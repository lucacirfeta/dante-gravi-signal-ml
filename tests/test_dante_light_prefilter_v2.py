from __future__ import annotations

import numpy as np

from src.dante_light.prefilter_v2 import (
    extract_prefilter_v2_features,
    feature_names_by_family,
)
from src.dante_light.prefilter_v2_protocol import load_prefilter_v2_protocol


def _config():
    return load_prefilter_v2_protocol().payload["feature_extraction"]


def test_v2_feature_vector_is_complete_finite_and_deterministic():
    config = _config()
    rng = np.random.default_rng(17)
    values = rng.normal(size=32 * int(config["sample_rate_hz"]))
    first = extract_prefilter_v2_features(values, config=config)
    second = extract_prefilter_v2_features(values, config=config)
    expected = {
        name
        for family in feature_names_by_family(config).values()
        for name in family
    }
    assert set(first.values) == expected
    assert first.values == second.values
    assert all(np.isfinite(value) and value >= 0.0 for value in first.values.values())


def test_temporal_features_respond_to_a_localized_transient():
    config = _config()
    sample_rate = int(config["sample_rate_hz"])
    rng = np.random.default_rng(23)
    background = rng.normal(size=32 * sample_rate)
    transient = background.copy()
    transient[15 * sample_rate : 15 * sample_rate + sample_rate // 8] += 12.0
    base = extract_prefilter_v2_features(background, config=config).values
    event = extract_prefilter_v2_features(transient, config=config).values
    assert event["temporal_peak_ratio_125ms"] > base["temporal_peak_ratio_125ms"]
    assert event["temporal_top_energy_fraction_125ms"] > base["temporal_top_energy_fraction_125ms"]


def test_spectral_evolution_distinguishes_chirp_from_stationary_tone():
    config = _config()
    sample_rate = int(config["sample_rate_hz"])
    time = np.arange(32 * sample_rate) / sample_rate
    stationary = np.sin(2.0 * np.pi * 80.0 * time)
    chirp = np.sin(2.0 * np.pi * (30.0 * time + 0.5 * 8.0 * time * time))
    fixed = extract_prefilter_v2_features(stationary, config=config).values
    evolving = extract_prefilter_v2_features(chirp, config=config).values
    assert evolving["spectral_centroid_range_fraction"] > fixed["spectral_centroid_range_fraction"]
    assert evolving["spectral_centroid_slope_abs"] > fixed["spectral_centroid_slope_abs"]
