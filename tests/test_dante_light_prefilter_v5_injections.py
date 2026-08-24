from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v5_injections import (
    load_frozen_trials,
    parameters_from_trial,
)
from src.dante_light.prefilter_v5_protocol import ROOT
from scripts.verify_dante_light_prefilter_v5_injections import verify


PROTOCOL_PATH = ROOT / "config/dante_light_prefilter_protocol_v5.json"
TRIAL_PATH = ROOT / "config/dante_light_prefilter_v5_injection_trials.jsonl"


def _protocol() -> dict:
    return json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))


def test_all_frozen_trials_resolve_without_outcomes() -> None:
    protocol = _protocol()
    trials = load_frozen_trials(TRIAL_PATH)
    assert len(trials) == 1440
    populations = set()
    for trial in trials.values():
        parameters = parameters_from_trial(trial, protocol)
        populations.add(trial["population"])
        assert parameters.sample_rate_hz == 4096
        assert trial["outcome_fields_present"] == []
    assert populations == {
        "legacy_comparability",
        "aligned_tidal_nsbh_stress",
    }


def test_tidal_trial_freezes_body_order_chi_ns_and_lambda() -> None:
    protocol = _protocol()
    trial = next(
        row
        for row in load_frozen_trials(TRIAL_PATH).values()
        if row["population"] == "aligned_tidal_nsbh_stress"
    )
    parameters = parameters_from_trial(trial, protocol)
    assert parameters.approximant == "IMRPhenomNSBH"
    assert parameters.mass_1_msun >= parameters.mass_2_msun
    assert parameters.spin_2z == 0.0
    assert parameters.lambda_1 == 0.0
    assert parameters.lambda_2 == trial["lambda_2"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("spin_2z", 0.01), ("lambda_2", 1001.0), ("mass_1_msun", 4.99)],
)
def test_tidal_trial_fails_closed_outside_frozen_contract(field: str, value: float) -> None:
    protocol = _protocol()
    trial = next(
        copy.deepcopy(row)
        for row in load_frozen_trials(TRIAL_PATH).values()
        if row["population"] == "aligned_tidal_nsbh_stress"
    )
    trial[field] = value
    with pytest.raises(ContractError):
        parameters_from_trial(trial, protocol)


def test_legacy_trial_remains_point_particle_comparator() -> None:
    protocol = _protocol()
    trial = next(
        row
        for row in load_frozen_trials(TRIAL_PATH).values()
        if row["system"] == "NSBH_10_1.4_LEGACY"
    )
    parameters = parameters_from_trial(trial, protocol)
    assert parameters.approximant == "IMRPhenomD"
    assert parameters.spin_1z == parameters.spin_2z == 0.0
    assert parameters.lambda_1 == parameters.lambda_2 == 0.0
    assert np.isclose(parameters.mass_1_msun, 10.0)
    assert np.isclose(parameters.mass_2_msun, 1.4)


def test_structural_verifier_is_outcome_blind() -> None:
    result = verify()
    assert result["status"] == "PASS_OUTCOME_BLIND"
    assert result["trial_count"] == 1440
    assert result["partitions"] == {"confirmation": 720, "development": 720}
    assert result["detectors"] == {"H1": 720, "L1": 720}
    assert result["outcome_fields_accessed"] == []
    assert not result["waveform_smoke_executed"]
