from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import ROOT
from src.pipeline_v3_multiscale.efficiency_v2_analysis import (
    ALL_CONDITIONAL,
    ALL_PRIMARY,
    NO_CONDITIONAL,
    NO_ELIGIBLE,
    NO_PRIMARY,
    PASS_CI,
    UNDEFINED_REPLICATES,
    _conditional_statistic,
    _primary_statistic,
    load_analysis_contract,
    validate_analysis_contract,
)


def _rehash(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def test_analysis_contract_accepts_checked_in_protocol() -> None:
    contract = load_analysis_contract(ROOT)
    assert contract["uncertainty"]["unit"] == "raw_source_block"
    assert contract["uncertainty"]["resamples"] == 2000
    assert contract["uncertainty"]["shared_draws_across_morphology_snr_scale"]
    assert contract["boundary_policy"][
        "endpoint_values_are_not_true_probability_claims"
    ]


def test_checked_in_analysis_evidence_is_self_consistent() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/multiscale_efficiency_v2"
        / "analysis_summary.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert evidence["status"] == "PASS_VERIFIED_MULTISCALE_EFFICIENCY_V2_ANALYSIS"
    assert evidence["primary_efficiency"]["row_total"] == 96
    assert evidence["primary_efficiency"]["zero_recovery_cells"] == 27
    assert evidence["conditional_response"]["defined_cells"] == 276
    assert evidence["conditional_response"]["observed_zero_cells"] == 140
    assert evidence["conditional_response"]["observed_one_cells"] == 110
    assert evidence["conditional_response"]["interior_cells"] == 26
    assert evidence["conditional_response"][
        "endpoint_fraction_of_defined"
    ] == pytest.approx(250 / 276)
    assert evidence["scientific_boundary"]["scale_or_fusion_applied"] is False
    assert evidence["scientific_boundary"]["rate_upper_limit_computed"] is False
    assert evidence["scientific_boundary"]["wall_of_lines_mechanism_proven"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["uncertainty"].update(unit="trial"),
            "block-bootstrap",
        ),
        (
            lambda value: value["uncertainty"].update(detectors_pooled=True),
            "block-bootstrap",
        ),
        (
            lambda value: value["boundary_policy"]["zero_conditional_responses"].update(
                confidence_interval=[0.0, 0.0]
            ),
            "boundary policy",
        ),
        (
            lambda value: value["required_interpretation"].update(
                scale_fusion_allowed=True
            ),
            "interpretation boundary",
        ),
    ],
)
def test_analysis_contract_rejects_scientific_drift(mutation, message: str) -> None:
    contract = load_analysis_contract(ROOT)
    mutation(contract)
    with pytest.raises(ContractError, match=message):
        validate_analysis_contract(_rehash(contract), root=ROOT)


def _draws(seed: int = 3) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 4, size=(2000, 4))


def test_primary_endpoints_have_observed_point_and_null_interval() -> None:
    zero = _primary_statistic(np.asarray([False] * 4), _draws(), confidence=0.95)
    assert zero["point"] == 0.0
    assert zero["confidence_interval_95"] is None
    assert zero["status"] == NO_PRIMARY

    one = _primary_statistic(np.asarray([True] * 4), _draws(), confidence=0.95)
    assert one["point"] == 1.0
    assert one["confidence_interval_95"] is None
    assert one["status"] == ALL_PRIMARY


def test_primary_interior_cell_has_block_bootstrap_interval() -> None:
    result = _primary_statistic(
        np.asarray([False, True, False, True]), _draws(), confidence=0.95
    )
    assert result["point"] == 0.5
    assert result["confidence_interval_95"] is not None
    assert result["status"] == PASS_CI
    assert result["bootstrap_defined_replicates"] == 2000


def test_conditional_zero_denominator_is_undefined() -> None:
    result = _conditional_statistic(
        np.asarray([False] * 4),
        np.asarray([False] * 4),
        _draws(),
        confidence=0.95,
    )
    assert result["point"] is None
    assert result["confidence_interval_95"] is None
    assert result["status"] == NO_ELIGIBLE


@pytest.mark.parametrize(
    ("response", "point", "status"),
    [([False] * 4, 0.0, NO_CONDITIONAL), ([True] * 4, 1.0, ALL_CONDITIONAL)],
)
def test_conditional_observed_endpoints_have_null_interval(
    response, point: float, status: str
) -> None:
    result = _conditional_statistic(
        np.asarray([True] * 4),
        np.asarray(response),
        _draws(),
        confidence=0.95,
    )
    assert result["point"] == point
    assert result["confidence_interval_95"] is None
    assert result["status"] == status


def test_conditional_interior_cell_fails_closed_if_any_denominator_is_zero() -> None:
    result = _conditional_statistic(
        np.asarray([True, False, False, False]),
        np.asarray([True, False, False, False]),
        _draws(),
        confidence=0.95,
    )
    assert result["point"] == 1.0
    assert result["confidence_interval_95"] is None
    assert result["status"] == ALL_CONDITIONAL

    result = _conditional_statistic(
        np.asarray([True, True, False, False]),
        np.asarray([True, False, False, False]),
        _draws(),
        confidence=0.95,
    )
    assert result["point"] == 0.5
    assert result["confidence_interval_95"] is None
    assert result["bootstrap_undefined_replicates"] > 0
    assert result["status"] == UNDEFINED_REPLICATES


def test_conditional_interior_cell_has_ci_when_every_replicate_is_defined() -> None:
    result = _conditional_statistic(
        np.asarray([True] * 4),
        np.asarray([True, False, True, False]),
        _draws(),
        confidence=0.95,
    )
    assert result["point"] == 0.5
    assert result["confidence_interval_95"] is not None
    assert result["status"] == PASS_CI
    assert result["bootstrap_defined_replicates"] == 2000
