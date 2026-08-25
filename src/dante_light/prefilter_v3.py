"""Frozen A/B morphology-sensitive feature families for DANTE-Light L4 v3."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
from scipy import stats

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v2 import _spectral_features, _time_frequency_power


SIGNED_ORDERING = "signed_ordering"
RIDGE_CONSISTENCY = "ridge_consistency"
SPECTRAL_V2_BASELINE = "spectral_v2_baseline"


def feature_names_by_family(config: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    return {
        SIGNED_ORDERING: tuple(str(value) for value in config[SIGNED_ORDERING]["features"]),
        RIDGE_CONSISTENCY: tuple(str(value) for value in config[RIDGE_CONSISTENCY]["features"]),
        SPECTRAL_V2_BASELINE: (
            "spectral_flux_median",
            "spectral_flux_max",
            "spectral_centroid_range_fraction",
            "spectral_centroid_slope_abs",
            "spectral_entropy_median",
            "spectral_entropy_range",
        ),
    }


@dataclass(frozen=True, slots=True)
class PrefilterFeaturesV3:
    values: dict[str, float]

    def __post_init__(self) -> None:
        if not self.values:
            raise ContractError("prefilter v3 feature vector is empty")
        clean = {}
        for name, raw in self.values.items():
            value = float(raw)
            if not name or not math.isfinite(value):
                raise ContractError(f"invalid prefilter v3 feature {name}")
            clean[str(name)] = value
        object.__setattr__(self, "values", clean)


def _normalized_time(size: int) -> np.ndarray:
    if size < 2:
        raise ContractError("prefilter v3 requires at least two STFT frames")
    return np.linspace(0.0, 1.0, size, dtype=np.float64)


def _safe_spearman(x: np.ndarray, y: np.ndarray) -> float:
    if np.ptp(x) == 0.0 or np.ptp(y) == 0.0:
        return 0.0
    value = float(stats.spearmanr(x, y).statistic)
    return value if math.isfinite(value) else 0.0


def _weighted_line(
    x: np.ndarray,
    y: np.ndarray,
    weights: np.ndarray,
) -> tuple[float, float]:
    clean_weights = np.maximum(np.asarray(weights, dtype=np.float64), 0.0)
    total = float(clean_weights.sum())
    if total <= np.finfo(np.float64).eps:
        clean_weights = np.ones_like(clean_weights)
        total = float(clean_weights.sum())
    x_mean = float(np.sum(clean_weights * x) / total)
    y_mean = float(np.sum(clean_weights * y) / total)
    centered_x = x - x_mean
    denominator = float(np.sum(clean_weights * centered_x * centered_x))
    slope = 0.0 if denominator <= np.finfo(np.float64).eps else float(
        np.sum(clean_weights * centered_x * (y - y_mean)) / denominator
    )
    intercept = y_mean - slope * x_mean
    residual = float(
        np.sqrt(np.sum(clean_weights * (y - (intercept + slope * x)) ** 2) / total)
    )
    return slope, residual


def _arrival_time(energy: np.ndarray, quantile: float) -> float:
    values = np.maximum(np.asarray(energy, dtype=np.float64), 0.0)
    total = float(values.sum())
    if total <= np.finfo(np.float64).eps:
        return 0.0
    cumulative = np.cumsum(values) / total
    index = min(int(np.searchsorted(cumulative, quantile, side="left")), values.size - 1)
    if values.size == 1:
        return 0.0
    return float(index / (values.size - 1))


def _centroid(
    frequencies: np.ndarray,
    power: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    totals = np.maximum(power.sum(axis=0), np.finfo(np.float64).eps)
    low = float(frequencies[0])
    width = max(float(frequencies[-1] - low), np.finfo(np.float64).eps)
    normalized_frequency = (frequencies - low) / width
    centroid = np.sum(normalized_frequency[:, None] * power, axis=0) / totals
    return np.asarray(centroid, dtype=np.float64), np.asarray(totals, dtype=np.float64)


def _signed_ordering_features(
    frequencies: np.ndarray,
    power: np.ndarray,
    config: Mapping[str, Any],
) -> dict[str, float]:
    centroid, frame_energy = _centroid(frequencies, power)
    time = _normalized_time(centroid.size)
    slope, _residual = _weighted_line(time, centroid, frame_energy)
    positive_step_fraction = float(np.mean(np.diff(centroid) > 0.0))

    band_count = int(config["log_frequency_band_count"])
    if band_count != 3:
        raise ContractError("prefilter v3 signed ordering requires three log-frequency bands")
    edges = np.geomspace(float(frequencies[0]), float(frequencies[-1]), band_count + 1)
    arrivals = []
    quantile = float(config["energy_arrival_quantile"])
    for index in range(band_count):
        selected = (frequencies >= edges[index]) & (
            frequencies <= edges[index + 1]
            if index == band_count - 1
            else frequencies < edges[index + 1]
        )
        if not np.any(selected):
            raise ContractError("prefilter v3 log-frequency band is empty")
        arrivals.append(_arrival_time(power[selected].sum(axis=0), quantile))
    return {
        "signed_centroid_slope": slope,
        "centroid_time_spearman": _safe_spearman(time, centroid),
        "centroid_positive_step_fraction": positive_step_fraction,
        "low_band_arrival_time": arrivals[0],
        "mid_band_arrival_time": arrivals[1],
        "high_band_arrival_time": arrivals[2],
        "high_minus_low_arrival_time": arrivals[2] - arrivals[0],
    }


def _ridge_consistency_features(
    frequencies: np.ndarray,
    power: np.ndarray,
    config: Mapping[str, Any],
) -> dict[str, float]:
    if config["ridge_method"] != "per_frame_maximum_power":
        raise ContractError("unsupported prefilter v3 ridge method")
    indices = np.argmax(power, axis=0)
    ridge_frequency = np.asarray(frequencies[indices], dtype=np.float64)
    ridge_power = np.asarray(power[indices, np.arange(power.shape[1])], dtype=np.float64)
    time = _normalized_time(ridge_frequency.size)
    low = float(frequencies[0])
    width = max(float(frequencies[-1] - low), np.finfo(np.float64).eps)
    normalized_ridge = (ridge_frequency - low) / width
    slope, linear_residual = _weighted_line(time, normalized_ridge, ridge_power)

    exponent = float(config["inspiral_coordinate_power"])
    inspiral_coordinate = np.power(ridge_frequency, exponent)
    coordinate_width = float(np.ptp(inspiral_coordinate))
    if coordinate_width <= np.finfo(np.float64).eps:
        inspiral_residual = 0.0
    else:
        normalized_coordinate = (
            inspiral_coordinate - float(np.min(inspiral_coordinate))
        ) / coordinate_width
        _inspiral_slope, inspiral_residual = _weighted_line(
            time, normalized_coordinate, ridge_power
        )
    total_power = max(float(power.sum()), np.finfo(np.float64).eps)
    return {
        "ridge_signed_slope": slope,
        "ridge_time_spearman": _safe_spearman(time, normalized_ridge),
        "ridge_positive_step_fraction": float(np.mean(np.diff(normalized_ridge) > 0.0)),
        "ridge_energy_fraction": float(ridge_power.sum() / total_power),
        "ridge_linear_residual": linear_residual,
        "ridge_inspiral_residual": inspiral_residual,
    }


def extract_prefilter_v3_features(
    whitened: np.ndarray,
    *,
    config: Mapping[str, Any],
) -> PrefilterFeaturesV3:
    values = np.asarray(whitened, dtype=np.float64)
    sample_rate = int(config["sample_rate_hz"])
    if values.ndim != 1 or values.size < sample_rate:
        raise ContractError("prefilter v3 expects at least one second of 1D strain")
    if not np.all(np.isfinite(values)):
        raise ContractError("prefilter v3 strain contains non-finite samples")
    frequencies, power = _time_frequency_power(values, config)
    extracted = {
        **_signed_ordering_features(frequencies, power, config[SIGNED_ORDERING]),
        **_ridge_consistency_features(frequencies, power, config[RIDGE_CONSISTENCY]),
        **_spectral_features(frequencies, power),
    }
    expected = {
        name
        for family in feature_names_by_family(config).values()
        for name in family
    }
    if set(extracted) != expected:
        raise ContractError("prefilter v3 feature schema mismatch")
    return PrefilterFeaturesV3(extracted)
