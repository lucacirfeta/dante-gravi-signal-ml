from __future__ import annotations

from src.dante_light.o4a_final_impact_attribution import (
    ROOT,
    build_attribution,
    load_contract,
)


def test_frozen_posthoc_attribution_contract_validates() -> None:
    contract = load_contract(ROOT)
    assert contract["status"] == "FROZEN_POSTHOC_AFTER_EXPLORATORY_PREFLIGHT"
    assert contract["scientific_boundary"]["outcome_blind"] is False
    assert contract["scientific_boundary"][
        "nonedge_churn_may_not_be_called_threshold_only"
    ] is True


def test_attribution_replays_exact_final_populations_and_boundaries() -> None:
    result = build_attribution(root=ROOT)
    assert result["status"] == "PASS_POSTHOC_FINAL_IMPACT_ATTRIBUTION_V1"
    assert result["controlled_direct_padding_effect"]["class_changed"] == 120
    assert result["final_shared_class_churn"]["class_changed_total"] == 1626
    assert result["final_shared_class_churn"]["edge_class_changed"] == 39
    assert result["final_shared_class_churn"]["nonedge_class_changed"] == 1587
    assert result["final_shared_class_churn"]["causal_decomposition"] == (
        "NOT_IDENTIFIABLE_FROM_FINAL_COMPARISON"
    )
    assert result["corrected_only_followup"]["primary_pem_from_corrected_only"] == 2
    assert result["corrected_only_followup"]["primary_new_candidates_at_right_edge"] == 0
    assert result["forum_candidate"]["corrected_class"] == "ROBUST"
    assert result["forum_candidate"]["included_in_pem_shortlist"] is False
