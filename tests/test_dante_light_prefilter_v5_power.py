from __future__ import annotations

import pytest

from src.dante_light.prefilter_v5_power import (
    analyze_power, gate_pass_probability, load_power_config,
    minimum_passing_successes, worst_case_wilson_half_width,
)


def test_approved_retention_boundaries_and_power() -> None:
    assert minimum_passing_successes(60, minimum_retention=0.9, minimum_wilson_lower=0.8, confidence=0.95) == 55
    assert minimum_passing_successes(90, minimum_retention=0.9, minimum_wilson_lower=0.8, confidence=0.95) == 81
    assert gate_pass_probability(60, true_retention=0.95, minimum_retention=0.9, minimum_wilson_lower=0.8, confidence=0.95) == pytest.approx(0.9212807354)
    assert gate_pass_probability(90, true_retention=0.95, minimum_retention=0.9, minimum_wilson_lower=0.8, confidence=0.95) == pytest.approx(0.9854806337)


def test_frozen_power_contract_recomputes_without_outcomes() -> None:
    config, design = load_power_config()
    result = analyze_power(config, design)
    assert result["status"] == "FROZEN_POWER_CONTRACT_VERIFIED"
    assert result["background_precision"]["minimum_even_n_meeting_half_width"] == 264
    assert result["background_precision"]["frozen_n_worst_case_half_width"] == pytest.approx(0.05622048386608308)
    assert result["net_saving_gate_power"]["prospective_power_claimed"] is False
    assert result["outcomes_accessed"] == []


def test_wilson_background_requires_even_sample_size() -> None:
    with pytest.raises(Exception, match="positive even"):
        worst_case_wilson_half_width(299, confidence=0.95)
