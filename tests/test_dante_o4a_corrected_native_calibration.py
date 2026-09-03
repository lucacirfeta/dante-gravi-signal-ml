from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_calibration import (
    ROOT,
    _within_start_guard,
    load_native_calibration_contract,
    select_native_calibration_rows,
    validate_native_calibration_contract,
)
from src.pipeline_v2_production.background_calibration import RawBlock


def _reseal(value: dict) -> dict:
    updated = copy.deepcopy(value)
    updated.pop("contract_digest", None)
    updated["contract_digest"] = canonical_json_sha256(updated)
    return updated


def test_native_calibration_contract_freezes_authorized_boundary() -> None:
    contract = load_native_calibration_contract(ROOT)
    population = contract["population"]
    assert population["target_rows_by_detector"] == {"H1": 5000, "L1": 5000}
    assert population["temporal_block_length"] == 17
    assert population["forbidden_guard_s"] == 96.0
    assert population["equivalent_start_delta_s"] == 128.0
    boundary = contract["scientific_boundary"]
    assert boundary["candidate_guard_is_cross_detector"] is True
    assert boundary["native_index_guard_is_cross_detector"] is True
    assert boundary["historical_calibration_population_reused"] is False
    assert contract["future_threshold_contract"]["bootstrap_replicates"] == 1_000_000


def test_native_calibration_contract_rejects_scientific_drift() -> None:
    contract = load_native_calibration_contract(ROOT)
    changed = copy.deepcopy(contract)
    changed["scientific_boundary"]["historical_calibration_population_reused"] = True
    with pytest.raises(ContractError, match="scientific boundary"):
        validate_native_calibration_contract(_reseal(changed), ROOT)


def test_start_guard_is_strict_at_frozen_128_second_boundary() -> None:
    assert _within_start_guard(100.0, [227.999], 128.0)
    assert not _within_start_guard(100.0, [228.0], 128.0)


def test_selector_applies_candidate_and_index_guards_cross_detector(tmp_path: Path) -> None:
    source_h1 = tmp_path / "H1.hdf5"
    source_l1 = tmp_path / "L1.hdf5"
    source_h1.touch()
    source_l1.touch()
    starts = [float(value) for value in range(4, 20_000, 64)]
    geometry = {
        detector: {
            gps: {
                "image_sha256": ("a" if detector == "H1" else "b") * 64,
                "identity_digest": ("c" if detector == "H1" else "d") * 64,
                "is_candidate": False,
            }
            for gps in starts
        }
        for detector in ("H1", "L1")
    }
    rows, audit = select_native_calibration_rows(
        raw_blocks_by_detector={
            "H1": [RawBlock(0.0, 20_100.0, source_h1)],
            "L1": [RawBlock(0.0, 20_100.0, source_l1)],
        },
        source_sha256_by_detector={
            "H1": {source_h1.resolve(): "e" * 64},
            "L1": {source_l1.resolve(): "f" * 64},
        },
        scan_geometry=geometry,
        candidate_times=[132.0],
        native_index_times=[900.0],
        run_bounds=(0.0, 20_100.0),
        raw_root=tmp_path,
        target_rows_by_detector={"H1": 34, "L1": 34},
        block_length=17,
        guard_s=96.0,
        pad_s=4.0,
        window_s=32.0,
        stride_s=64.0,
    )
    assert len(rows) == 68
    assert audit["H1"]["selected_rows"] == 34
    assert audit["L1"]["selected_rows"] == 34
    assert all(abs(float(row["gps_start"]) - 132.0) >= 128.0 for row in rows)
    assert all(abs(float(row["gps_start"]) - 900.0) >= 128.0 for row in rows)


def test_scan_query_is_outcome_firewalled() -> None:
    source = (ROOT / "src/dante_light/o4a_corrected_native_calibration.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    sql_literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "SELECT detector,gps_start" in node.value
    ]
    assert sql_literals == [
        "SELECT detector,gps_start,image_sha256,is_candidate,identity_digest "
        "FROM windows ORDER BY detector,gps_start"
    ]
    assert all(
        forbidden not in sql_literals[0]
        for forbidden in ("primary_score", "score_hex", "taxonomy", "class")
    )
