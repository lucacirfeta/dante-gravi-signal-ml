"""Verify, package, download, and install DANTE scientific artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import tempfile
from urllib.request import urlopen
import zipfile

import numpy as np

from src.core.artifact_manifest import (
    ArtifactManifestError,
    get_artifact_manifest_path,
    resolve_model_artifact,
    resolve_reference_index,
)
from src.core.index_contract import read_index_metadata, sha256_file


REFERENCE_BUNDLE_MEMBERS = (
    "config/reference_artifacts.json",
    "data/reference/patch_compressed_index_o3b.npz",
    "data/reference/patch_compressed_index_o4a_q4-64_ex.npz",
    "data/reference/patch_compressed_index_o4a_q4-64_ex.t_bg.json",
    "data/reference/environment_build_native_index_o4a_q4-64.json",
    "data/reference/source_state_build_native_index_o4a_q4-64.zip",
    "docs/REFERENCE_ARTIFACT_BUNDLE.md",
    "LICENSE",
)


def verify_reference_indices(
    *,
    manifest_path: str | Path | None = None,
    allow_missing: bool = False,
) -> list[dict]:
    """Verify every declared NPZ against path, SHA-256, shape and Q-range."""
    manifest = get_artifact_manifest_path(manifest_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    results: list[dict] = []
    for artifact_id, raw in payload.get("reference_indices", {}).items():
        root = (manifest.parent / str(payload.get("artifact_root", "."))).resolve()
        path = (root / str(raw["path"])).resolve()
        if not path.exists():
            if allow_missing:
                results.append(
                    {"artifact_id": artifact_id, "path": str(path), "status": "MISSING"}
                )
                continue
            raise ArtifactManifestError(f"Reference index missing: {path}")
        spec = resolve_reference_index(path, manifest_path=manifest)
        actual_sha256 = sha256_file(path)
        if actual_sha256 != spec.sha256:
            raise ArtifactManifestError(
                f"Reference index SHA-256 mismatch for {artifact_id}: "
                f"{actual_sha256} != {spec.sha256}"
            )
        with np.load(path, allow_pickle=False) as data:
            if "embeddings" not in data.files:
                raise ArtifactManifestError(f"Index {artifact_id} lacks embeddings")
            shape = tuple(int(value) for value in data["embeddings"].shape)
        expected_shape = (spec.n_centroids, spec.embedding_dim)
        if shape != expected_shape:
            raise ArtifactManifestError(
                f"Reference index shape mismatch for {artifact_id}: "
                f"{shape} != {expected_shape}"
            )
        embedded = read_index_metadata(path)
        if embedded.get("qrange") is not None and spec.qrange is not None:
            if tuple(int(value) for value in embedded["qrange"]) != spec.qrange:
                raise ArtifactManifestError(
                    f"Reference index Q-range mismatch for {artifact_id}"
                )
        results.append(
            {
                "artifact_id": artifact_id,
                "path": str(path),
                "status": "VERIFIED",
                "sha256": actual_sha256,
                "shape": list(shape),
                "qrange": list(spec.qrange) if spec.qrange else None,
                "qrange_declared_in_npz": "qrange" in embedded,
            }
        )
    if not results:
        raise ArtifactManifestError(f"No reference indices declared in {manifest}")
    return results


def _manifest_lines(files: dict[str, bytes]) -> str:
    return "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(files.items())
    )


def build_reference_bundle(
    output_path: str | Path,
    *,
    project_root: str | Path,
) -> dict:
    """Create an arXiv-safe/Unix-safe ZIP containing exact reference inputs."""
    root = Path(project_root).resolve()
    verify_reference_indices(manifest_path=root / "config/reference_artifacts.json")
    files: dict[str, bytes] = {}
    for member in REFERENCE_BUNDLE_MEMBERS:
        source = root / PurePosixPath(member)
        if not source.is_file():
            raise ArtifactManifestError(f"Bundle source missing: {source}")
        files[member] = source.read_bytes()
    files["MANIFEST.sha256"] = _manifest_lines(files).encode("utf-8")

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.partial")
    if temporary.exists():
        temporary.unlink()
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for member, data in sorted(files.items()):
                info = zipfile.ZipInfo(member)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return {
        "path": str(output),
        "sha256": sha256_file(output),
        "bytes": output.stat().st_size,
        "members": len(files),
    }


def verify_reference_bundle(bundle_path: str | Path) -> dict:
    """Validate safe member names and every bundle-level SHA-256."""
    bundle = Path(bundle_path).resolve()
    with zipfile.ZipFile(bundle, "r") as archive:
        names = archive.namelist()
        for name in names:
            pure = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or pure.is_absolute()
                or ".." in pure.parts
            ):
                raise ArtifactManifestError(f"Unsafe ZIP member: {name!r}")
        if "MANIFEST.sha256" not in names:
            raise ArtifactManifestError("Reference bundle lacks MANIFEST.sha256")
        lines = archive.read("MANIFEST.sha256").decode("utf-8").splitlines()
        checked = 0
        for line in lines:
            expected, separator, name = line.partition("  ")
            if not separator or name not in names:
                raise ArtifactManifestError(f"Malformed bundle manifest line: {line}")
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != expected:
                raise ArtifactManifestError(
                    f"Bundle member SHA-256 mismatch for {name}: {actual} != {expected}"
                )
            checked += 1
    return {
        "path": str(bundle),
        "sha256": sha256_file(bundle),
        "members_checked": checked,
        "status": "VERIFIED",
    }


def install_reference_bundle(
    bundle_path: str | Path,
    *,
    project_root: str | Path,
) -> dict:
    """Install verified bundle members without overwriting divergent files."""
    verification = verify_reference_bundle(bundle_path)
    root = Path(project_root).resolve()
    installed: list[str] = []
    already_present: list[str] = []
    with zipfile.ZipFile(Path(bundle_path).resolve(), "r") as archive:
        if "config/reference_artifacts.json" not in archive.namelist():
            raise ArtifactManifestError(
                "Reference bundle lacks config/reference_artifacts.json"
            )
        bundled_contract = json.loads(
            archive.read("config/reference_artifacts.json").decode("utf-8")
        )
        local_manifest = root / "config/reference_artifacts.json"
        if local_manifest.exists():
            local_contract = json.loads(local_manifest.read_text(encoding="utf-8"))
            for section in ("models", "reference_indices"):
                if local_contract.get(section) != bundled_contract.get(section):
                    raise ArtifactManifestError(
                        f"Local and bundled {section} contracts disagree; "
                        "refusing mixed scientific inputs"
                    )

        for artifact_id, raw in bundled_contract.get("reference_indices", {}).items():
            member = PurePosixPath(str(raw["path"])).as_posix()
            if member not in archive.namelist():
                raise ArtifactManifestError(
                    f"Bundle lacks declared index {artifact_id}: {member}"
                )
            data = archive.read(member)
            actual = hashlib.sha256(data).hexdigest()
            if actual != str(raw["sha256"]).lower():
                raise ArtifactManifestError(
                    f"Bundled index contract mismatch for {artifact_id}"
                )

        install_members = [
            name for name in archive.namelist() if name.startswith("data/reference/")
        ]
        for member in install_members:
            target = (root / PurePosixPath(member)).resolve()
            expected_parent = (root / "data/reference").resolve()
            if target != expected_parent and expected_parent not in target.parents:
                raise ArtifactManifestError(f"Unsafe install target: {target}")
            data = archive.read(member)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(data).digest():
                    raise ArtifactManifestError(
                        f"Refusing to overwrite divergent artifact: {target}"
                    )
                already_present.append(member)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.partial")
            temporary.write_bytes(data)
            temporary.replace(target)
            installed.append(member)
    return {
        **verification,
        "installed": installed,
        "already_present": already_present,
    }


def download_reference_bundle(
    destination: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> Path:
    """Download the deposited bundle atomically once its URL is published."""
    manifest = get_artifact_manifest_path(manifest_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    contract = payload.get("reference_bundle", {})
    url = contract.get("url")
    expected = contract.get("sha256")
    if not url or not expected:
        raise ArtifactManifestError(
            "The validated reference bundle has not been deposited yet. "
            "The software DOI 10.5281/zenodo.21912589 and evidence DOI "
            "10.5281/zenodo.21925453 do not contain the NPZ dictionaries."
        )
    target = Path(destination).resolve()
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
            with urlopen(str(url), timeout=60) as response:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    handle.write(chunk)
        actual = sha256_file(temporary)
        if actual != str(expected).lower():
            raise ArtifactManifestError(
                f"Reference bundle SHA-256 mismatch: {actual} != {expected}"
            )
        verify_reference_bundle(temporary)
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return target


def model_contract_summary(
    *,
    manifest_path: str | Path | None = None,
) -> dict:
    spec = resolve_model_artifact(
        "dinov2_vits14_reg", manifest_path=manifest_path
    )
    return {
        "artifact_id": spec.artifact_id,
        "repository": spec.repository,
        "revision": spec.revision,
        "weights_sha256": spec.weights_sha256,
        "weights_bytes": spec.weights_bytes,
        "source_python_tree_sha256": spec.source_python_tree_sha256,
    }
