from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "config/dante_light_v8_1_design_proposal.json"


def _proposal() -> dict:
    return json.loads(PROPOSAL.read_text(encoding="utf-8"))


def test_v8_1_design_authorizes_only_phase0_and_remains_non_destructive() -> None:
    proposal = _proposal()
    priority = proposal["prioritization_workstream"]

    assert proposal["status"] == "PHASE0_AUTHORIZED_GATES_NOT_FROZEN"
    assert (
        proposal["decision_record"]["confirmed_primary_placement"]
        == "post_exact_human_review_priority"
    )
    assert priority["status"] == "PROPOSED_NOT_AUTHORIZED_FOR_IMPLEMENTATION"
    assert "no_window_discard" in priority["mandatory_safety_properties"]
    assert (
        "exact_path_eventual_service_for_every_valid_window"
        in priority["mandatory_safety_properties"]
    )
    assert priority["aggregate_metrics"]["spearman"] == "DESCRIPTIVE_ONLY_NOT_A_GATE"


def test_v8_1_priority_gate_cannot_hide_protected_cells_or_invent_budget() -> None:
    gate = _proposal()["prioritization_workstream"]["primary_gate_family"]

    assert gate["required_cells"] == "DETECTOR_X_MORPHOLOGY_NO_POOLING"
    assert gate["confidence_method"] == "DETECTOR_GPS_BLOCK_BOOTSTRAP"
    assert gate["budget_or_deadline"].startswith("UNRESOLVED_")
    assert gate["success_bound"].startswith("UNRESOLVED_")
    assert gate["minimum_effective_blocks"].startswith("UNRESOLVED_")


def test_v8_1_exact_optimization_requires_equivalence_before_speed() -> None:
    exact = _proposal()["exact_path_workstream"]

    assert exact["reference_engine"] == "canonical"
    assert exact["acceptance_order"][-1] == "performance"
    assert exact["equivalence"]["decision_mismatches_allowed"] == 0
    assert exact["equivalence"]["tolerance_may_not_be_relaxed_after_results"] is True
    assert (
        exact["equivalence"]["cross_engine_existing_score_tolerance_reference"]
        == "src/dante_light/evidence.py::SCORE_ATOL"
    )
    assert exact["source_of_truth_issue"]["current_literal"] == "k=68"
    assert "representation.top_k" in exact["source_of_truth_issue"]["required_resolution"]


def test_v8_1_design_references_exist_and_no_new_holdout_is_opened() -> None:
    proposal = _proposal()
    allowed = proposal["access_boundary"]["allowed_evidence"]
    forbidden = proposal["access_boundary"]["forbidden_until_separate_freeze"]

    assert "already_open_o4b_shadow_v2_as_retrospective_engineering_regression" in allowed
    assert "new_protected_confirmation_outcomes" in forbidden
    assert (ROOT / "docs/DANTE_LIGHT_V8_1_DESIGN_PROPOSAL_2026-08-27.md").is_file()
    assert (ROOT / "docs/DANTE_LIGHT_V8_1_IMPLEMENTATION_PLAN_2026-08-27.md").is_file()
    assert (ROOT / "config/dante_light_prefilter_v7_teacher_stability.json").is_file()
    assert (ROOT / "artifacts/dante_light/prospective_validation_v1.json").is_file()
