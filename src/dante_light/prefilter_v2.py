"""Cheap, run-agnostic candidate feature families for L4 v2."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
from scipy import ndimage, signal

from src.dante_light.contracts import ContractError


def _duration_suffix(duration_s: float) -> str:
    milliseconds = float(duration_s) * 1000.0
    rounded = int(round(milliseconds))
    if not np.isclose(milliseconds, rounded):
        raise ContractError("temporal block durations must resolve to integer milliseconds")
    return f"{rounded}ms"


def feature_names_by_family(config: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    temporal = []
    for duration in config["temporal_block_durations_s"]:
        suffix = _duration_suffix(float(duration))
        temporal.extend(
            (
                f"temporal_peak_ratio_{suffix}",
                f"temporal_top_energy_fraction_{suffix}",
                f"temporal_excursion_fraction_{suffix}",
                f"temporal_longest_excursion_fraction_{suffix}",
            )
        )
    return {
        "temporal_energy": tuple(temporal),
        "tf_cluster": (
            "tf_occupancy",
            "tf_cluster_count_density",
            "tf_largest_cluster_fraction",
            "tf_largest_cluster_energy_fraction",
            "tf_cluster_time_span_fraction",
            "tf_cluster_band_span_fraction",
        ),
        "spectral_evolution": (
            "spectral_flux_median",
            "spectral_flux_max",
            "spectral_centroid_range_fraction",
            "spectral_centroid_slope_abs",
            "spectral_entropy_median",
            "spectral_entropy_range",
        ),
        "wavelet_sparse": (
            "wavelet_max_robust_z",
            "wavelet_tail_fraction",
            "wavelet_tail_mean_ratio",
            "wavelet_scale_entropy",
            "wavelet_peak_scale_energy_fraction",
            "wavelet_longest_tail_run_fraction",
        ),
    }


@dataclass(frozen=True, slots=True)
class PrefilterFeaturesV2:
    values: dict[str, float]

    def __post_init__(self) -> None:
        if not self.values:
            raise ContractError("prefilter v2 feature vector is empty")
        clean = {}
        for name, raw in self.values.items():
            value = float(raw)
            if not name or not math.isfinite(value) or value < 0.0:
                raise ContractError(f"invalid prefilter v2 feature {name}")
            clean[str(name)] = value
        object.__setattr__(self, "values", clean)


def _longest_true_fraction(mask: np.ndarray) -> float:
    values = np.asarray(mask, dtype=bool)
    if values.size == 0 or not values.any():
        return 0.0
    padded = np.r_[False, values, False]
    changes = np.flatnonzero(padded[1:] != padded[:-1])
    lengths = changes[1::2] - changes[::2]
    return float(lengths.max() / values.size)


def _block_means(values: np.ndarray, size: int, step: int) -> np.ndarray:
    if size > values.size:
        raise ContractError("temporal block is longer than the feature window")
    starts = np.arange(0, values.size - size + 1, step, dtype=np.int64)
    cumulative = np.r_[0.0, np.cumsum(values, dtype=np.float64)]
    return (cumulative[starts + size] - cumulative[starts]) / float(size)


def _robust_z(values: np.ndarray) -> np.ndarray:
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    scale = max(1.4826 * mad, np.finfo(np.float64).eps)
    return (values - median) / scale


def _temporal_features(values: np.ndarray, config: Mapping[str, Any]) -> dict[str, float]:
    energy = values * values
    sample_rate = int(config["sample_rate_hz"])
    overlap = float(config["temporal_overlap_fraction"])
    top_fraction = float(config["temporal_top_fraction"])
    threshold = float(config["robust_z_threshold"])
    result = {}
    for duration in config["temporal_block_durations_s"]:
        suffix = _duration_suffix(float(duration))
        size = int(round(float(duration) * sample_rate))
        step = max(1, int(round(size * (1.0 - overlap))))
        block_energy = _block_means(energy, size, step)
        median = max(float(np.median(block_energy)), np.finfo(np.float64).eps)
        count = max(1, int(math.ceil(top_fraction * block_energy.size)))
        total = max(float(block_energy.sum()), np.finfo(np.float64).eps)
        excursions = _robust_z(block_energy) >= threshold
        result[f"temporal_peak_ratio_{suffix}"] = float(block_energy.max() / median)
        result[f"temporal_top_energy_fraction_{suffix}"] = float(
            np.partition(block_energy, -count)[-count:].sum() / total
        )
        result[f"temporal_excursion_fraction_{suffix}"] = float(excursions.mean())
        result[f"temporal_longest_excursion_fraction_{suffix}"] = _longest_true_fraction(excursions)
    return result


def _time_frequency_power(
    values: np.ndarray, config: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray]:
    sample_rate = int(config["sample_rate_hz"])
    frame = int(round(float(config["stft_frame_duration_s"]) * sample_rate))
    overlap = int(round(frame * float(config["stft_overlap_fraction"])))
    frequencies, _times, transform = signal.stft(
        values,
        fs=sample_rate,
        window="hann",
        nperseg=frame,
        noverlap=overlap,
        nfft=frame,
        boundary=None,
        padded=False,
    )
    low, high = (float(value) for value in config["analysis_band_hz"])
    selected = (frequencies >= low) & (frequencies <= high)
    power = np.abs(transform[selected]) ** 2
    if power.size == 0 or power.shape[1] < 2:
        raise ContractError("prefilter v2 STFT has insufficient band coverage")
    return frequencies[selected], np.asarray(power, dtype=np.float64)


def _tf_cluster_features(power: np.ndarray, config: Mapping[str, Any]) -> dict[str, float]:
    log_power = np.log(power + np.finfo(np.float64).tiny)
    median = np.median(log_power, axis=1, keepdims=True)
    mad = np.median(np.abs(log_power - median), axis=1, keepdims=True)
    scale = np.maximum(1.4826 * mad, np.finfo(np.float64).eps)
    mask = (log_power - median) / scale >= float(config["robust_z_threshold"])
    labels, count = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    result = {
        "tf_occupancy": float(mask.mean()),
        "tf_cluster_count_density": float(count / mask.size),
        "tf_largest_cluster_fraction": 0.0,
        "tf_largest_cluster_energy_fraction": 0.0,
        "tf_cluster_time_span_fraction": 0.0,
        "tf_cluster_band_span_fraction": 0.0,
    }
    if count == 0:
        return result
    sizes = ndimage.sum(mask, labels, index=np.arange(1, count + 1))
    largest = int(np.argmax(sizes)) + 1
    selected = labels == largest
    rows, columns = np.nonzero(selected)
    result["tf_largest_cluster_fraction"] = float(selected.sum() / mask.size)
    result["tf_largest_cluster_energy_fraction"] = float(
        power[selected].sum() / max(float(power.sum()), np.finfo(np.float64).eps)
    )
    result["tf_cluster_time_span_fraction"] = float(
        (columns.max() - columns.min() + 1) / mask.shape[1]
    )
    result["tf_cluster_band_span_fraction"] = float(
        (rows.max() - rows.min() + 1) / mask.shape[0]
    )
    return result


def _spectral_features(frequencies: np.ndarray, power: np.ndarray) -> dict[str, float]:
    totals = np.maximum(power.sum(axis=0, keepdims=True), np.finfo(np.float64).eps)
    distribution = power / totals
    band_width = max(float(frequencies[-1] - frequencies[0]), np.finfo(np.float64).eps)
    normalized_frequency = (frequencies - frequencies[0]) / band_width
    centroid = np.sum(normalized_frequency[:, None] * distribution, axis=0)
    entropy = -np.sum(
        distribution * np.log(distribution + np.finfo(np.float64).tiny), axis=0
    ) / math.log(power.shape[0])
    flux = 0.5 * np.sum(np.abs(np.diff(distribution, axis=1)), axis=0)
    normalized_time = np.linspace(0.0, 1.0, centroid.size)
    slope = float(np.polyfit(normalized_time, centroid, 1)[0])
    return {
        "spectral_flux_median": float(np.median(flux)),
        "spectral_flux_max": float(np.max(flux)),
        "spectral_centroid_range_fraction": float(np.ptp(centroid)),
        "spectral_centroid_slope_abs": abs(slope),
        "spectral_entropy_median": float(np.median(entropy)),
        "spectral_entropy_range": float(np.ptp(entropy)),
    }


def _wavelet_features(values: np.ndarray, config: Mapping[str, Any]) -> dict[str, float]:
    approximation = np.asarray(values, dtype=np.float64)
    threshold = float(config["robust_z_threshold"])
    tail_quantile = float(config["wavelet_tail_quantile"])
    energies = []
    tail_count = 0
    coefficient_count = 0
    max_z = 0.0
    longest = 0.0
    tail_ratios = []
    for _level in range(int(config["dyadic_levels"])):
        if approximation.size < 2:
            raise ContractError("dyadic level exceeds feature window length")
        if approximation.size % 2:
            approximation = approximation[:-1]
        even = approximation[0::2]
        odd = approximation[1::2]
        detail = (even - odd) / math.sqrt(2.0)
        approximation = (even + odd) / math.sqrt(2.0)
        absolute = np.abs(detail)
        median = float(np.median(absolute))
        mad = float(np.median(np.abs(absolute - median)))
        scale = max(1.4826 * mad, np.finfo(np.float64).eps)
        robust = np.abs(absolute - median) / scale
        mask = robust >= threshold
        quantile = float(np.quantile(absolute, tail_quantile))
        tail = absolute[absolute >= quantile]
        tail_ratios.append(float(tail.mean() / max(median, np.finfo(np.float64).eps)))
        energies.append(float(np.sum(detail * detail)))
        tail_count += int(mask.sum())
        coefficient_count += int(mask.size)
        max_z = max(max_z, float(robust.max()))
        longest = max(longest, _longest_true_fraction(mask))
    energy = np.asarray(energies, dtype=np.float64)
    distribution = energy / max(float(energy.sum()), np.finfo(np.float64).eps)
    entropy = -float(
        np.sum(distribution * np.log(distribution + np.finfo(np.float64).tiny))
        / math.log(distribution.size)
    )
    return {
        "wavelet_max_robust_z": max_z,
        "wavelet_tail_fraction": float(tail_count / coefficient_count),
        "wavelet_tail_mean_ratio": float(max(tail_ratios)),
        "wavelet_scale_entropy": entropy,
        "wavelet_peak_scale_energy_fraction": float(distribution.max()),
        "wavelet_longest_tail_run_fraction": longest,
    }


def extract_prefilter_v2_features(
    whitened: np.ndarray,
    *,
    config: Mapping[str, Any],
) -> PrefilterFeaturesV2:
    values = np.asarray(whitened, dtype=np.float64)
    sample_rate = int(config["sample_rate_hz"])
    if values.ndim != 1 or values.size < sample_rate:
        raise ContractError("prefilter v2 expects at least one second of 1D strain")
    if not np.all(np.isfinite(values)):
        raise ContractError("prefilter v2 strain contains non-finite samples")
    frequencies, power = _time_frequency_power(values, config)
    extracted = {
        **_temporal_features(values, config),
        **_tf_cluster_features(power, config),
        **_spectral_features(frequencies, power),
        **_wavelet_features(values, config),
    }
    expected = {
        name
        for family in feature_names_by_family(config).values()
        for name in family
    }
    if set(extracted) != expected:
        raise ContractError("prefilter v2 feature schema mismatch")
    return PrefilterFeaturesV2(extracted)
