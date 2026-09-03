from __future__ import annotations

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_gps_identity_audit import (
    ROOT,
    load_contract,
    summarize_calibration_geometry,
    summarize_candidate_geometry,
    validate_contract,
)


def test_frozen_gps_identity_contract_validates() -> None:
    contract = load_contract(ROOT)
    assert contract["acceptance"]["candidate_catalog_offset_s"] == 4.0
    assert contract["scientific_boundary"][
        "candidate_transform_may_not_be_reused_for_calibration"
    ] is True


def test_contract_rejects_mutation() -> None:
    contract = load_contract(ROOT)
    contract["acceptance"]["candidate_catalog_offset_s"] = 0.0
    with pytest.raises(ContractError, match="digest mismatch"):
        validate_contract(contract, root=ROOT)


def test_candidate_geometry_requires_uniform_plus_four() -> None:
    entry = {
        "case_id": "a",
        "catalog_identity": {"detector": "L1", "gps_start": 100.0},
        "required_padded_interval_gps": [100.0, 140.0],
        "window": {"detector": "L1", "gps_start": 104.0, "duration_s": 32.0},
    }
    edge = {
        **entry,
        "local_stitch": {
            "components": [{"file_interval_gps": [0.0, 136.0]}]
        },
    }
    summary = summarize_candidate_geometry([entry], [edge])
    assert summary["offset_counts_s"] == {"4.0": 1}
    assert summary["edge_historical_boundary_offset_counts_s"] == {"36.0": 1}
    assert summary["geometry_failures"] == 0


def _calibration_row(disposition: str) -> dict:
    catalog = 100.0
    analysis = 100.0 if disposition == "HISTORICAL_LEFT_TRUNCATED_4S" else 104.0
    source = [100.0, 500.0]
    if disposition == "HISTORICAL_RIGHT_TRUNCATED_4S":
        source = [0.0, 136.0]
    return {
        "session_id": 1,
        "detector": "H1",
        "catalog_gps_start": catalog,
        "analysis_gps_start": analysis,
        "historical_context_disposition": disposition,
        "historical_context_interval": [
            catalog,
            catalog + (40.0 if disposition == "HISTORICAL_FULL_SYMMETRIC_4S" else 36.0),
        ],
        "historical_source_span": source,
        "required_padded_interval": [analysis - 4.0, analysis + 36.0],
    }


def test_calibration_geometry_preserves_left_edge_exception() -> None:
    rows = [
        _calibration_row("HISTORICAL_FULL_SYMMETRIC_4S"),
        _calibration_row("HISTORICAL_LEFT_TRUNCATED_4S"),
        _calibration_row("HISTORICAL_RIGHT_TRUNCATED_4S"),
    ]
    rows[1]["session_id"] = 2
    rows[2]["session_id"] = 3
    summary = summarize_calibration_geometry(rows)
    assert summary["offset_counts_s"] == {"0.0": 1, "4.0": 2}
    assert summary["geometry_failures"] == 0


def test_calibration_left_edge_rejects_uniform_plus_four() -> None:
    row = _calibration_row("HISTORICAL_LEFT_TRUNCATED_4S")
    row["analysis_gps_start"] = 104.0
    row["required_padded_interval"] = [100.0, 140.0]
    assert summarize_calibration_geometry([row])["geometry_failures"] == 1
