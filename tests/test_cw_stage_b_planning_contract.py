"""Partial planning contract checks only; no scientific execution or data access."""

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/dante_cw_stage_b_planning_v1.json"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_scope_is_not_an_executable_scientific_contract(contract):
    assert contract["scope"] == "APPROVED_PARTIAL_PLANNING_ONLY_NOT_EXECUTABLE"
    assert contract["scientific_execution_ready"] is False
    assert not any(contract["execution"].values())


def test_approved_reporting_scope_does_not_select_inputs(contract):
    population = contract["reporting_population"]
    assert population["detector"] == "L1"
    assert population["cw_policy"] == "annotate_not_global_veto"
    for field in (
        "exact_epoch_gps",
        "dq_selection",
        "reference_calibration_exclusions",
        "window_grid_and_complete_context",
    ):
        assert population[field] is None


def test_two_epoch_equivalence_error_control(contract):
    error = contract["error_control"]
    assert error["family_alpha"] == 0.05
    assert error["primary_epoch_count"] == len(contract["primary"]["epochs"]) == 2
    assert error["epoch_alpha"] == pytest.approx(
        error["family_alpha"] / error["primary_epoch_count"]
    )
    assert error["paired_interval_coverage"] == pytest.approx(
        1 - 2 * error["epoch_alpha"]
    )
    assert error["simultaneous_95_percent_coverage_claim_allowed"] is False
    assert error["interval_algorithm"] is None


def test_joint_power_is_a_target_not_an_observation(contract):
    power = contract["power"]
    assert power["target_per_epoch"] == 0.95
    assert power["minimum_joint_target_union_bound"] == pytest.approx(
        1
        - contract["error_control"]["primary_epoch_count"]
        * (1 - power["target_per_epoch"])
    )
    assert power["empirical_qualification"] is None
    assert power["independent_pair_scenarios_are_observed_power"] is False


def test_pilot_share_is_approved_but_unallocated(contract):
    pilot = contract["pilot"]
    assert pilot["target_fraction_of_eligible_cw_off_duration_per_epoch"] == 0.2
    assert pilot["metadata_stratified_temporally_disjoint"] is True
    assert pilot["exact_allocation"] is None
    assert pilot["context_guards"] is None
    assert pilot["confirmatory_recycling_allowed"] is False


def test_primary_and_secondary_numeric_margins_remain_unset(contract):
    margin = contract["margin"]
    for field in (
        "planning_reporting_rate",
        "reporting_uncertainty_method",
        "planning_reporting_sigma",
        "delta",
        "scientific_bias_cap",
    ):
        assert margin[field] is None
    assert margin["confirmatory_outcome_margin_retuning_allowed"] is False
    assert contract["secondary"]["limit"] is None
    assert contract["secondary"]["limit_rule"] == (
        "planning_reporting_rate_times_delta_minus_one"
    )
    assert contract["secondary"]["additional_primary_equivalence_claim"] is False
    assert (
        contract["secondary"]["observational_placebo_can_define_paired_margin"] is False
    )


def test_no_silent_bootstrap_or_zero_event_assumptions(contract):
    uncertainty = contract["uncertainty"]
    assert uncertainty["bootstrap_if_used"] == "block_based_paired_only"
    assert uncertainty["block_scheme"] is None
    assert uncertainty["rare_zero_event_coverage_qualification"] is None
    assert uncertainty["minimum_tail_support"] is None
    assert uncertainty["zero_flag_handling"] is None
    assert uncertainty["zero_observed_discordance_implies_zero_variance"] is False


def test_physical_anchoring_precedes_score(contract):
    step = contract["step_zero"]
    for field in (
        "realized_amplitude_history",
        "primary_physical_waveform",
        "spectral_agreement_tolerance",
        "independent_real_cw_on_anchor",
        "public_o4_psd_dose_screen_source",
    ):
        assert step[field] is None
    assert step["before_any_stage_b_score"] is True
    assert step["silent_nominal_extrapolation_allowed"] is False


def test_old_point_p99_is_not_an_adopted_flag_or_threshold(contract):
    parent = contract["inherited_point_p99_comparison_only"]
    raw = (ROOT / parent["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == parent["sha256"]
    assert parent["new_stage_b_flag_rule_adopted"] is False
    assert contract["primary"]["flag_rule"] is None
    assert contract["primary"]["fresh_16k_threshold_calibration"] is None
    assert contract["primary"]["historical_numeric_threshold_reuse_allowed"] is False
