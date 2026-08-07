from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts import build_paper_reproducibility_bundle as bundle


def test_unsafe_paths_are_rejected() -> None:
    for value in ("../secret", "/absolute/file", "archive/stale.json", "x_pilot.json"):
        with pytest.raises(RuntimeError):
            bundle._safe_relative(value)


def test_portability_rewrite_is_explicit_and_removes_machine_paths() -> None:
    source = (
        r'{"repo":"C:\\Users\\atafe\\PycharmProjects\\dante-gravi-signal-ml\\data\\x.json",'
        r'"raw":"E:\\o4a\\session\\H1.hdf5"}'
    ).encode()
    observed, changed = bundle._portable_text(source)
    assert changed is True
    assert b"C:\\\\Users" not in observed
    assert b"E:\\\\o4a" not in observed
    assert b"GWOSC_RAW_DATA_NOT_BUNDLED" in observed


def test_current_allowlist_is_final_and_master_hashes_match() -> None:
    paths = bundle.source_paths()
    assert len(paths) > 180
    assert len(paths) == len(set(paths))
    assert all("pilot" not in Path(path).name.lower() for path in paths)
    assert all("archive" not in Path(path).parts for path in paths)
    assert sum(path.endswith(".png") for path in paths) >= 9
    assert sum("null_calibration_" in path for path in paths) == 141


def test_build_and_check_round_trip(tmp_path: Path) -> None:
    release = tmp_path / "bundle"
    zip_path = tmp_path / "bundle.zip"
    bundle.build(release, zip_path)
    bundle.check(release, zip_path)
    manifest = (release / "MANIFEST.sha256").read_text(encoding="utf-8")
    provenance = json.loads((release / "SOURCE_PROVENANCE.json").read_text(encoding="utf-8"))
    assert "Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv" in manifest
    assert any(item["portable_text_rewrite"] for item in provenance["files"])
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.testzip() is None
        assert archive.read("MANIFEST.sha256") == (release / "MANIFEST.sha256").read_bytes()
