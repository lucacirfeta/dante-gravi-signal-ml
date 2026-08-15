"""Reproducible DINOv2 model acquisition and loading.

Both executable source and weights are immutable inputs.  Online loading uses
a full Git commit; offline loading additionally verifies a deterministic hash
of the Python source tree.  Weights are always verified before deserialization.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
from urllib.request import urlopen

import torch

from src.core.artifact_manifest import (
    ArtifactManifestError,
    ModelArtifactSpec,
    resolve_model_artifact,
)
from src.core.index_contract import sha256_file


DEFAULT_MODEL_ARTIFACT_ID = "dinov2_vits14_reg"


def python_source_tree_sha256(source_dir: str | Path) -> str:
    """Hash normalized Python sources by relative path and content digest."""
    root = Path(source_dir).expanduser().resolve()
    hubconf = root / "hubconf.py"
    package = root / "dinov2"
    if not hubconf.is_file() or not package.is_dir():
        raise ArtifactManifestError(
            f"DINOv2 source mirror is incomplete: {root}"
        )
    files = [hubconf, *package.rglob("*.py")]
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        normalized = path.read_bytes().replace(b"\r\n", b"\n")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(hashlib.sha256(normalized).digest())
    return digest.hexdigest()


def _verify_weights(path: Path, spec: ModelArtifactSpec) -> None:
    if not path.is_file():
        raise ArtifactManifestError(f"DINOv2 weights not found: {path}")
    if spec.weights_bytes >= 0 and path.stat().st_size != spec.weights_bytes:
        raise ArtifactManifestError(
            f"DINOv2 weights size mismatch: expected {spec.weights_bytes}, "
            f"got {path.stat().st_size}"
        )
    actual = sha256_file(path)
    if actual != spec.weights_sha256:
        raise ArtifactManifestError(
            f"DINOv2 weights SHA-256 mismatch: expected "
            f"{spec.weights_sha256}, got {actual}"
        )


def _default_weights_path(spec: ModelArtifactSpec) -> Path:
    configured = os.environ.get("DANTE_DINOV2_WEIGHTS")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(torch.hub.get_dir()) / "checkpoints" / spec.weights_filename).resolve()


def acquire_dinov2_weights(
    destination: str | Path | None = None,
    *,
    manifest_path: str | Path | None = None,
    artifact_id: str = DEFAULT_MODEL_ARTIFACT_ID,
) -> Path:
    """Download weights atomically and accept them only after SHA-256 checks."""
    spec = resolve_model_artifact(artifact_id, manifest_path=manifest_path)
    target = (
        Path(destination).expanduser().resolve()
        if destination is not None
        else _default_weights_path(spec)
    )
    if target.exists():
        _verify_weights(target, spec)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".partial",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            with urlopen(spec.weights_url, timeout=60) as response:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
        _verify_weights(temporary, spec)
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


def _verified_local_source(
    spec: ModelArtifactSpec,
    explicit_source: str | Path | None,
) -> Path | None:
    candidates: list[Path] = []
    configured = explicit_source or os.environ.get("DANTE_DINOV2_REPO")
    if configured:
        candidates.append(Path(configured).expanduser().resolve())
    else:
        hub_root = Path(torch.hub.get_dir())
        owner, repository = spec.repository.split("/", 1)
        candidates.extend(
            [
                hub_root / f"{owner}_{repository}_{spec.revision}",
                hub_root / f"{owner}_{repository}_{spec.revision[:7]}",
                # torch.hub historically cached mutable main under this name.
                # It is accepted only when its complete Python tree matches.
                hub_root / f"{owner}_{repository}_main",
            ]
        )
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        actual = python_source_tree_sha256(candidate)
        if actual == spec.source_python_tree_sha256:
            return candidate.resolve()
        if configured:
            raise ArtifactManifestError(
                f"DINOv2 source-tree SHA-256 mismatch for {candidate}: "
                f"expected {spec.source_python_tree_sha256}, got {actual}"
            )
    return None


def _load_state_dict(path: Path) -> dict:
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except TypeError:  # PyTorch < 2.0 compatibility
        payload = torch.load(path, map_location="cpu")
    if not isinstance(payload, dict):
        raise ArtifactManifestError(
            f"DINOv2 weights must deserialize to a state dict, got {type(payload)!r}"
        )
    return payload


def load_dinov2_model(
    device: str | torch.device | None = None,
    *,
    source_dir: str | Path | None = None,
    weights_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
    artifact_id: str = DEFAULT_MODEL_ARTIFACT_ID,
    allow_download: bool = True,
) -> torch.nn.Module:
    """Load frozen DINOv2 from a pinned source revision and verified weights."""
    spec = resolve_model_artifact(artifact_id, manifest_path=manifest_path)
    weights = (
        Path(weights_path).expanduser().resolve()
        if weights_path is not None
        else _default_weights_path(spec)
    )
    if not weights.exists():
        if not allow_download:
            raise ArtifactManifestError(
                f"DINOv2 weights unavailable in offline mode: {weights}"
            )
        weights = acquire_dinov2_weights(
            weights,
            manifest_path=manifest_path,
            artifact_id=artifact_id,
        )
    _verify_weights(weights, spec)

    local_source = _verified_local_source(spec, source_dir)
    if local_source is not None:
        model = torch.hub.load(
            str(local_source),
            spec.entrypoint,
            source="local",
            pretrained=False,
        )
        source_provenance = str(local_source)
    else:
        if not allow_download:
            raise ArtifactManifestError(
                "No verified local DINOv2 source mirror is available. Set "
                "DANTE_DINOV2_REPO or run artifact acquisition online."
            )
        pinned_repository = f"{spec.repository}:{spec.revision}"
        model = torch.hub.load(
            pinned_repository,
            spec.entrypoint,
            pretrained=False,
            trust_repo=True,
            # torch.hub's GitHub API validation enumerates branches/tags and
            # rejects a full commit SHA even when the immutable archive exists.
            # The owner/repository are manifest-pinned and the downloaded code
            # is addressed by the complete 40-character commit.
            skip_validation=True,
        )
        source_provenance = pinned_repository

    state_dict = _load_state_dict(weights)
    model.load_state_dict(state_dict, strict=True)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad = False
    if device is not None:
        model.to(torch.device(device))
    model.dante_model_provenance = {
        "artifact_id": spec.artifact_id,
        "repository": spec.repository,
        "revision": spec.revision,
        "entrypoint": spec.entrypoint,
        "source": source_provenance,
        "source_python_tree_sha256": spec.source_python_tree_sha256,
        "weights_path": str(weights),
        "weights_sha256": spec.weights_sha256,
    }
    return model
