from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_thresholds import (
    ROOT,
    compute_detector_threshold,
    load_native_threshold_contract,
    validate_calibration_score_rows,
    validate_native_threshold_contract,
)


def _reseal(value: dict) -> dict:
    updated = copy.deepcopy(value)
    updated.pop("contract_digest", None)
    updated["contract_digest"] = canonical_json_sha256(updated)
    return updated


def _rows(detector: str, count: int, block_length: int) -> list[dict]:
    rows = []
    for index in range(count):
        score = float(np.float32(index / max(1, count)))
        rows.append(
            {
                "detector": detector,
                "gps_start": 1_000_000_000.0 + 64.0 * index,
                "population": "native_calibration",
                "ledger_row_number": index,
                "bootstrap_block_index": index // block_length,
                "identity_digest": f"{index:064x}",
                "native_score": score,
                "score_float32_hex": np.float32(score).tobytes().hex(),
            }
        )
    return rows


def test_native_threshold_contract_matches_frozen_future_method() -> None:
    contract = load_native_threshold_contract(ROOT)
    method = contract["method"]
    assert method == {
        "name": "non_overlapping_block_bootstrap_p99",
        "detector_specific": True,
        "point_percentile_uses_all_rows": True,
        "bootstrap_uses_first_complete_blocks": True,
        "block_length": 17,
        "bootstrap_replicates": 1_000_000,
        "bootstrap_seed": 42,
        "bootstrap_chunk_size": 500,
        "percentile": 99,
        "confidence_percentiles": [2.5, 97.5],
    }
    assert contract["gates"]["exact_rows_by_detector"] == {
        "H1": 5000,
        "L1": 5000,
    }


def test_native_threshold_contract_rejects_method_drift() -> None:
    contract = load_native_threshold_contract(ROOT)
    changed = copy.deepcopy(contract)
    changed["method"]["percentile"] = 98
    with pytest.raises(ContractError, match="method changed"):
        validate_native_threshold_contract(_reseal(changed), ROOT)


def test_calibration_score_rows_preserve_detector_order_and_blocks() -> None:
    rows = _rows("H1", 34, 17)
    scores, audit = validate_calibration_score_rows(
        rows, detector="H1", expected_count=34, block_length=17
    )
    assert len(scores) == 34
    assert audit["row_total"] == 34
    assert len(audit["identity_score_digest"]) == 64
    assert len(audit["score_vector_float64_sha256"]) == 64

    changed = copy.deepcopy(rows)
    changed[17]["bootstrap_block_index"] = 0
    with pytest.raises(ContractError, match="row changed"):
        validate_calibration_score_rows(
            changed, detector="H1", expected_count=34, block_length=17
        )


def test_threshold_computation_is_detector_local_and_deterministic() -> None:
    method = {
        **load_native_threshold_contract(ROOT)["method"],
        "block_length": 4,
        "bootstrap_replicates": 200,
        "bootstrap_chunk_size": 7,
        "bootstrap_seed": 7,
    }
    scores = np.linspace(0.0, 1.0, 125, dtype=np.float64)
    first = compute_detector_threshold(scores, method=method)
    second = compute_detector_threshold(scores, method=method)
    assert first == second
    assert first["p99"] == pytest.approx(np.percentile(scores, 99))
    assert first["block_length"] == 4
    assert first["n_complete_blocks"] == 31
    assert first["ci_lower"] <= first["p99"] <= first["ci_upper"]


def test_threshold_stage_does_not_open_candidate_or_historical_scores() -> None:
    source = (
        Path(ROOT) / "src/dante_light/o4a_corrected_native_thresholds.py"
    ).read_text(encoding="utf-8")
    assert "native_candidates.jsonl" not in source
    assert "corrected_native_rescore.json" not in source
    assert '"old_native_thresholds_read"' not in source
