"""Checks for the compact O4a provenance release bundle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile

from scripts.build_o4a_provenance_release_bundle import build_bundle


ROOT = Path(__file__).resolve().parents[1]


def test_all_canonical_provenance_json_files_are_checkout_stable() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")

    assert "config/dante_o4a_canonical_provenance_*.json text eol=lf" in attributes


def test_provenance_release_bundle_is_complete_and_reproducible(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_manifest = build_bundle(first)
    second_manifest = build_bundle(second)

    assert first.read_bytes() == second.read_bytes()
    assert first_manifest == second_manifest
    assert first_manifest["release_version"] == "3.8.1"
    assert first_manifest["scientific_change"] is False
    assert first_manifest["result"] == "BYTE_IDENTICAL_SCIENTIFIC_OUTPUTS"
    assert len(first_manifest["stages"]) == 10
    assert all(stage["status"].startswith("PASS_VERIFIED") for stage in first_manifest["stages"])

    with zipfile.ZipFile(first) as archive:
        names = set(archive.namelist())
        assert all(info.create_system == 3 for info in archive.infolist())
        assert all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
        assert "MANIFEST.json" in names
        assert "DANTE_O4A_PROVENANCE_TRANSPARENCY_NOTE.md" in names
        assert len([name for name in names if name.startswith("evidence/")]) == 10
        embedded = json.loads(archive.read("MANIFEST.json"))
        for name, metadata in embedded["files"].items():
            payload = archive.read(name)
            assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
            assert len(payload) == metadata["size_bytes"]


def test_final_compare_evidence_is_bound_to_verified_canonical_run() -> None:
    evidence = json.loads(
        (
            ROOT
            / "artifacts/dante_light/o4a_v1_parity/provenance_rerun_v1/"
            "corrected_final_comparison_v2.json"
        ).read_text(encoding="utf-8")
    )

    assert evidence["status"] == "PASS_VERIFIED_CANONICAL_FINAL_COMPARISON"
    assert evidence["run_key"] == (
        "7db808838ce9f0ca4149048ec6257695b9dccfb3e3b16ce382b8e350d2d03371"
    )
    assert evidence["contract_digest"] == (
        "ffe704a9771048274a55f03d809deb9c37940081df02e363f96c8b5cd571c548"
    )
