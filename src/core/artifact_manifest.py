"""Trusted, portable contracts for DANTE reference artifacts.

The manifest is the trust anchor for immutable scientific inputs.  An NPZ
cannot safely declare its own digest (that would be self-referential), so the
expected SHA-256 is stored in a small version-controlled JSON document.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_MANIFEST = _PROJECT_ROOT / "config" / "reference_artifacts.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArtifactManifestError(RuntimeError):
    """Raised when a scientific artifact is absent or violates its contract."""


@dataclass(frozen=True)
class ReferenceIndexSpec:
    artifact_id: str
    path: Path
    sha256: str
    embedding_dim: int
    n_centroids: int
    qrange: tuple[int, int] | None
    metadata: dict
    manifest_path: Path


@dataclass(frozen=True)
class ModelArtifactSpec:
    artifact_id: str
    repository: str
    revision: str
    entrypoint: str
    weights_filename: str
    weights_url: str
    weights_sha256: str
    weights_bytes: int
    source_python_tree_sha256: str
    metadata: dict
    manifest_path: Path


def get_artifact_manifest_path(path: str | Path | None = None) -> Path:
    """Return an explicit, environment-provided, or repository manifest."""
    if path is not None:
        return Path(path).expanduser().resolve()
    configured = os.environ.get("DANTE_ARTIFACT_MANIFEST")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_ARTIFACT_MANIFEST.resolve()


def _load_manifest(path: Path) -> tuple[dict, Path]:
    if not path.exists():
        raise ArtifactManifestError(
            f"Reference artifact manifest not found: {path}. "
            "Set DANTE_ARTIFACT_MANIFEST or acquire the release artifacts."
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactManifestError(f"Invalid artifact manifest {path}: {exc}") from exc
    if int(payload.get("schema_version", -1)) != 1:
        raise ArtifactManifestError(
            f"Unsupported artifact manifest schema in {path}: "
            f"{payload.get('schema_version')!r}"
        )
    root = (path.parent / str(payload.get("artifact_root", "."))).resolve()
    return payload, root


def resolve_reference_index(
    index_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> ReferenceIndexSpec:
    """Resolve *index_path* to one exact manifest entry.

    Matching uses normalized absolute paths, not basenames, preventing a file
    with a trusted name in an unrelated directory from inheriting the digest.
    """
    requested = Path(index_path).expanduser().resolve()
    manifest = get_artifact_manifest_path(manifest_path)
    payload, artifact_root = _load_manifest(manifest)
    entries = payload.get("reference_indices")
    if not isinstance(entries, dict) or not entries:
        raise ArtifactManifestError(
            f"Manifest {manifest} contains no reference_indices"
        )

    matches: list[ReferenceIndexSpec] = []
    for artifact_id, raw in entries.items():
        if not isinstance(raw, dict) or "path" not in raw:
            raise ArtifactManifestError(
                f"Malformed reference index entry {artifact_id!r} in {manifest}"
            )
        declared_path = (artifact_root / str(raw["path"])).resolve()
        digest = str(raw.get("sha256", "")).lower()
        if not _SHA256_RE.fullmatch(digest):
            raise ArtifactManifestError(
                f"Invalid SHA-256 for {artifact_id!r} in {manifest}"
            )
        if declared_path != requested:
            continue
        qrange_raw = raw.get("qrange")
        qrange = None
        if qrange_raw is not None:
            if not isinstance(qrange_raw, list) or len(qrange_raw) != 2:
                raise ArtifactManifestError(
                    f"Invalid qrange for {artifact_id!r} in {manifest}"
                )
            qrange = (int(qrange_raw[0]), int(qrange_raw[1]))
        matches.append(
            ReferenceIndexSpec(
                artifact_id=str(artifact_id),
                path=declared_path,
                sha256=digest,
                embedding_dim=int(raw.get("embedding_dim", 384)),
                n_centroids=int(raw.get("n_centroids", -1)),
                qrange=qrange,
                metadata=dict(raw),
                manifest_path=manifest,
            )
        )

    if len(matches) != 1:
        raise ArtifactManifestError(
            f"Reference index {requested} must match exactly one entry in "
            f"{manifest}; matched {len(matches)}"
        )
    return matches[0]


def resolve_model_artifact(
    artifact_id: str,
    *,
    manifest_path: str | Path | None = None,
) -> ModelArtifactSpec:
    """Load one immutable model code-and-weights contract."""
    manifest = get_artifact_manifest_path(manifest_path)
    payload, _ = _load_manifest(manifest)
    entries = payload.get("models")
    if not isinstance(entries, dict) or artifact_id not in entries:
        raise ArtifactManifestError(
            f"Model artifact {artifact_id!r} is not declared in {manifest}"
        )
    raw = entries[artifact_id]
    if not isinstance(raw, dict):
        raise ArtifactManifestError(
            f"Malformed model artifact {artifact_id!r} in {manifest}"
        )
    weights_sha256 = str(raw.get("weights_sha256", "")).lower()
    tree_sha256 = str(raw.get("source_python_tree_sha256", "")).lower()
    if not _SHA256_RE.fullmatch(weights_sha256):
        raise ArtifactManifestError(
            f"Invalid weights SHA-256 for model {artifact_id!r}"
        )
    if not _SHA256_RE.fullmatch(tree_sha256):
        raise ArtifactManifestError(
            f"Invalid source-tree SHA-256 for model {artifact_id!r}"
        )
    revision = str(raw.get("revision", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ArtifactManifestError(
            f"Model {artifact_id!r} must pin a full 40-character commit"
        )
    required = ("repository", "entrypoint", "weights_filename", "weights_url")
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ArtifactManifestError(
            f"Model {artifact_id!r} lacks fields: {missing}"
        )
    return ModelArtifactSpec(
        artifact_id=artifact_id,
        repository=str(raw["repository"]),
        revision=revision,
        entrypoint=str(raw["entrypoint"]),
        weights_filename=str(raw["weights_filename"]),
        weights_url=str(raw["weights_url"]),
        weights_sha256=weights_sha256,
        weights_bytes=int(raw.get("weights_bytes", -1)),
        source_python_tree_sha256=tree_sha256,
        metadata=dict(raw),
        manifest_path=manifest,
    )
