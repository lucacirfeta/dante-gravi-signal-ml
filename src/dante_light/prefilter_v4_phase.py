"""Label-blind phase-aware feasibility probe for DANTE-Light.

The probe derives instantaneous frequency from the unwrapped phase of the
analytic, band-limited whitened strain.  It does not fit a classifier, inspect
cohort labels, define a routing threshold, or constitute a v4 protocol.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from scipy import signal, stats

from src.dante_light.contracts import ContractError


def _weighted_line_residual(
    x: np.ndarray, y: np.ndarray, weight: np.ndarray
) -> float:
    design = np.column_stack((np.ones(x.size, dtype=np.float64), x))
    root_weight = np.sqrt(np.maximum(weight, np.finfo(np.float64).eps))
    beta, *_ = np.linalg.lstsq(
        design * root_weight[:, None], y * root_weight, rcond=None
    )
    residual = y - design @ beta
    scale = max(float(np.ptp(y)), np.finfo(np.float64).eps)
    return float(np.sqrt(np.average(residual**2, weights=weight)) / scale)


def _weighted_cubic_phase_residual(
    time: np.ndarray, phase: np.ndarray, weight: np.ndarray
) -> float:
    span = max(float(np.ptp(time)), np.finfo(np.float64).eps)
    normalized = (time - float(np.mean(time))) / span
    design = np.column_stack(
        (
            np.ones(time.size, dtype=np.float64),
            normalized,
            normalized**2,
            normalized**3,
        )
    )
    root_weight = np.sqrt(np.maximum(weight, np.finfo(np.float64).eps))
    beta, *_ = np.linalg.lstsq(
        design * root_weight[:, None], phase * root_weight, rcond=None
    )
    residual = phase - design @ beta
    concentration = np.abs(np.average(np.exp(1j * residual), weights=weight))
    return float(1.0 - concentration)


def extract_phase_feasibility_features(
    values: np.ndarray,
    *,
    sample_rate_hz: int,
    analysis_band_hz: tuple[float, float] | list[float],
    config: Mapping[str, object],
) -> dict[str, float]:
    """Extract deterministic analytic-phase summaries from one window."""

    data = np.asarray(values, dtype=np.float64)
    if data.ndim != 1 or data.size < 32 or not np.all(np.isfinite(data)):
        raise ContractError("phase feasibility input must be a finite 1-D window")
    sample_rate = int(sample_rate_hz)
    low, high = (float(value) for value in analysis_band_hz)
    if not 0.0 < low < high < sample_rate / 2.0:
        raise ContractError("phase feasibility analysis band is invalid")
    order = int(config["bandpass_order"])
    hop = int(config["frame_hop_samples"])
    smooth = int(config["frequency_smoothing_frames"])
    polynomial = int(config["frequency_smoothing_polynomial_order"])
    quantile = float(config["active_envelope_quantile"])
    exponent = float(config["inspiral_coordinate_power"])
    if hop <= 0 or smooth <= polynomial or smooth % 2 != 1:
        raise ContractError("phase feasibility frame/smoothing contract is invalid")
    if not 0.0 <= quantile < 1.0:
        raise ContractError("active_envelope_quantile must lie in [0, 1)")

    sos = signal.butter(order, [low, high], btype="bandpass", fs=sample_rate, output="sos")
    filtered = signal.sosfiltfilt(sos, data)
    analytic = signal.hilbert(filtered)
    envelope = np.abs(analytic)
    unwrapped_phase = np.unwrap(np.angle(analytic))

    centers = np.arange(hop // 2, data.size - hop // 2, hop, dtype=np.int64)
    if centers.size <= smooth:
        raise ContractError("phase feasibility window has too few frames")
    phase_at_centers = unwrapped_phase[centers]
    delta_t = np.diff(centers).astype(np.float64) / sample_rate
    instantaneous_frequency = np.diff(phase_at_centers) / (2.0 * np.pi * delta_t)
    instantaneous_frequency = signal.savgol_filter(
        instantaneous_frequency, smooth, polynomial
    )
    time = (centers[1:] + centers[:-1]).astype(np.float64) / (2.0 * sample_rate)
    frame_weight = np.sqrt(envelope[centers[1:]] * envelope[centers[:-1]])
    active = frame_weight >= np.quantile(frame_weight, quantile)
    valid = (
        active
        & np.isfinite(instantaneous_frequency)
        & (instantaneous_frequency >= low)
        & (instantaneous_frequency <= high)
    )
    if int(np.sum(valid)) < max(5, polynomial + 2):
        raise ContractError("phase feasibility probe has insufficient valid frames")

    selected_time = time[valid]
    selected_frequency = instantaneous_frequency[valid]
    selected_weight = frame_weight[valid]
    rho = float(stats.spearmanr(selected_time, selected_frequency).statistic)
    if not np.isfinite(rho):
        rho = 0.0
    coordinate = np.power(selected_frequency, exponent)
    phase_for_fit = phase_at_centers[1:][valid]
    ordered = np.argsort(selected_time, kind="stable")
    frequency_steps = np.diff(selected_frequency[ordered])
    result = {
        "phase_frequency_time_spearman": rho,
        "phase_frequency_positive_step_fraction": float(
            np.mean(frequency_steps > 0.0) if frequency_steps.size else 0.0
        ),
        "phase_inspiral_coordinate_residual": _weighted_line_residual(
            selected_time, coordinate, selected_weight
        ),
        "phase_cubic_circular_residual": _weighted_cubic_phase_residual(
            selected_time, phase_for_fit, selected_weight
        ),
        "phase_valid_frame_fraction": float(np.mean(valid)),
        "phase_accumulation_cycles": float(
            (phase_for_fit[-1] - phase_for_fit[0]) / (2.0 * np.pi)
        ),
    }
    if not all(np.isfinite(value) for value in result.values()):
        raise ContractError("phase feasibility features are non-finite")
    return result
