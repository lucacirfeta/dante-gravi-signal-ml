from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore_v2 import (
    ROOT,
    _run_key,
    calibration_v2_rows,
    load_native_rescore_v2_contract,
    validate_native_rescore_v2_contract,
    validate_v2_input_rows,
)


def _reseal(value: dict) -> dict:
    updated = copy.deepcopy(value)
    updated.pop("contract_digest", None)
    updated["contract_digest"] = canonical_json_sha256(updated)
    return updated


def test_contract_freezes_new_calibration_and_unchanged_scoring() -> None:
    contract = load_native_rescore_v2_contract(ROOT)
    assert contract["scientific_boundary"]["native_calibration_identities_changed"] is True
    assert contract["scientific_boundary"]["primary_candidate_identities_changed"] is False
    assert contract["scientific_boundary"]["preprocessing_changed"] is False
    assert contract["scientific_boundary"]["top_k_changed"] is False
    assert contract["scoring"]["top_k"] == 68
    assert contract["gates"]["exact_total_rows"] == 20_942


def test_contract_rejects_old_score_reuse() -> None:
    contract = load_native_rescore_v2_contract(ROOT)
    changed = copy.deepcopy(contract)
    changed["scientific_boundary"]["old_native_scores_read"] = True
    with pytest.raises(ContractError, match="scientific boundary"):
        validate_native_rescore_v2_contract(_reseal(changed), ROOT)


def test_calibration_loader_is_outcome_blind_and_replays_hashes(tmp_path: Path) -> None:
    ledger = tmp_path / "cohort.jsonl"
    rows = []
    for detector in ("H1", "L1"):
        rows.append(
            {
                "detector": detector,
                "gps_start": 100.0 if detector == "H1" else 200.0,
                "row_number": 0,
                "calibration_index": 0 if detector == "H1" else 1,
                "bootstrap_block_index": 0,
                "expected_image_sha256": ("a" if detector == "H1" else "b") * 64,
                "identity_digest": ("c" if detector == "H1" else "d") * 64,
                "context_sources": [
                    {
                        "source_relative_path": f"{detector}.hdf5",
                        "source_sha256": "e" * 64,
                        "block_interval": [0.0, 300.0],
                        "used_interval": [96.0, 136.0]
                        if detector == "H1"
                        else [196.0, 236.0],
                    }
                ],
            }
        )
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    contract = {"gates": {"calibration_rows_by_detector": {"H1": 1, "L1": 1}}}
    loaded = calibration_v2_rows(ledger, contract=contract)
    assert len(loaded) == 2
    assert all(len(row["expected_image_sha256"]) == 64 for row in loaded)
    assert all(len(row["frozen_context_sources_digest"]) == 64 for row in loaded)
    rows[0]["native_score"] = 0.5
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    with pytest.raises(ContractError, match="contains outcomes"):
        calibration_v2_rows(ledger, contract=contract)


def test_input_validator_rejects_cross_population_overlap() -> None:
    contract = {
        "gates": {
            "calibration_rows_by_detector": {"H1": 1, "L1": 0},
            "candidate_rows_by_detector": {"H1": 1, "L1": 0},
        }
    }
    rows = [
        {"input_index": 0, "population": "native_calibration", "detector": "H1", "gps_start": 1.0},
        {"input_index": 1, "population": "primary_candidate", "detector": "H1", "gps_start": 1.0},
    ]
    with pytest.raises(ContractError, match="identity is invalid"):
        validate_v2_input_rows(rows, contract=contract)


def test_run_key_depends_on_new_calibration_artifact() -> None:
    contract = {"contract_digest": "a" * 64}
    common = {
        "index_summary": {"artifact_digest": "i" * 64},
        "scan_summary": {"artifact_digest": "s" * 64},
        "runtime": {"runtime_environment": {"environment_digest": "r" * 64}},
    }
    first = _run_key(
        contract, calibration_summary={"artifact_digest": "c" * 64}, **common
    )
    second = _run_key(
        contract, calibration_summary={"artifact_digest": "d" * 64}, **common
    )
    assert first != second
