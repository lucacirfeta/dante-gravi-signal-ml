from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_initial_calibration import (
    build_initial_calibration_plan,
    iter_planned_identities,
    load_initial_calibration_plan,
    load_selector_contract,
    validate_initial_calibration_plan,
)
from src.dante_light.o3a_population_geometry import (
    iter_role_identities,
    load_identity_universes,
)


ROOT = Path(__file__).resolve().parents[1]


def test_selector_freezes_approved_outcome_blind_semantics() -> None:
    value = load_selector_contract(root=ROOT)
    assert value["selection"]["candidate_block_length_rows"] == 17
    assert value["selection"]["chronological_stratum_count"] == 295
    assert value["selection"]["planned_rows_per_detector"] == 5_000
    assert value["selection"]["bootstrap_rows"] == 4_998
    assert value["selection"]["point_only_tail_rows"] == 2
    assert value["raw_acceptance"]["excess_power_veto_applied"] is False
    assert value["raw_acceptance"]["score_value_or_class_may_affect_acceptance"] is False
    assert value["execution_boundary"]["strain_access_allowed"] is False


def test_plan_has_exact_detector_cardinality_and_block_shape() -> None:
    value = load_initial_calibration_plan(root=ROOT)
    assert {
        detector: plan["candidate_block_count"]
        for detector, plan in value["detector_plans"].items()
    } == {"H1": 10_044, "L1": 10_731}
    assert {
        detector: plan["discarded_segment_tail_window_count"]
        for detector, plan in value["detector_plans"].items()
    } == {"H1": 4_219, "L1": 4_064}
    for detector in ("H1", "L1"):
        detector_plan = value["detector_plans"][detector]
        assert detector_plan["selected_candidate_blocks"] == 295
        assert detector_plan["planned_rows"] == 5_000
        assert detector_plan["bootstrap_rows"] == 4_998
        assert detector_plan["point_only_tail_rows"] == 2
        output_counts = [
            block["output_row_count"]
            for block in detector_plan["selected_blocks"]
        ]
        assert output_counts == [17] * 294 + [2]
        assert all(
            block["candidate_block_row_count"] == 17
            for block in detector_plan["selected_blocks"]
        )


def test_planned_identities_are_unique_aligned_and_inside_universe() -> None:
    plan = load_initial_calibration_plan(root=ROOT)
    universe = load_identity_universes(root=ROOT)
    available = set(
        iter_role_identities(universe, "initial_calibration_proposal_universe")
    )
    rows = list(iter_planned_identities(plan))
    assert len(rows) == 10_000
    assert len(set(rows)) == 10_000
    assert set(rows) <= available
    assert all(gps % 64 == 0 for _detector, gps in rows)


def test_strata_are_complete_balanced_and_hash_selected() -> None:
    plan = load_initial_calibration_plan(root=ROOT)
    for detector in ("H1", "L1"):
        detector_plan = plan["detector_plans"][detector]
        assert detector_plan["minimum_stratum_candidate_count"] > 0
        assert (
            detector_plan["maximum_stratum_candidate_count"]
            - detector_plan["minimum_stratum_candidate_count"]
            <= 1
        )
        assert [
            block["stratum_index"]
            for block in detector_plan["selected_blocks"]
        ] == list(range(295))
        assert all(
            block["candidate_rank_in_stratum"] == 0
            for block in detector_plan["selected_blocks"]
        )


def test_plan_rejects_selected_block_drift() -> None:
    value = build_initial_calibration_plan(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["detector_plans"]["H1"]["selected_blocks"][0][
        "first_gps_start"
    ] += 64
    with pytest.raises(ContractError, match="plan mismatch"):
        validate_initial_calibration_plan(mutated, root=ROOT)
