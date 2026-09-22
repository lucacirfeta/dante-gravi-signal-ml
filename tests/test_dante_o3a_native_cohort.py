from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_native_cohort import (
    _quality_check_values,
    _scan_identity_rows,
    _source_rows_for_context,
    load_cohort_contract,
    proposal_priority,
    select_native_proposals,
)


def test_priority_is_contract_detector_and_gps_bound() -> None:
    first = proposal_priority("contract", "H1", 123)
    assert first == proposal_priority("contract", "H1", 123)
    assert first != proposal_priority("contract-2", "H1", 123)
    assert first != proposal_priority("contract", "L1", 123)
    assert first != proposal_priority("contract", "H1", 124)


def test_selector_uses_cross_detector_inclusive_guard() -> None:
    rows = [
        ("H1", 100, True),
        ("L1", 228, False),
        ("L1", 229, False),
        ("H1", 400, False),
    ]
    proposals, counts = select_native_proposals(
        rows,
        stage_contract_digest="stage",
        candidate_guard_delta_s=128,
        minimum_separation_s=96,
    )
    assert [row["gps_start"] for row in proposals["L1"]] == [229]
    assert counts["L1"]["candidate_guard"] == 1
    assert [row["gps_start"] for row in proposals["H1"]] == [400]


def test_selector_allows_exact_minimum_separation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.dante_light.o3a_native_cohort.proposal_priority",
        lambda _digest, _detector, gps: f"{gps:08d}",
    )
    proposals, counts = select_native_proposals(
        [("H1", 100, False), ("H1", 195, False), ("H1", 196, False)],
        stage_contract_digest="stage",
        candidate_guard_delta_s=128,
        minimum_separation_s=96,
    )
    assert [row["gps_start"] for row in proposals["H1"]] == [100, 196]
    assert counts["H1"]["proposal_separation"] == 1


def test_scan_reader_omits_primary_score_and_class_columns(tmp_path: Path) -> None:
    database = tmp_path / "scan.sqlite"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE windows("
        "detector TEXT, gps_start INTEGER, is_candidate INTEGER, "
        "primary_score REAL, class TEXT)"
    )
    connection.executemany(
        "INSERT INTO windows VALUES(?,?,?,?,?)",
        [("H1", 100, 0, 9.9, "SECRET"), ("L1", 200, 1, 8.8, "SECRET")],
    )
    connection.commit()
    connection.close()
    assert _scan_identity_rows(database) == [
        ("H1", 100, False),
        ("L1", 200, True),
    ]


def test_source_resolver_stitches_exact_symmetric_context() -> None:
    frames = [
        {
            "gps_start": 0,
            "gps_end": 128,
            "filename": "a.hdf5",
            "url": "https://example/a",
        },
        {
            "gps_start": 128,
            "gps_end": 256,
            "filename": "b.hdf5",
            "url": "https://example/b",
        },
    ]
    ledger = {
        ("H1", "a.hdf5"): {
            **frames[0],
            "detector": "H1",
            "sha256": "a" * 64,
            "size_bytes": 1,
        },
        ("H1", "b.hdf5"): {
            **frames[1],
            "detector": "H1",
            "sha256": "b" * 64,
            "size_bytes": 1,
        },
    }
    sources = _source_rows_for_context(
        detector="H1",
        gps=96,
        frames=frames,
        frame_starts=[0, 128],
        raw_frame_rows=ledger,
    )
    assert [row["used_interval_gps"] for row in sources] == [
        [92, 128],
        [128, 132],
    ]


def test_quality_check_runs_whitening_before_clean_crop() -> None:
    values = np.random.default_rng(42).normal(size=40 * 4096).astype(np.float64)
    result = _quality_check_values((values, 100, "H1"))
    assert result["quality_disposition"] in {
        "PASS_CLEAN",
        "EXCESS_POWER_VETO",
    }
    assert result["clean_window_shape"] == [32 * 4096]
    assert len(result["clean_window_sha256"]) == 64


def test_frozen_contract_binds_approved_firewall_and_parity_veto() -> None:
    value = load_cohort_contract()
    assert value["selection"]["target_rows_per_detector"] == 647
    assert value["selection"]["candidate_guard_start_delta_s"] == 128
    assert value["selection"]["minimum_same_detector_separation_s"] == 96
    assert value["selection"]["primary_score_or_class_read"] is False
    assert value["preprocessing"]["excess_power_veto"]["function"] == (
        "excess_power_veto"
    )
    assert value["population_firewall"][
        "native_calibration_selected_after_index_manifest"
    ] is True
    assert value["population_firewall"][
        "native_calibration_must_be_disjoint_from_index"
    ] is True


def test_contract_rejects_digest_drift(tmp_path: Path) -> None:
    value = load_cohort_contract()
    value["selection"]["target_rows_per_detector"] = 648
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    from src.dante_light.o3a_native_cohort import validate_cohort_contract

    with pytest.raises(ContractError, match="digest mismatch"):
        validate_cohort_contract(json.loads(path.read_text(encoding="utf-8")))
