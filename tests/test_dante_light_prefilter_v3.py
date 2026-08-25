from __future__ import annotations

import numpy as np
from scipy import signal

from src.dante_light.prefilter_v2 import extract_prefilter_v2_features
from src.dante_light.prefilter_v3 import (
    extract_prefilter_v3_features,
    feature_names_by_family,
)
from src.dante_light.prefilter_v3_protocol import load_prefilter_v3_protocol


def _config():
    return load_prefilter_v3_protocol().payload["feature_extraction"]


def test_v3_feature_vector_is_complete_finite_and_deterministic():
    config = _config()
    rng = np.random.default_rng(20260823)
    values = rng.normal(size=32 * int(config["sample_rate_hz"]))
    first = extract_prefilter_v3_features(values, config=config)
    second = extract_prefilter_v3_features(values, config=config)
    expected = {
        name
        for family in feature_names_by_family(config).values()
        for name in family
    }
    assert set(first.values) == expected
    assert first.values == second.values
    assert all(np.isfinite(value) for value in first.values.values())


def test_v3_signed_features_preserve_chirp_direction():
    config = _config()
    sample_rate = int(config["sample_rate_hz"])
    time = np.arange(32 * sample_rate, dtype=np.float64) / sample_rate
    up = signal.chirp(time, f0=30.0, f1=800.0, t1=32.0, method="linear")
    down = signal.chirp(time, f0=800.0, f1=30.0, t1=32.0, method="linear")
    upward = extract_prefilter_v3_features(up, config=config).values
    downward = extract_prefilter_v3_features(down, config=config).values
    assert upward["signed_centroid_slope"] > 0.0
    assert downward["signed_centroid_slope"] < 0.0
    assert upward["centroid_time_spearman"] > 0.9
    assert downward["centroid_time_spearman"] < -0.9
    assert upward["high_minus_low_arrival_time"] > 0.0
    assert downward["high_minus_low_arrival_time"] < 0.0
    assert upward["ridge_signed_slope"] > 0.0
    assert downward["ridge_signed_slope"] < 0.0


def test_v3_ridge_fit_distinguishes_smooth_from_discontinuous_track():
    config = _config()
    sample_rate = int(config["sample_rate_hz"])
    time = np.arange(32 * sample_rate, dtype=np.float64) / sample_rate
    smooth = signal.chirp(time, f0=40.0, f1=600.0, t1=32.0, method="linear")
    first = signal.chirp(time[: 16 * sample_rate], f0=40.0, f1=300.0, t1=16.0)
    second = signal.chirp(time[: 16 * sample_rate], f0=700.0, f1=200.0, t1=16.0)
    discontinuous = np.concatenate([first, second])
    smooth_features = extract_prefilter_v3_features(smooth, config=config).values
    broken_features = extract_prefilter_v3_features(discontinuous, config=config).values
    assert smooth_features["ridge_linear_residual"] < broken_features["ridge_linear_residual"]
    assert smooth_features["ridge_time_spearman"] > broken_features["ridge_time_spearman"]


def test_v3_spectral_baseline_matches_v2_exactly():
    config = _config()
    v2_config = dict(load_prefilter_v3_protocol().payload["feature_extraction"])
    v2_config.update(
        {
            "temporal_block_durations_s": [0.125, 0.5, 2.0],
            "temporal_overlap_fraction": 0.5,
            "temporal_top_fraction": 0.05,
            "robust_z_threshold": 6.0,
            "dyadic_levels": 8,
            "wavelet_tail_quantile": 0.995,
        }
    )
    rng = np.random.default_rng(31)
    values = rng.normal(size=32 * int(config["sample_rate_hz"]))
    v3 = extract_prefilter_v3_features(values, config=config).values
    v2 = extract_prefilter_v2_features(values, config=v2_config).values
    for name in feature_names_by_family(config)["spectral_v2_baseline"]:
        assert v3[name] == v2[name]
