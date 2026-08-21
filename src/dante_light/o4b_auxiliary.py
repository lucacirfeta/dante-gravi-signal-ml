"""Public O4b auxiliary-data diagnostics for frozen DANTE-Light candidates.

This module deliberately does not implement a veto.  The public O4 auxiliary
inventory mixes environmental monitors with calibration, control and data-
quality channels whose astrophysical safety is not established by their
publication.  The only allowed endpoint is therefore a descriptive,
empirically calibrated ``AUXILIARY_EXCESS`` diagnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Callable, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256


SCHEMA_VERSION = 1
WINDOW_S = 32.0
FFTLENGTH_S = 2.0
OVERLAP_S = 1.0
F_LOW_HZ = 20.0
F_HIGH_HZ = 500.0


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_channel_policy(path: str | Path) -> dict:
    """Load and strictly validate the frozen public O4 channel policy."""

    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported O4 auxiliary policy schema")
    if policy.get("run") != "O4b":
        raise ContractError("O4 auxiliary policy is not frozen for O4b")
    if policy.get("scientific_policy", {}).get("status") != "DIAGNOSTIC_ONLY":
        raise ContractError("public O4 auxiliary channels must remain diagnostic-only")
    channels = policy.get("channels")
    if not isinstance(channels, dict) or set(channels) != {"H1", "L1"}:
        raise ContractError("O4 auxiliary policy must contain H1 and L1")
    expected_counts = {"H1": 14, "L1": 11}
    for detector, entries in channels.items():
        if len(entries) != expected_counts[detector]:
            raise ContractError(f"unexpected {detector} public-channel count")
        names = [entry.get("name") for entry in entries]
        if len(names) != len(set(names)):
            raise ContractError(f"duplicate {detector} auxiliary channel")
        for entry in entries:
            if not str(entry.get("name", "")).startswith(f"{detector}:"):
                raise ContractError("auxiliary channel detector mismatch")
            rate = entry.get("sample_rate_hz")
            if not isinstance(rate, int) or rate <= 0:
                raise ContractError("invalid auxiliary sample rate")
            if entry.get("role") not in {
                "environmental_monitor",
                "control_or_subtraction",
                "calibration_injection",
                "dq_state_below_band",
            }:
                raise ContractError("invalid auxiliary channel role")
            if rate < 2 * F_LOW_HZ and entry.get("analyze") is not False:
                raise ContractError("below-band channel cannot enter spectral test")
    return policy


@dataclass(frozen=True, slots=True)
class AuxiliarySeriesKey:
    detector: str
    channel: str
    gps_start: int
    gps_end: int
    native_sample_rate_hz: float
    stored_sample_rate_hz: float
    source: str = "nds.gwosc.org"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError("unsupported O4 auxiliary cache schema")
        detector = self.detector.upper()
        if detector not in {"H1", "L1"} or not self.channel.startswith(
            f"{detector}:"
        ):
            raise ContractError("auxiliary cache detector/channel mismatch")
        if self.gps_end <= self.gps_start:
            raise ContractError("invalid auxiliary cache interval")
        for value in (self.native_sample_rate_hz, self.stored_sample_rate_hz):
            if not math.isfinite(value) or value <= 0:
                raise ContractError("invalid auxiliary cache sample rate")
        if self.stored_sample_rate_hz > self.native_sample_rate_hz:
            raise ContractError("auxiliary cache must not upsample")
        if not self.source:
            raise ContractError("auxiliary cache source is required")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "detector": self.detector.upper(),
            "channel": self.channel,
            "gps_start": int(self.gps_start),
            "gps_end": int(self.gps_end),
            "native_sample_rate_hz": float(self.native_sample_rate_hz),
            "stored_sample_rate_hz": float(self.stored_sample_rate_hz),
            "source": self.source,
        }

    @property
    def cache_id(self) -> str:
        return f"o4aux1-{canonical_json_sha256(self.to_dict())[:32]}"


class AuxiliarySeriesCache:
    """Atomic, content-addressed float32 cache for public auxiliary blocks."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: AuxiliarySeriesKey) -> tuple[Path, Path]:
        return self.root / f"{key.cache_id}.npy", self.root / f"{key.cache_id}.json"

    @staticmethod
    def _validate(key: AuxiliarySeriesKey, values: np.ndarray) -> np.ndarray:
        array = np.ascontiguousarray(values, dtype=np.float32)
        expected = int(round((key.gps_end - key.gps_start) * key.stored_sample_rate_hz))
        if array.ndim != 1 or array.size != expected:
            raise ContractError(
                f"auxiliary series length {array.size} does not match {expected}"
            )
        if not np.isfinite(array).all():
            raise ContractError("auxiliary series contains non-finite values")
        if float(array.std(dtype=np.float64)) == 0.0:
            raise ContractError("auxiliary series is constant")
        return array

    def load(self, key: AuxiliarySeriesKey) -> tuple[np.ndarray, dict] | None:
        data_path, metadata_path = self._paths(key)
        if not data_path.is_file() or not metadata_path.is_file():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("key") != key.to_dict():
            raise ContractError("auxiliary cache key mismatch")
        if sha256_file(data_path) != metadata.get("npy_sha256"):
            raise ContractError("auxiliary cache file SHA256 mismatch")
        values = self._validate(key, np.load(data_path, allow_pickle=False))
        if hashlib.sha256(values.tobytes()).hexdigest() != metadata.get(
            "values_sha256"
        ):
            raise ContractError("auxiliary cached values SHA256 mismatch")
        return values, metadata

    def get_or_fetch(
        self,
        key: AuxiliarySeriesKey,
        fetch: Callable[[AuxiliarySeriesKey], np.ndarray],
    ) -> tuple[np.ndarray, dict, bool]:
        cached = self.load(key)
        if cached is not None:
            values, metadata = cached
            return values, metadata, True
        values = self._validate(key, fetch(key))
        data_path, metadata_path = self._paths(key)
        tmp_data = data_path.with_suffix(".npy.tmp")
        tmp_metadata = metadata_path.with_suffix(".json.tmp")
        with tmp_data.open("wb") as handle:
            np.save(handle, values, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "cache_id": key.cache_id,
            "key": key.to_dict(),
            "values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
            "npy_sha256": sha256_file(tmp_data),
        }
        with tmp_metadata.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_data, data_path)
        os.replace(tmp_metadata, metadata_path)
        return values, metadata, False


