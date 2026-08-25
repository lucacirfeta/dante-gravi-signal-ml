from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_power import (
    analyze_power,
    first_even_n_for_half_width,
    gate_pass_probability,
    load_power_config,
    minimum_passing_successes,
    worst_case_wilson_half_width,
)


def test_committed_power_analysis_is_non_gating_and_reproducible():
    config = load_power_config()
    result = analyze_power(config)
    assert result["status"] == "ANALYSIS_ONLY_NOT_FROZEN"
    assert result["interpretation"]["does_not_open_protected_outcomes"] is True
    assert result["first_n_meeting_power_target"] == 47
    assert result["background_precision"]["minimum_even_n_meeting_half_width"] == 264
    assert result["background_precision"]["recommended_n_half_width"] == pytest.approx(
        0.05622048386608308
    )
    assert result["recommendation_operating_characteristics"][
        "known_glitch_per_detector_morphology"
    ]["pass_probability_at_true_retention"] == pytest.approx(0.9212807354233151)
    body = dict(result)
    assert body.pop("artifact_digest") == canonical_json_sha256(body)


@pytest.mark.parametrize("n,minimum", [(18, 18), (20, 20), (25, 24), (60, 55), (90, 81)])
def test_minimum_passing_count_matches_exact_wilson_gate(n, minimum):
    assert minimum_passing_successes(
        n,
        minimum_retention=0.9,
        minimum_wilson_lower=0.8,
        confidence=0.95,
    ) == minimum


def test_old_small_confirmation_strata_are_underpowered_at_true_095():
    common = {
        "true_retention": 0.95,
        "minimum_retention": 0.9,
        "minimum_wilson_lower": 0.8,
        "confidence": 0.95,
    }
    assert gate_pass_probability(18, **common) == pytest.approx(0.3972143184582182)
    assert gate_pass_probability(20, **common) == pytest.approx(0.3584859224085419)
    assert gate_pass_probability(60, **common) == pytest.approx(0.9212807354233151)
    assert gate_pass_probability(90, **common) == pytest.approx(0.985480633688403)


def test_n90_compound_gate_rejects_80_even_though_wilson_passes():
    from src.dante_light.prefilter_evaluation import wilson_interval

    lower_80, _ = wilson_interval(80, 90, 0.95)
    assert lower_80 == pytest.approx(0.8074222740736939)
    assert lower_80 >= 0.8
    assert 80 / 90 < 0.9
    assert minimum_passing_successes(
        90,
        minimum_retention=0.9,
        minimum_wilson_lower=0.8,
        confidence=0.95,
    ) == 81


def test_background_precision_derives_300_as_rounded_not_minimal():
    assert first_even_n_for_half_width(confidence=0.95, maximum_half_width=0.06) == 264
    assert worst_case_wilson_half_width(250, confidence=0.95) > 0.06
    assert worst_case_wilson_half_width(300, confidence=0.95) < 0.06


def test_power_config_rejects_frozen_or_tampered_interpretation(tmp_path):
    payload = deepcopy(load_power_config())
    payload["status"] = "FROZEN"
    body = dict(payload)
    body.pop("contract_digest")
    payload["contract_digest"] = canonical_json_sha256(body)
    path = tmp_path / "power.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="cannot authorize a frozen protocol"):
        load_power_config(path)


def test_invalid_sample_size_fails_closed():
    with pytest.raises(ContractError, match="positive integer"):
        minimum_passing_successes(
            0,
            minimum_retention=0.9,
            minimum_wilson_lower=0.8,
            confidence=0.95,
        )
