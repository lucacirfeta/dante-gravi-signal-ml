from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_classification import (
    CLASS_LABELS,
    classify_candidate_rows,
    classify_native_score,
    load_native_classification_contract,
    validate_native_classification_contract,
)
from src.dante_light.o4a_corrected_native_rescore import _float32_hex


ROOT = Path(__file__).resolve().parents[1]


def _redigest(contract: dict) -> dict:
    updated = json.loads(json.dumps(contract))
    updated.pop("contract_digest", None)
    updated["contract_digest"] = canonical_json_sha256(updated)
    return updated


def _row(index: int, detector: str, gps: float, score: float) -> dict:
    return {
        "input_index": index,
        "population": "primary_candidate",
        "detector": detector,
        "gps_start": gps,
        "identity_digest": f"identity-{index}",
        "image_sha256": "1" * 64,
        "raw_context_sha256": "2" * 64,
        "clean_window_sha256": "3" * 64,
        "context_sources": [],
        "context_sources_digest": canonical_json_sha256([]),
        "native_score": score,
        "score_float32_hex": _float32_hex(score),
    }


def test_native_classification_contract_is_frozen() -> None:
    contract = load_native_classification_contract(ROOT)
    assert contract["classification"]["rule"] == (
        "BACKGROUND if score < ci_lower; ROBUST if score > ci_upper; "
        "AMBIGUOUS otherwise"
    )
    assert contract["gates"]["exact_rows_by_detector"] == {
        "H1": 4720,
        "L1": 6222,
    }


def test_native_classification_contract_rejects_rule_drift() -> None:
    contract = load_native_classification_contract(ROOT)
    changed = json.loads(json.dumps(contract))
    changed["classification"]["upper_boundary_class"] = "ROBUST"
    with pytest.raises(ContractError, match="rule changed"):
        validate_native_classification_contract(_redigest(changed), ROOT)


def test_classify_native_score_preserves_open_extreme_boundaries() -> None:
    assert classify_native_score(0.09, lower=0.1, upper=0.2) == "BACKGROUND"
    assert classify_native_score(0.1, lower=0.1, upper=0.2) == "AMBIGUOUS"
    assert classify_native_score(0.2, lower=0.1, upper=0.2) == "AMBIGUOUS"
    assert classify_native_score(0.21, lower=0.1, upper=0.2) == "ROBUST"


def test_classify_candidate_rows_is_detector_specific() -> None:
    rows = [
        _row(0, "H1", 1.0, 0.16),
        _row(1, "L1", 2.0, 0.16),
    ]
    classified, counts = classify_candidate_rows(
        rows,
        thresholds={
            "H1": {"ci_lower": 0.15, "p99": 0.2, "ci_upper": 0.3},
            "L1": {"ci_lower": 0.17, "p99": 0.22, "ci_upper": 0.4},
        },
        expected_counts={"H1": 1, "L1": 1},
        expected_first_input_index=0,
    )
    assert [row["native_class"] for row in classified] == [
        "AMBIGUOUS",
        "BACKGROUND",
    ]
    assert set(counts["H1"]) == set(CLASS_LABELS)
    assert counts["H1"]["AMBIGUOUS"] == 1
    assert counts["L1"]["BACKGROUND"] == 1


def test_classify_candidate_rows_rejects_prior_outcomes() -> None:
    row = _row(0, "H1", 1.0, 0.16)
    row["class"] = "ROBUST"
    with pytest.raises(ContractError, match="input row changed"):
        classify_candidate_rows(
            [row],
            thresholds={"H1": {"ci_lower": 0.15, "p99": 0.2, "ci_upper": 0.3}},
            expected_counts={"H1": 1},
            expected_first_input_index=0,
        )