def _segment_ffts(
    values: np.ndarray,
    sample_rate_hz: float,
    *,
    f_low_hz: float = F_LOW_HZ,
    f_high_hz: float = F_HIGH_HZ,
) -> tuple[np.ndarray, np.ndarray]:
    """Return normalized Hann-window FFTs for one 32 s series."""

    data = np.asarray(values, dtype=np.float64)
    expected = int(round(WINDOW_S * sample_rate_hz))
    if data.ndim != 1 or data.size != expected:
        raise ContractError(f"coherence input must contain exactly {expected} samples")
    if not np.isfinite(data).all() or float(data.std()) == 0.0:
        raise ContractError("coherence input is non-finite or constant")
    data = (data - data.mean()) / data.std()
    nfft = int(round(FFTLENGTH_S * sample_rate_hz))
    hop = int(round((FFTLENGTH_S - OVERLAP_S) * sample_rate_hz))
    n_segments = 1 + (data.size - nfft) // hop
    if n_segments < 2:
        raise ContractError("insufficient Welch segments")
    window = np.hanning(nfft)
    freqs = np.fft.rfftfreq(nfft, d=1.0 / sample_rate_hz)
    upper = min(f_high_hz, 0.9 * sample_rate_hz / 2.0)
    mask = (freqs >= f_low_hz) & (freqs <= upper)
    if not mask.any():
        raise ContractError("channel Nyquist frequency does not reach analysis band")
    result = np.empty((n_segments, int(mask.sum())), dtype=np.complex128)
    for index in range(n_segments):
        start = index * hop
        result[index] = np.fft.rfft(data[start : start + nfft] * window)[mask]
    return result, freqs[mask]


def max_coherence(
    strain: np.ndarray,
    auxiliary: np.ndarray,
    sample_rate_hz: float,
) -> dict:
    """Maximum Welch coherence in the frozen band for one aligned window."""

    x, frequencies = _segment_ffts(strain, sample_rate_hz)
    y, aux_frequencies = _segment_ffts(auxiliary, sample_rate_hz)
    if not np.array_equal(frequencies, aux_frequencies):
        raise ContractError("strain and auxiliary frequency grids differ")
    numerator = np.abs(np.sum(x * np.conj(y), axis=0)) ** 2
    denominator = np.sum(np.abs(x) ** 2, axis=0) * np.sum(
        np.abs(y) ** 2, axis=0
    )
    coherence = np.divide(
        numerator,
        denominator,
        out=np.zeros_like(numerator, dtype=np.float64),
        where=denominator > 0,
    )
    peak = int(np.argmax(coherence))
    return {
        "max_coherence": float(coherence[peak]),
        "peak_frequency_hz": float(frequencies[peak]),
        "effective_band_hz": [float(frequencies[0]), float(frequencies[-1])],
        "n_welch_segments": int(x.shape[0]),
    }


def _fft_batch(windows: np.ndarray, sample_rate_hz: float) -> np.ndarray:
    values = np.asarray(windows)
    if values.ndim != 2:
        raise ContractError("background windows must form a two-dimensional array")
    return np.stack([_segment_ffts(row, sample_rate_hz)[0] for row in values])


