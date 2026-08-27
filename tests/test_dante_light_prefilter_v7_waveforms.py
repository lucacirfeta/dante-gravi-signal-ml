from __future__ import annotations

from src.dante_light.prefilter_v7_training_freeze import ROOT
from src.dante_light.prefilter_v7_waveforms import (
    risk_calibration_trials,
    verify_waveform_cache,
    waveform_contract,
    waveform_run_key,
)


def test_v7_risk_waveform_contract_is_outcome_blind_and_deterministic() -> None:
    contract = waveform_contract(root=ROOT)
    assert contract["partition"] == "risk_calibration"
    assert contract["outcomes_accessed"] == []
    assert contract["confirmation_accessed"] == []
    assert contract["o4b_accessed"] == []
    assert waveform_run_key(contract) == waveform_run_key(contract)


def test_v7_risk_waveform_trials_are_complete_and_outcome_blind() -> None:
    rows = risk_calibration_trials(root=ROOT)
    assert len(rows) == 720
    assert len({row["source_id"] for row in rows}) == 720
    assert {row["detector"] for row in rows} == {"H1", "L1"}
    assert {row["system"] for row in rows} == {
        "BBH_10_10",
        "BBH_30_30",
        "NSBH_10_1.4_LEGACY",
        "NSBH_ALIGNED_TIDAL_STRESS",
    }
    assert all(row["outcome_fields_present"] == [] for row in rows)


def test_v7_saved_risk_waveform_cache_verifies_without_outcome_access() -> None:
    _, records, summary = verify_waveform_cache(root=ROOT)
    assert len(records) == 720
    assert summary["artifact_digest"] == (
        "1a7a8a0aa631f4ee78b6b83421fa64f616e348fb5811bbdd04547ccdde5f8e90"
    )
    assert summary["outcomes_accessed"] == []
    assert summary["confirmation_accessed"] == []
    assert summary["o4b_accessed"] == []
