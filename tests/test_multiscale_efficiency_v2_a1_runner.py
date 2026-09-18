from __future__ import annotations

import copy

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import ROOT
from src.pipeline_v3_multiscale.efficiency_v2_a1_runner import (
    BOUNDARY_CI,
    ENDPOINT_LABELS,
    _analyze_heldout,
    _expected_heldout_cardinalities,
    _heldout_run_key,
    _joint_null_run_key,
    empirical_tail_probability,
    holm_adjust,
    joint_surprise,
    load_a1_contract,
    paired_gain_statistic,
    paired_sign_flip_pvalue,
    validate_a1_contract,
)


def _rehash(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def test_a1_contract_accepts_checked_in_protocol() -> None:
    contract = load_a1_contract(ROOT)
    assert contract["status"] == "APPROVED_CONFIRMATORY_JOINT_NULL_INPUT"
    assert contract["joint_statistic"]["naive_scale_or_allowed"] is False
    assert contract["joint_null_calibration"]["rows_per_detector"] == 5000
    assert _expected_heldout_cardinalities(contract) == (2280, 7440, 96)
    assert contract["scientific_boundary"]["automatic_endpoint_promotion"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["joint_statistic"].update(naive_scale_or_allowed=True),
            "joint statistic",
        ),
        (
            lambda value: value["joint_null_calibration"].update(bootstrap_unit="row"),
            "joint-null calibration",
        ),
        (
            lambda value: value["waveform"]["duration_s_by_morphology"].update(
                Blip=2.0
            ),
            "waveform",
        ),
        (
            lambda value: value["heldout_confirmation"].update(
                confirmatory_morphologies=["Blip"]
            ),
            "held-out confirmation",
        ),
        (
            lambda value: value["uncertainty"].update(iid_bootstrap_allowed=True),
            "uncertainty",
        ),
        (
            lambda value: value["scientific_boundary"].update(
                automatic_endpoint_promotion=True
            ),
            "scientific boundary",
        ),
    ],
)
def test_a1_contract_rejects_scientific_drift(mutation, message: str) -> None:
    contract = load_a1_contract(ROOT)
    mutation(contract)
    with pytest.raises(ContractError, match=message):
        validate_a1_contract(_rehash(contract), root=ROOT)


def test_empirical_tail_probabilities_use_frozen_formulas() -> None:
    calibration = np.asarray([1.0, 2.0, 2.0, 4.0])
    assert empirical_tail_probability(2.0, calibration, heldout=False) == 0.75
    assert empirical_tail_probability(2.0, calibration, heldout=True) == 0.8
    assert empirical_tail_probability(5.0, calibration, heldout=True) == 0.2
    with pytest.raises(ContractError, match="sorted"):
        empirical_tail_probability(2.0, [2.0, 1.0], heldout=True)


def test_joint_surprise_is_maximum_marginal_surprise() -> None:
    calibration = {
        endpoint: np.asarray([1.0, 2.0, 3.0, 4.0]) for endpoint in ENDPOINT_LABELS
    }
    scores = {endpoint: 2.0 for endpoint in ENDPOINT_LABELS}
    scores["0.5"] = 4.0
    statistic, probabilities = joint_surprise(scores, calibration, heldout=False)
    assert probabilities["primary_32"] == 0.75
    assert probabilities["0.5"] == 0.25
    assert statistic == pytest.approx(-np.log10(0.25))


def test_holm_adjustment_and_paired_statistics_are_deterministic() -> None:
    assert holm_adjust({"a": 0.01, "b": 0.03, "c": 0.04}) == {
        "a": 0.03,
        "b": 0.06,
        "c": 0.06,
    }
    boundary = paired_gain_statistic(
        [1.0, 1.0], np.asarray([[0, 1], [1, 0]]), confidence=0.95
    )
    assert boundary["mean_gain"] == 1.0
    assert boundary["confidence_interval_95"] is None
    assert boundary["status"] == BOUNDARY_CI

    draws = np.asarray([[0, 0, 0], [1, 1, 1], [2, 2, 2], [0, 1, 2]])
    interior = paired_gain_statistic([0.0, 0.5, 1.0], draws, confidence=0.95)
    assert interior["mean_gain"] == 0.5
    assert interior["bootstrap_replicates"] == 4
    assert interior["confidence_interval_95"] is not None

    signs = np.asarray([[1.0, 1.0], [-1.0, -1.0], [1.0, -1.0]])
    assert paired_sign_flip_pvalue([1.0, 1.0], signs) == 0.5


def _synthetic_heldout_rows(contract: dict) -> tuple[list[dict], list[dict]]:
    confirmation = contract["heldout_confirmation"]
    clean_rows: list[dict] = []
    trial_rows: list[dict] = []
    for detector in ("H1", "L1"):
        for role, count in (
            ("heldout_background", confirmation["background_blocks_per_detector"]),
            (
                "heldout_primary_injection",
                confirmation["primary_blocks_per_detector"],
            ),
            (
                "heldout_secondary_control",
                confirmation["secondary_blocks_per_detector"],
            ),
        ):
            for role_index in range(count):
                clean_rows.append(
                    {
                        "detector": detector,
                        "role": role,
                        "role_index": role_index,
                        "endpoint": {
                            "a1_recovered": role == "heldout_background"
                            and role_index < 10,
                            "baseline_32_recovered": False,
                        },
                    }
                )
        for role, role_spec in confirmation["roles"].items():
            count = (
                confirmation["primary_blocks_per_detector"]
                if role == "heldout_primary_injection"
                else confirmation["secondary_blocks_per_detector"]
            )
            for morphology in role_spec["morphologies"]:
                confirmatory = morphology in confirmation["confirmatory_morphologies"]
                for target_snr in confirmation["target_snr"]:
                    for role_index in range(count):
                        trial_rows.append(
                            {
                                "detector": detector,
                                "role": role,
                                "role_index": role_index,
                                "morphology": morphology,
                                "target_snr": float(target_snr),
                                "endpoint": {
                                    "a1_recovered": confirmatory,
                                    "baseline_32_recovered": False,
                                },
                            }
                        )
    return clean_rows, trial_rows


def test_heldout_analysis_keeps_detectors_and_morphologies_separate() -> None:
    contract = load_a1_contract(ROOT)
    clean_rows, trial_rows = _synthetic_heldout_rows(contract)
    analysis = _analyze_heldout(
        clean_rows=clean_rows, trial_rows=trial_rows, contract=contract
    )
    assert len(analysis["cells"]) == 96
    assert set(analysis["confirmatory_hypotheses"]) == {
        "H1|Blip",
        "H1|Whistle",
        "L1|Blip",
        "L1|Whistle",
    }
    assert analysis["decision"]["background_no_significant_excess"] is True
    assert analysis["decision"]["all_confirmatory_improvements_pass"] is True
    assert analysis["decision"]["automatic_production_promotion"] is False


def test_a1_run_keys_bind_contract_runtime_and_inputs() -> None:
    joint = _joint_null_run_key("a" * 64, "b" * 64, "c" * 64)
    assert joint != _joint_null_run_key("d" * 64, "b" * 64, "c" * 64)
    heldout = _heldout_run_key("a" * 64, "b" * 64, "c" * 64, "d" * 64)
    assert heldout != _heldout_run_key("a" * 64, "b" * 64, "c" * 64, "e" * 64)
