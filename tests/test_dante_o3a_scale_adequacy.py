from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_scale_adequacy import (
    build_scale_adequacy_audit,
    load_scale_adequacy_audit,
    load_stage_contract,
    validate_scale_adequacy_audit,
    validate_stage_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_scale_audit_passes_without_strain_or_outcomes() -> None:
    value = load_scale_adequacy_audit(root=ROOT)
    assert value["status"] == "PASS_METHOD_PARITY_SCALE_ADEQUATE"
    assert value["strain_data_accessed"] is False
    assert value["outcome_data_accessed"] is False
    assert all(
        row["capacity_gates_pass"] for row in value["detectors"].values()
    )


def test_scale_audit_preserves_nominal_p99_and_index_design() -> None:
    parity = load_scale_adequacy_audit(root=ROOT)[
        "nominal_statistical_and_representation_parity"
    ]
    assert parity["nominal_expected_upper_tail_observations"] == 50
    assert parity["complete_non_overlapping_blocks"] == 294
    assert parity["rows_excluded_from_complete_block_resampling"] == 2
    assert parity["exact_patch_token_total"] == 1_771_486
    assert parity["matches_corrected_o4a_design"] is True


def test_o3a_sampling_is_not_capacity_limited() -> None:
    value = load_scale_adequacy_audit(root=ROOT)
    for row in value["detectors"].values():
        assert row["calibration_capacity_multiple"] > 30
        assert row["index_capacity_multiple"] > 100
        assert row["o3a_to_o4a_eligible_ratio"] > 0.85


def test_scale_audit_rejects_changed_capacity() -> None:
    value = build_scale_adequacy_audit(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["detectors"]["H1"]["eligible_calibration_starts"] -= 1
    with pytest.raises(ContractError, match="audit mismatch"):
        validate_scale_adequacy_audit(mutated, root=ROOT)


def test_approved_stage_contract_exactly_freezes_recommendations() -> None:
    value = load_stage_contract(root=ROOT)
    assert value["status"] == "AUTHOR_APPROVED_METHOD_PARITY_STAGE_CONTRACT"
    assert value["methodological_parity"][
        "post_hoc_o3a_hyperparameter_tuning_allowed"
    ] is False
    assert value["execution_boundary"][
        "outcome_blind_identity_manifest_preparation_allowed"
    ] is True
    assert value["execution_boundary"]["strain_access_allowed"] is False
    assert value["execution_boundary"]["full_scan_allowed"] is False


def test_stage_contract_rejects_execution_promotion() -> None:
    value = load_stage_contract(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["execution_boundary"]["strain_access_allowed"] = True
    with pytest.raises(ContractError, match="contract mismatch"):
        validate_stage_contract(mutated, root=ROOT)