def calibrate_familywise_null(
    channel_windows: Mapping[str, tuple[np.ndarray, np.ndarray, float]],
    *,
    alpha: float = 0.01,
    n_bootstrap: int = 200,
    seed: int = 42,
) -> dict:
    """Calibrate max-over-channel coherence using paired quiet windows.

    Each mapping value is ``(strain_windows, auxiliary_windows, sample_rate)``.
    Rows are aligned zero-lag windows.  Off-diagonal pairs define the time-
    shift null; the diagonal defines the quiet zero-lag control.  Bootstrap
    resampling is over window identities, never over dependent pairs.
    """

    if not channel_windows:
        raise ContractError("family-wise null requires at least one channel")
    cmax_by_channel: list[np.ndarray] = []
    per_channel: dict[str, dict] = {}
    n_windows: int | None = None
    for channel, (strain_windows, auxiliary_windows, sample_rate_hz) in sorted(
        channel_windows.items()
    ):
        strain_windows = np.asarray(strain_windows)
        auxiliary_windows = np.asarray(auxiliary_windows)
        if strain_windows.shape != auxiliary_windows.shape:
            raise ContractError("strain/auxiliary background shapes differ")
        if n_windows is None:
            n_windows = int(strain_windows.shape[0])
        elif strain_windows.shape[0] != n_windows:
            raise ContractError("all channels must use identical window identities")
        if n_windows < 30:
            raise ContractError("at least 30 quiet windows are required")
        x = _fft_batch(strain_windows, sample_rate_hz)
        y = _fft_batch(auxiliary_windows, sample_rate_hz)
        px = np.sum(np.abs(x) ** 2, axis=1)
        py = np.sum(np.abs(y) ** 2, axis=1)
        cross = np.einsum("ikf,jkf->ijf", x, np.conj(y), optimize=True)
        denominator = px[:, None, :] * py[None, :, :]
        coherence = np.divide(
            np.abs(cross) ** 2,
            denominator,
            out=np.zeros_like(denominator, dtype=np.float64),
            where=denominator > 0,
        )
        channel_cmax = coherence.max(axis=2)
        cmax_by_channel.append(channel_cmax)
        off_diagonal = ~np.eye(n_windows, dtype=bool)
        per_channel[channel] = {
            "time_shift_q99": float(
                np.quantile(channel_cmax[off_diagonal], 1.0 - alpha)
            ),
            "zero_lag_q99": float(
                np.quantile(np.diag(channel_cmax), 1.0 - alpha)
            ),
            "zero_lag_median": float(np.median(np.diag(channel_cmax))),
        }
        del x, y, cross, coherence

    assert n_windows is not None
    familywise = np.max(np.stack(cmax_by_channel), axis=0)
    valid = ~np.eye(n_windows, dtype=bool)
    shifted = familywise[valid]
    zero_lag = np.diag(familywise)
    shifted_threshold = float(np.quantile(shifted, 1.0 - alpha))
    zero_lag_threshold = float(np.quantile(zero_lag, 1.0 - alpha))

    rng = np.random.default_rng(seed)
    shifted_bootstrap = np.empty(n_bootstrap, dtype=float)
    zero_lag_bootstrap = np.empty(n_bootstrap, dtype=float)
    for index in range(n_bootstrap):
        selected = rng.integers(0, n_windows, size=n_windows)
        if np.unique(selected).size < 2:
            raise ContractError("degenerate window-level bootstrap sample")
        sub = familywise[np.ix_(selected, selected)]
        sub_valid = selected[:, None] != selected[None, :]
        shifted_bootstrap[index] = np.quantile(
            sub[sub_valid], 1.0 - alpha
        )
        zero_lag_bootstrap[index] = np.quantile(
            familywise[selected, selected], 1.0 - alpha
        )

    return {
        "alpha_familywise": float(alpha),
        "n_channels": len(channel_windows),
        "n_windows": n_windows,
        "n_time_shift_pairs": int(valid.sum()),
        "time_shift_threshold": shifted_threshold,
        "time_shift_threshold_ci95": [
            float(np.quantile(shifted_bootstrap, 0.025)),
            float(np.quantile(shifted_bootstrap, 0.975)),
        ],
        "zero_lag_threshold": zero_lag_threshold,
        "zero_lag_threshold_ci95": [
            float(np.quantile(zero_lag_bootstrap, 0.025)),
            float(np.quantile(zero_lag_bootstrap, 0.975)),
        ],
        "zero_lag_fraction_above_time_shift_threshold": float(
            np.mean(zero_lag > shifted_threshold)
        ),
        "per_channel": per_channel,
        "method": (
            "max over channels and frequency; off-diagonal 32 s quiet-window "
            "pairs define the time-shift null; aligned diagonal windows define "
            "the quiet zero-lag null; bootstrap resamples window identities"
        ),
    }


def diagnostic_verdict(
    observed_by_channel: Mapping[str, float],
    time_shift_threshold: float,
    zero_lag_threshold: float,
) -> str:
    """Return a diagnostic endpoint; never a veto or physical-origin label."""

    if not observed_by_channel:
        return "AUXILIARY_UNAVAILABLE"
    if not math.isfinite(time_shift_threshold) or not math.isfinite(
        zero_lag_threshold
    ):
        return "AUXILIARY_UNAVAILABLE"
    values = np.asarray(list(observed_by_channel.values()), dtype=float)
    if not np.isfinite(values).all():
        return "AUXILIARY_UNAVAILABLE"
    maximum = float(values.max())
    if maximum > time_shift_threshold and maximum > zero_lag_threshold:
        return "AUXILIARY_EXCESS"
    if maximum > time_shift_threshold:
        return "PERSISTENT_BASELINE_COMPATIBLE"
    return "NO_AUXILIARY_EXCESS"
