"""Regression tests for public scientific-artifact handling."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

import numpy as np
import pytest

from src.core.artifact_manager import (
    download_reference_bundle,
    install_reference_bundle,
    verify_reference_bundle,
    verify_reference_indices,
)
from src.core.artifact_manifest import ArtifactManifestError


def _index_manifest(tmp_path: Path) -> Path:
    index = tmp_path / "index.npz"
    np.savez(
        index,
        embeddings=np.ones((2, 384), dtype=np.float32),
        labels=np.array(["BG", "BG"]),
        meta=json.dumps({"qrange": [4, 64]}),
    )
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    manifest = tmp_path / "artifacts.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifact_root": ".",
                "reference_bundle": {
                    "publication_status": "not_deposited",
                    "url": None,
                    "sha256": None,
                },
                "reference_indices": {
                    "fixture": {
                        "path": index.name,
                        "sha256": digest,
                        "embedding_dim": 384,
                        "n_centroids": 2,
                        "qrange": [4, 64],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return manifest


def test_reference_index_verifier_checks_hash_shape_and_qrange(tmp_path) -> None:
    manifest = _index_manifest(tmp_path)
    result = verify_reference_indices(manifest_path=manifest)
    assert result[0]["status"] == "VERIFIED"
    assert result[0]["shape"] == [2, 384]
    assert result[0]["qrange"] == [4, 64]


def test_reference_bundle_verifier_rejects_path_traversal_members(tmp_path) -> None:
    bundle = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("../reference/index.npz", b"unsafe")
        archive.writestr("MANIFEST.sha256", b"")
    with pytest.raises(ArtifactManifestError, match="Unsafe ZIP member"):
        verify_reference_bundle(bundle)


def test_reference_bundle_download_fails_honestly_before_deposit(tmp_path) -> None:
    manifest = _index_manifest(tmp_path)
    with pytest.raises(ArtifactManifestError, match="has not been deposited"):
        download_reference_bundle(
            tmp_path / "bundle.zip",
            manifest_path=manifest,
        )


def test_reference_bundle_install_is_verified_and_non_overwriting(tmp_path) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    index_buffer = tmp_path / "index.npz"
    np.savez(
        index_buffer,
        embeddings=np.ones((2, 384), dtype=np.float32),
        labels=np.array(["BG", "BG"]),
        meta=json.dumps({"qrange": [4, 64]}),
    )
    index_bytes = index_buffer.read_bytes()
    contract = {
        "schema_version": 1,
        "artifact_root": "..",
        "models": {},
        "reference_indices": {
            "fixture": {
                "path": "data/reference/index.npz",
                "sha256": hashlib.sha256(index_bytes).hexdigest(),
                "embedding_dim": 384,
                "n_centroids": 2,
                "qrange": [4, 64],
            }
        },
    }
    contract_bytes = json.dumps(contract).encode("utf-8")
    members = {
        "config/reference_artifacts.json": contract_bytes,
        "data/reference/index.npz": index_bytes,
    }
    manifest_bytes = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(members.items())
    ).encode("utf-8")
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
        archive.writestr("MANIFEST.sha256", manifest_bytes)
    (project / "config/reference_artifacts.json").write_bytes(contract_bytes)

    result = install_reference_bundle(bundle, project_root=project)
    installed = project / "data/reference/index.npz"
    assert installed.read_bytes() == index_bytes
    assert result["installed"] == ["data/reference/index.npz"]

    installed.write_bytes(b"divergent")
    with pytest.raises(ArtifactManifestError, match="Refusing to overwrite"):
        install_reference_bundle(bundle, project_root=project)


def test_user_docs_do_not_restore_superseded_setup_claims() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    cli = (root / "CLI_REFERENCE.md").read_text(encoding="utf-8")
    citation = (root / "CITATION.cff").read_text(encoding="utf-8")
    assert "Download the reference index from the\n" not in readme
    assert "3,593 ROBUST / 2,109 AMBIGUOUS / 4,670 BACKGROUND" not in readme
    assert "zero I/O overhead" not in cli
    assert "theoretical GEV thresholding" not in cli
    assert 'version: "3.7.0"' in citation
    assert 'doi: "10.5281/zenodo.21912589"' in citation
