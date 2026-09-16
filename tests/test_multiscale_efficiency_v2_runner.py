from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import ROOT
from src.pipeline_v3_multiscale.efficiency_v2_reference import SCALE_LABELS
from src.pipeline_v3_multiscale.efficiency_v2_runner import (
    _generate_unit_waveform,
    _runner_run_key,
    classify_trial_endpoints,
    derive_waveform_seed,
    load_runner_contract,
    validate_runner_contract,
)


def _rehash(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def test_runner_contract_accepts_checked_in_protocol() -> None:
    contract = load_runner_contract(ROOT)
    assert contract["status"] == "APPROVED_PAIRED_INJECTION_INPUT"
    assert contract["paired_design"]["expected_total_trials"] == 7440
    assert contract["endpoints"]["scale_or_fusion_allowed"] is False
    assert contract["waveform"]["duration_s_by_morphology"] == {
        "Blip": 1.0,
        "NarrowChirp": 1.0,
        "Whistle": 1.0,
        "ScatteredLight": 2.0,
        "NoiseBlob": 4.0,
        "HarmonicComb": 4.0,
        "WallOfLines": 4.0,
        "KoiFish": 1.0,
    }


def test_checked_in_runner_preflight_evidence_is_self_consistent() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/multiscale_efficiency_v2"
        / "runner_preflight_summary.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert evidence["status"] == "PASS_MULTISCALE_EFFICIENCY_V2_RUNNER_PREFLIGHT"
    assert evidence["replay"]["paired_clean_snr_reference_verified"] is True
    assert evidence["replay"]["injection_before_whitening_verified"] is True
    assert evidence["replay"][
        "endpoint_construction_verified_without_publishing_scores"
    ]


def test_checked_in_paired_injection_evidence_is_self_consistent() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/multiscale_efficiency_v2"
        / "paired_injection_summary.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert (
        evidence["status"] == "PASS_VERIFIED_MULTISCALE_EFFICIENCY_V2_PAIRED_INJECTIONS"
    )
    assert evidence["clean_controls"]["row_total"] == 280
    assert evidence["trials"]["row_total"] == 7440
    assert evidence["scientific_boundary"]["scale_or_fusion_applied"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["waveform"]["duration_s_by_morphology"].update(
                Blip=2.0
            ),
            "durations",
        ),
        (
            lambda value: value["waveform"].update(injection_domain="whitened_strain"),
            "reconstruction",
        ),
        (
            lambda value: value["endpoints"].update(scale_or_fusion_allowed=True),
            "endpoint",
        ),
        (
            lambda value: value["paired_design"].update(
                same_backgrounds_across_morphologies=False
            ),
            "paired-design",
        ),
    ],
)
def test_runner_contract_rejects_scientific_drift(mutation, message: str) -> None:
    contract = load_runner_contract(ROOT)
    mutation(contract)
    with pytest.raises(ContractError, match=message):
        validate_runner_contract(_rehash(contract), root=ROOT)


def test_waveform_seed_binds_contract_detector_block_morphology_and_identity() -> None:
    row = {
        "detector": "H1",
        "identity_digest": "i" * 64,
        "raw_block": {"source_sha256": "r" * 64},
    }
    first = derive_waveform_seed("c" * 64, row, "Blip")
    assert first == derive_waveform_seed("c" * 64, row, "Blip")

    with_unused_snr = {**row, "target_snr": 48}
    assert first == derive_waveform_seed("c" * 64, with_unused_snr, "Blip")

    for changed_contract, changed_row, changed_morphology in (
        ("d" * 64, row, "Blip"),
        ("c" * 64, {**row, "detector": "L1"}, "Blip"),
        (
            "c" * 64,
            {**row, "raw_block": {"source_sha256": "s" * 64}},
            "Blip",
        ),
        ("c" * 64, {**row, "identity_digest": "j" * 64}, "Blip"),
        ("c" * 64, row, "Whistle"),
    ):
        assert first != derive_waveform_seed(
            changed_contract, changed_row, changed_morphology
        )


def test_stochastic_waveform_replay_is_deterministic() -> None:
    first = _generate_unit_waveform(
        morphology="NoiseBlob", duration_s=4.0, sample_rate_hz=4096, seed=17
    )
    second = _generate_unit_waveform(
        morphology="NoiseBlob", duration_s=4.0, sample_rate_hz=4096, seed=17
    )
    changed = _generate_unit_waveform(
        morphology="NoiseBlob", duration_s=4.0, sample_rate_hz=4096, seed=18
    )
    assert first.shape == (4 * 4096,)
    assert np.all(np.isfinite(first))
    assert np.array_equal(first, second)
    assert not np.array_equal(first, changed)


def _scores(primary: float, scales: float) -> dict[str, float]:
    return {"primary_32": primary, **{label: scales for label in SCALE_LABELS}}


def test_endpoint_keeps_primary_and_conditional_scale_decisions_separate() -> None:
    ineligible = classify_trial_endpoints(
        clean_scores=_scores(0.1, 0.2),
        injected_scores=_scores(0.9, 2.0),
        primary_threshold=1.0,
        scale_thresholds={label: 1.0 for label in SCALE_LABELS},
    )
    assert ineligible["primary"]["end_to_end_recovered"] is False
    assert ineligible["conditional_multiscale"]["eligible"] is False
    assert ineligible["conditional_multiscale"]["scale_or_fusion_applied"] is False
    assert all(
        row["diagnostic_exceeds_threshold"] is True
        and row["conditional_scale_response"] is None
        for row in ineligible["conditional_multiscale"]["scales"].values()
    )

    eligible = classify_trial_endpoints(
        clean_scores=_scores(1.1, 1.1),
        injected_scores=_scores(1.2, 0.9),
        primary_threshold=1.0,
        scale_thresholds={label: 1.0 for label in SCALE_LABELS},
    )
    assert eligible["primary"]["end_to_end_recovered"] is True
    assert eligible["primary"]["clean_exceeds_threshold"] is True
    assert all(
        row["conditional_scale_response"] is False
        for row in eligible["conditional_multiscale"]["scales"].values()
    )


def test_runner_run_key_binds_runtime_environment() -> None:
    arguments = {
        "runner_contract_digest": "a" * 64,
        "cohort_artifact_digest": "b" * 64,
        "reference_artifact_digest": "c" * 64,
        "runtime_environment_digest": "d" * 64,
    }
    baseline = _runner_run_key(**arguments)
    changed = _runner_run_key(**{**arguments, "runtime_environment_digest": "e" * 64})
    assert len(baseline) == 64
    assert baseline != changed
