from __future__ import annotations

import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4b_auxiliary import (
    AuxiliarySeriesCache,
    AuxiliarySeriesKey,
    calibrate_familywise_null,
    diagnostic_verdict,
    load_channel_policy,
    max_coherence,
)


def _key() -> AuxiliarySeriesKey:
    return AuxiliarySeriesKey(
        detector="H1",
        channel="H1:PEM-TEST_DQ",
        gps_start=1000,
        gps_end=1002,
        native_sample_rate_hz=64.0,
        stored_sample_rate_hz=32.0,
    )


def test_frozen_o4_channel_policy_is_diagnostic_only() -> None:
    policy = load_channel_policy("config/dante_light_o4b_aux_channels_v1.json")
    assert len(policy["channels"]["H1"]) == 14
    assert len(policy["channels"]["L1"]) == 11
    assert policy["scientific_policy"]["status"] == "DIAGNOSTIC_ONLY"
    assert all(
        not item["analyze"]
        for entries in policy["channels"].values()
        for item in entries
        if item["sample_rate_hz"] < 40
    )


def test_policy_rejects_promotion_to_veto(tmp_path) -> None:
    source = load_channel_policy("config/dante_light_o4b_aux_channels_v1.json")
    source["scientific_policy"]["status"] = "VETO"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ContractError, match="diagnostic-only"):
        load_channel_policy(path)


def test_o4_auxiliary_cache_cold_warm_and_tamper_detection(tmp_path) -> None:
    cache = AuxiliarySeriesCache(tmp_path)
    calls = 0

    def fetch(_):
        nonlocal calls
        calls += 1
        return np.linspace(-1.0, 1.0, 64, dtype=np.float32)

    cold, cold_meta, was_cached = cache.get_or_fetch(_key(), fetch)
    assert was_cached is False
    warm, warm_meta, was_cached = cache.get_or_fetch(_key(), fetch)
    assert was_cached is True
    assert calls == 1
    np.testing.assert_array_equal(cold, warm)
    assert cold_meta == warm_meta

    data_path, _ = cache._paths(_key())
    with data_path.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(ContractError, match="SHA256 mismatch"):
        cache.load(_key())


def test_o4_auxiliary_cache_rejects_unknown_schema() -> None:
    with pytest.raises(ContractError, match="unsupported"):
        AuxiliarySeriesKey(
            detector="H1",
            channel="H1:PEM-TEST_DQ",
            gps_start=1000,
            gps_end=1002,
            native_sample_rate_hz=64.0,
            stored_sample_rate_hz=32.0,
            schema_version=2,
        )


def test_max_coherence_distinguishes_shared_tone_from_independent_noise() -> None:
    rng = np.random.default_rng(17)
    sample_rate = 128.0
    t = np.arange(int(32 * sample_rate)) / sample_rate
    shared = np.sin(2 * np.pi * 30.0 * t)
    strain = shared + 0.2 * rng.normal(size=t.size)
    coupled = shared + 0.2 * rng.normal(size=t.size)
    independent = rng.normal(size=t.size)
    high = max_coherence(strain, coupled, sample_rate)
    low = max_coherence(strain, independent, sample_rate)
    assert high["max_coherence"] > 0.9
    assert high["peak_frequency_hz"] == pytest.approx(30.0)
    assert low["max_coherence"] < high["max_coherence"]
    assert high["n_welch_segments"] == 31


def test_diagnostic_verdict_never_returns_a_physical_label() -> None:
    cases = [
        ({}, "AUXILIARY_UNAVAILABLE"),
        ({"a": 0.2}, "NO_AUXILIARY_EXCESS"),
        ({"a": 0.7}, "PERSISTENT_BASELINE_COMPATIBLE"),
        ({"a": 0.9}, "AUXILIARY_EXCESS"),
    ]
    for values, expected in cases:
        result = diagnostic_verdict(values, 0.6, 0.8)
        assert result == expected
        assert result not in {"VETO", "COUPLED", "INSTRUMENTAL", "PHYSICAL"}
    assert (
        diagnostic_verdict({"a": 0.2}, float("nan"), 0.8)
        == "AUXILIARY_UNAVAILABLE"
    )


def test_familywise_null_uses_window_level_bootstrap() -> None:
    rng = np.random.default_rng(23)
    sample_rate = 64.0
    shape = (30, int(32 * sample_rate))
    strain = rng.normal(size=shape)
    auxiliary = rng.normal(size=shape)
    result = calibrate_familywise_null(
        {"H1:PEM-TEST_DQ": (strain, auxiliary, sample_rate)},
        n_bootstrap=20,
        seed=5,
    )
    assert result["n_channels"] == 1
    assert result["n_windows"] == 30
    assert result["n_time_shift_pairs"] == 30 * 29
    assert 0 <= result["time_shift_threshold"] <= 1
    assert 0 <= result["zero_lag_threshold"] <= 1
    assert result["method"].endswith("window identities")
