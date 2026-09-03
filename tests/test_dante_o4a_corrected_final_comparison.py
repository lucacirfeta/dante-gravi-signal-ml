from __future__ import annotations

import json

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_corrected_final_comparison import (
    ROOT,
    _validate_historical_score_consistency,
    compare_candidate_catalogues,
    compare_coincidence_sets,
    compare_pem_sets,
    load_final_comparison_contract,
    recheck_historical_singletons,
    validate_final_comparison_contract,
)


def _old(detector: str, gps: float, score: float, klass: str) -> dict:
    return {
        "detector": detector,
        "gps_start": gps,
        "native_score_idxq4_64_queryq4_64": score,
        "robustness_class_idxq4_64_queryq4_64": klass,
    }


def _new(detector: str, gps: float, score: float, klass: str) -> dict:
    return {
        "detector": detector,
        "gps_start": gps,
        "native_score": score,
        "native_class": klass,
    }


def _tax(detector: str, gps: float, family: str) -> dict:
    return {"detector": detector, "gps_start": gps, "global_family_id": family}


def test_frozen_final_comparison_contract_validates() -> None:
    contract = load_final_comparison_contract(ROOT)
    assert contract["taxonomy_comparison"]["metric"] == "adjusted_rand_score"
    assert contract["coincidence_comparison"]["statistic_delta_per_event"] is False
    assert contract["scientific_boundary"]["no_cross_null_statistic_comparison"] is True


def test_contract_rejects_global_significance_claim() -> None:
    path = ROOT / "config/dante_o4a_corrected_final_comparison_v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract["scientific_boundary"]["no_global_significance_claim"] = False
    with pytest.raises(ContractError, match="digest mismatch"):
        validate_final_comparison_contract(contract, root=ROOT)


def test_candidate_comparison_is_exact_identity_and_permutation_invariant() -> None:
    old = [
        _old("H1", 1.0, 0.2, "BACKGROUND"),
        _old("L1", 2.0, 0.4, "ROBUST"),
        _old("H1", 3.0, 0.3, "AMBIGUOUS"),
    ]
    new = [
        _new("H1", 1.0, 0.3, "AMBIGUOUS"),
        _new("L1", 2.0, 0.5, "ROBUST"),
        _new("L1", 4.0, 0.6, "ROBUST"),
    ]
    old_tax = [
        _tax("H1", 1.0, "Family_A"),
        _tax("L1", 2.0, "Family_B"),
        _tax("H1", 3.0, "Family_B"),
    ]
    new_tax = [
        _tax("H1", 1.0, "renamed_7"),
        _tax("L1", 2.0, "renamed_9"),
        _tax("L1", 4.0, "renamed_9"),
    ]
    metrics, shared, removed, added = compare_candidate_catalogues(
        old, new, old_tax, new_tax
    )
    assert metrics["shared_total"] == 2
    assert metrics["historical_only_total"] == 1
    assert metrics["corrected_only_total"] == 1
    assert metrics["class_changed_total"] == 1
    assert metrics["taxonomy"]["adjusted_rand_index"] == pytest.approx(1.0)
    assert len(shared) == 2
    assert removed == [{"detector": "H1", "gps_start": 3.0}]
    assert added == [{"detector": "L1", "gps_start": 4.0}]


def test_candidate_comparison_rejects_duplicate_identity() -> None:
    old = [_old("H1", 1.0, 0.2, "BACKGROUND")] * 2
    new = [_new("H1", 1.0, 0.3, "AMBIGUOUS")]
    old_tax = [_tax("H1", 1.0, "A")]
    new_tax = [_tax("H1", 1.0, "B")]
    with pytest.raises(ContractError, match="duplicate"):
        compare_candidate_catalogues(old, new, old_tax, new_tax)


def test_historical_taxonomy_and_dsd_payload_must_match() -> None:
    taxonomy = [
        {
            **_old("H1", 1.0, 0.2, "BACKGROUND"),
            "global_family_id": "Family_01",
        }
    ]
    scores = [
        {
            "detector": "H1",
            "gps_start": 1.0,
            "score": 0.2,
            "class": "BACKGROUND",
        }
    ]
    _validate_historical_score_consistency(taxonomy, scores)
    scores[0]["class"] = "ROBUST"
    with pytest.raises(ContractError, match="payload differs"):
        _validate_historical_score_consistency(taxonomy, scores)


def test_coincidence_comparison_does_not_compare_statistics() -> None:
    historical = {
        "summary": {"n_catalogue": 2, "cc_null_max_p99": 0.4},
        "events": [
            {"detector": "H1", "gps": 1.0, "cc_onsource": 0.5},
            {"detector": "L1", "gps": 2.0, "cc_onsource": 0.2},
        ],
    }
    corrected = [
        {
            "detector": "H1",
            "gps_start": 1.0,
            "measurement_status": "MEASURED",
            "exceeds_primary_threshold": False,
        },
        {
            "detector": "L1",
            "gps_start": 3.0,
            "measurement_status": "PARTNER_DATA_UNAVAILABLE",
            "exceeds_primary_threshold": False,
        },
    ]
    result = compare_coincidence_sets(historical, corrected)
    assert result["measured_identity_overlap"] == 1
    assert result["threshold_exceeder_identity_overlap"] == 0
    assert result["threshold_equivalence_claim"] is False


def test_disjoint_pem_populations_fail_closed() -> None:
    result = compare_pem_sets(
        [{"detector": "H1", "gps_start": 1.0}],
        [{"detector": "H1", "gps_start": 1.0}],
        [{"detector": "L1", "gps_start": 2.0}],
    )
    assert result["detector_gps_overlap"] == 0
    assert result["outcome_comparison_performed"] is False
    assert result["disposition"] == "NOT_COMPARABLE_DISJOINT_TARGET_POPULATIONS"


def test_singleton_alias_is_explicit_and_not_general_candidate_pairing() -> None:
    cases = [
        {
            "name": "forum",
            "historical_identity": {"detector": "L1", "gps_start": 10.0},
            "corrected_identity_aliases": [
                {"detector": "L1", "gps_start": 14.0, "role": "frozen_analysis_window"}
            ],
            "localized_feature_gps": 35.17,
        }
    ]
    old = [_old("L1", 10.0, 0.4, "ROBUST")]
    new = [_new("L1", 14.0, 0.6, "ROBUST")]
    old_tax = [_tax("L1", 10.0, "Singleton_10")]
    new_tax = [_tax("L1", 14.0, "Family_01")]
    coincidence = [
        {
            "detector": "L1",
            "gps_start": 14.0,
            "measurement_status": "MEASURED",
            "exceeds_primary_threshold": False,
            "population": "primary",
        }
    ]
    pem = [
        {
            "target": {
                "detector": "L1",
                "gps_start": 14.0,
                "population": "primary",
            },
            "verdict_tier": "NO_CORRELATION",
        }
    ]
    result = recheck_historical_singletons(
        cases, old, new, old_tax, new_tax, coincidence, pem
    )
    assert result[0]["corrected_exact_identity_present"] is False
    assert (
        result[0]["corrected_matches"][0]["match_role"]
        == "frozen_analysis_window_alias"
    )
    assert result[0]["corrected_matches"][0]["native_class"] == "ROBUST"
    assert result[0]["corrected_matches"][0]["pem"] == {
        "population": "primary",
        "verdict_tier": "NO_CORRELATION",
    }
