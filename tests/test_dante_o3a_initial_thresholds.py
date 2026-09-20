from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_initial_thresholds import (
    compute_detector_threshold,
    load_threshold_contract,
    validate_score_rows,
    validate_threshold_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _row(detector: str, index: int, *, total: int) -> dict[str, object]:
    score = float(np.float32(0.25 + index / 10_000))
    return {
        "detector": detector,
        "analysis_gps_start": 1_000_000 + 64 * index,
        "primary_score": score,
        "primary_score_float32_hex": np.float32(score).tobytes().hex(),
        "bootstrap_eligible": index < total - 2,
        "point_only_tail": index >= total - 2,
    }


def test_frozen_contract_is_detector_specific_and_scan_closed() -> None:
    value = load_threshold_contract(root=ROOT)
    assert value["method"]["detector_specific"] is True
    assert value["method"]["block_length"] == 17
    assert value["method"]["bootstrap_replicates"] == 1_000_000
    assert value["population"]["point_rows_per_detector"] == 5000
    assert value["adequacy_gate"][
        "post_hoc_o3a_specific_width_cutoff_allowed"
    ] is False
    assert value["scientific_boundary"]["primary_scan_started"] is False
    assert value["scientific_boundary"]["classification_performed"] is False


def test_contract_rejects_pooling_or_precision_gate_drift() -> None:
    value = load_threshold_contract(root=ROOT)
    for path, replacement in (
        (("method", "detector_specific"), False),
        (("adequacy_gate", "nondegenerate_intervals"), False),
    ):
        mutated = copy.deepcopy(value)
        mutated[path[0]][path[1]] = replacement
        body = {
            key: item for key, item in mutated.items() if key != "contract_digest"
        }
        mutated["contract_digest"] = canonical_json_sha256(body)
        with pytest.raises(ContractError):
            validate_threshold_contract(mutated, root=ROOT)


def test_score_rows_require_exact_detector_split_and_point_only_tail() -> None:
    contract = {
        "population": {
            "detectors": ["H1", "L1"],
            "point_rows_per_detector": 36,
            "bootstrap_rows_per_detector": 34,
        }
    }
    rows = [
        _row(detector, index, total=36)
        for detector in ("H1", "L1")
        for index in range(36)
    ]
    values = validate_score_rows(rows, contract=contract)
    assert values["H1"].shape == (36,)
    assert values["L1"].shape == (36,)
    mutated = copy.deepcopy(rows)
    mutated[33]["point_only_tail"] = True
    with pytest.raises(ContractError, match="score row changed"):
        validate_score_rows(mutated, contract=contract)


def test_threshold_reports_finite_nondegenerate_width() -> None:
    rng = np.random.default_rng(7)
    scores = rng.normal(0.3, 0.03, size=170)
    value = compute_detector_threshold(
        scores,
        method={
            "bootstrap_replicates": 200,
            "bootstrap_seed": 42,
            "bootstrap_chunk_size": 50,
            "block_length": 17,
        },
    )
    assert value["ci_lower"] <= value["p99"] <= value["ci_upper"]
    assert value["ci_width"] > 0
    assert value["ci_width_fraction_of_p99"] > 0

