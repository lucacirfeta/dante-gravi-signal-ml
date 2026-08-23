"""Array-only helpers for a feasibility mini-bank study.

Waveform generation remains in the executable script so importing this module
does not require LALSuite.  No minimal-match gate is defined here.
"""

from __future__ import annotations

from collections.abc import Sequence
import time

import numpy as np
from scipy import fft

from src.dante_light.contracts import ContractError


def phase_maximized_noise_weighted_match(
    first: np.ndarray,
    second: np.ndarray,
    psd: np.ndarray,
    *,
    delta_f_hz: float,
    n_time_samples: int,
) -> float:
    """Return a time- and phase-maximized one-sided noise-weighted match."""

    left = np.asarray(first, dtype=np.complex128)
    right = np.asarray(second, dtype=np.complex128)
    noise = np.asarray(psd, dtype=np.float64)
    expected = n_time_samples // 2 + 1
    if left.shape != right.shape or left.shape != noise.shape or left.size != expected:
        raise ContractError("waveforms and PSD do not match the requested FFT length")
    valid = (
        np.isfinite(noise)
        & (noise > 0.0)
        & np.isfinite(left.real)
        & np.isfinite(left.imag)
        & np.isfinite(right.real)
        & np.isfinite(right.imag)
    )
    if not np.any(valid):
        raise ContractError("noise-weighted match has no valid frequency bins")
    weighted = np.zeros_like(left)
    weighted[valid] = left[valid] * np.conj(right[valid]) / noise[valid]
    full = np.zeros(int(n_time_samples), dtype=np.complex128)
    full[: left.size] = weighted
    correlation = fft.ifft(full, workers=1) * n_time_samples * 4.0 * delta_f_hz
    norm_left = np.sqrt(
        4.0 * delta_f_hz * np.sum(np.abs(left[valid]) ** 2 / noise[valid])
    )
    norm_right = np.sqrt(
        4.0 * delta_f_hz * np.sum(np.abs(right[valid]) ** 2 / noise[valid])
    )
    if norm_left <= 0.0 or norm_right <= 0.0:
        raise ContractError("noise-weighted waveform norm is zero")
    value = float(np.max(np.abs(correlation)) / (norm_left * norm_right))
    return float(np.clip(value, 0.0, 1.0))


def greedy_farthest_bank(
    match_matrix: np.ndarray,
    *,
    bank_sizes: Sequence[int],
    anchor_index: int,
) -> dict[str, object]:
    """Build a deterministic farthest-first coverage curve."""

    matrix = np.asarray(match_matrix, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1] or matrix.size == 0:
        raise ContractError("match matrix must be non-empty and square")
    if not np.all(np.isfinite(matrix)) or not np.allclose(matrix, matrix.T, atol=1e-10):
        raise ContractError("match matrix must be finite and symmetric")
    count = matrix.shape[0]
    if not 0 <= int(anchor_index) < count:
        raise ContractError("anchor_index is outside the match matrix")
    sizes = sorted({int(value) for value in bank_sizes})
    if not sizes or sizes[0] < 1 or sizes[-1] > count:
        raise ContractError("bank sizes must lie within the target grid")

    selected = [int(anchor_index)]
    best = matrix[:, int(anchor_index)].copy()
    snapshots: dict[str, object] = {}
    for size in range(1, sizes[-1] + 1):
        if size in sizes:
            snapshots[str(size)] = {
                "selected_indices": list(selected),
                "minimum_match": float(np.min(best)),
                "p05_match": float(np.quantile(best, 0.05)),
                "median_match": float(np.median(best)),
                "mean_match": float(np.mean(best)),
            }
        if size == sizes[-1]:
            break
        unselected = np.ones(count, dtype=bool)
        unselected[selected] = False
        candidates = np.flatnonzero(unselected)
        next_index = int(candidates[np.argmin(best[candidates])])
        selected.append(next_index)
        best = np.maximum(best, matrix[:, next_index])
    return {"selection_method": "deterministic_farthest_first", "curve": snapshots}


def benchmark_complex_filter_kernel(
    *,
    n_time_samples: int,
    bank_sizes: Sequence[int],
    repetitions: int,
    warmup: int,
    seed: int,
) -> dict[str, object]:
    """Benchmark the complex-IFFT kernel required for phase maximization."""

    if repetitions <= 0 or warmup < 0:
        raise ContractError("kernel benchmark repetition counts are invalid")
    rng = np.random.default_rng(seed)
    frequency_count = n_time_samples // 2 + 1
    data = rng.standard_normal(frequency_count) + 1j * rng.standard_normal(
        frequency_count
    )
    maximum = max(int(value) for value in bank_sizes)
    templates = rng.standard_normal((maximum, frequency_count)) + 1j * rng.standard_normal(
        (maximum, frequency_count)
    )
    full = np.zeros(n_time_samples, dtype=np.complex128)

    def run(size: int) -> None:
        for index in range(size):
            full.fill(0.0)
            full[:frequency_count] = data * templates[index]
            fft.ifft(full, workers=1)

    result: dict[str, object] = {}
    for raw_size in bank_sizes:
        size = int(raw_size)
        for _ in range(warmup):
            run(size)
        samples = []
        for _ in range(repetitions):
            began = time.perf_counter()
            run(size)
            samples.append(time.perf_counter() - began)
        values = np.asarray(samples, dtype=np.float64)
        result[str(size)] = {
            "median_s": float(np.median(values)),
            "p95_s": float(np.quantile(values, 0.95)),
            "maximum_s": float(np.max(values)),
        }
    return {
        "semantics": (
            "CPU complex-IFFT kernel with precomputed data FFT and templates; "
            "excludes PSD estimation, waveform generation, normalization, and I/O"
        ),
        "results": result,
    }
