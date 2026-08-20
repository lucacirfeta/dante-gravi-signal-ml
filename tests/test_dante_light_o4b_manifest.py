from __future__ import annotations

import json

import pytest

from scripts import build_dante_light_o4b_manifest as o4b
from src.dante_light.contracts import canonical_json_sha256


def test_select_windows_requires_cat1_whitening_context() -> None:
    starts = o4b.select_windows([[100.0, 400.0]], 100, 400, count=2)
    assert starts == [128, 160]
    assert starts[0] - o4b.WHITENING_PAD_S >= 100
    assert starts[-1] + o4b.WINDOW_S + o4b.WHITENING_PAD_S <= 400


def test_select_windows_fails_closed_on_insufficient_dq() -> None:
    with pytest.raises(RuntimeError, match="provides only"):
        o4b.select_windows([[100.0, 140.0]], 100, 140, count=1)


def test_build_is_outcome_blind_and_temporally_held_out(
    tmp_path, monkeypatch
) -> None:
    reference_manifest = (
        o4b.ROOT / "config" / "reference_artifacts.json"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(o4b, "ROOT", tmp_path)
    monkeypatch.setattr(o4b, "WINDOWS_PER_DETECTOR_BLOCK", 1)
    monkeypatch.setattr(o4b, "EVALUATION_BLOCKS", ((2000, 2200), (3000, 3200)))
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "reference_artifacts.json").write_text(
        reference_manifest, encoding="utf-8"
    )
    snapshot = {
        "schema_version": 1,
        "status": "frozen_dq_only",
        "run": "O4B",
        "source": {"outcome_data_accessed": False},
        "segments": {
            "H1": [[1900.0, 3300.0]],
            "L1": [[1900.0, 3300.0]],
        },
    }
    snapshot["snapshot_sha256"] = canonical_json_sha256(snapshot)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    output_path = tmp_path / "manifest.json"

    payload, entries = o4b.build(snapshot_path, output_path)

    assert payload["status"] == "locked_before_scoring"
    assert payload["outcome_fields_used_for_selection"] == []
    assert len(entries) == 4
    assert all(entry["expected"] == {} for entry in entries)
    assert all(entry["window"]["run"] == "O4B" for entry in entries)
    assert min(entry["window"]["gps_start"] for entry in entries) > 1000
