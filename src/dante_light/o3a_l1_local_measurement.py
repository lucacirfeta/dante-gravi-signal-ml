"""Offline, input-bound local PEM measurement and independent spectral replay.

The fixed reference-tail screen is exploratory, not a calibrated p-value.
No network reader, alternative channel set or outcome-dependent tuning exists.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import h5py
import numpy as np
from gwpy.timeseries import TimeSeries

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_l1_local_followup import local_coherence_max, reference_screen
from src.dante_light.o3a_o4a_common_pem_aux_samples import data_path


class UnavailableContext(Exception):
    """A numerically unavailable tested context, never a negative result."""


def sample_digest(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def half_open_indices(
    interval: list[float], rate: float, count: int
) -> tuple[int, int]:
    if (
        len(interval) != 2
        or not all(math.isfinite(v) for v in (*interval, rate))
        or not 0 <= interval[0] < interval[1]
        or rate <= 0
    ):
        raise ContractError("local relative interval invalid")
    first, last = (math.ceil(v * rate) for v in interval)
    if not 0 <= first < last <= count:
        raise ContractError("local sample interval outside full context")
    return first, last


def preprocess_context(
    strain: np.ndarray,
    auxiliary: dict[str, np.ndarray],
    *,
    strain_rate: int,
    auxiliary_rates: dict[str, int],
    channels: list[str],
    duration: int,
    target_rate: int,
    highpass_hz: float,
    interval: list[float],
) -> tuple[np.ndarray, dict[str, np.ndarray], dict]:
    """Historical strain-only filter/order, on individual complete contexts."""
    if set(auxiliary) != set(channels) or set(auxiliary_rates) != set(channels):
        raise ContractError("local exact channel identity changed")
    streams = {"strain": strain, **auxiliary}
    rates = {"strain": strain_rate, **auxiliary_rates}
    processed, raw_sha, full_sha = {}, {}, {}
    for name, raw in streams.items():
        values = np.asarray(raw)
        rate = rates[name]
        if rate < target_rate or values.shape != (duration * rate,):
            raise ContractError("native context sample geometry changed")
        if not np.isfinite(values).all():
            raise ContractError("verified native context contains nonfinite samples")
        raw_sha[name] = sample_digest(values)
        if np.var(values) == 0:
            raise UnavailableContext(f"CONSTANT_NATIVE_SERIES:{name}")
        series = TimeSeries(values, sample_rate=rate, t0=0, name=name)
        if name == "strain":
            series = series.highpass(highpass_hz)
        if rate != target_rate:
            series = series.resample(target_rate)
        aligned = np.asarray(series.value, dtype=np.float64)
        if aligned.shape != (duration * target_rate,):
            raise ContractError("resampled full context geometry changed")
        if not np.isfinite(aligned).all() or np.var(aligned) == 0:
            raise UnavailableContext(f"UNAVAILABLE_PREPROCESSED_SERIES:{name}")
        full_sha[name] = sample_digest(aligned)
        processed[name] = aligned
    first, last = half_open_indices(interval, target_rate, duration * target_rate)
    local = {name: values[first:last] for name, values in processed.items()}
    if any(np.var(values) == 0 for values in local.values()):
        raise UnavailableContext("CONSTANT_LOCAL_SERIES")
    provenance = {
        "native_samples_sha256": raw_sha,
        "full_preprocessed_samples_sha256": full_sha,
        "local_samples_sha256": {n: sample_digest(v) for n, v in local.items()},
        "half_open_sample_indices": [first, last],
        "selected_relative_interval_s": [first / target_rate, last / target_rate],
        "local_sample_count": last - first,
    }
    return local.pop("strain"), local, provenance


def independent_coherence(
    strain: np.ndarray,
    auxiliary: dict[str, np.ndarray],
    *,
    channels: list[str],
    band: list[float],
    measurement: dict,
) -> dict:
    """Direct FFT/cross-autospectrum implementation, not scipy.coherence/csd."""
    rate = measurement["sample_rate_hz"]
    width = int(rate * measurement["fftlength_s"])
    overlap = int(rate * measurement["overlap_s"])
    hop = width - overlap
    if (
        set(auxiliary) != set(channels)
        or len(set(channels)) != len(channels)
        or not channels
        or measurement["window"] != "hann_periodic"
        or measurement["detrend"] != "constant"
        or measurement["lag_s"] != 0
        or hop <= 0
        or not 0 < band[0] < band[1] < rate / 2
        or band[0] * measurement["fftlength_s"]
        < measurement["minimum_cycles_at_band_low"]
    ):
        raise ContractError("independent local spectral geometry invalid")
    x = np.asarray(strain, dtype=np.float64)
    starts = list(range(0, x.size - width + 1, hop))
    if len(starts) < measurement["minimum_welch_segments"]:
        raise ContractError("independent local Welch segments insufficient")
    # Analytic periodic Hann, independently of scipy.signal.get_window.
    window = (1 - np.cos(2 * np.pi * np.arange(width) / width)) / 2
    frequencies = np.arange(width // 2 + 1) * rate / width
    bins = np.flatnonzero((frequencies >= band[0]) & (frequencies <= band[1]))
    if not bins.size:
        raise ContractError("independent local band contains no spectral bins")

    def transform(values):
        values = np.asarray(values, dtype=np.float64)
        if values.shape != x.shape or not np.isfinite(values).all():
            raise ContractError("independent local stream shape/finite mismatch")
        segments = np.stack([values[start : start + width] for start in starts])
        return np.fft.rfft(
            (segments - segments.mean(axis=1, keepdims=True)) * window, axis=1
        )

    transformed_x = transform(x)
    power_x = np.mean(np.abs(transformed_x) ** 2, axis=0)
    details = {}
    for channel in channels:
        transformed_y = transform(auxiliary[channel])
        power_y = np.mean(np.abs(transformed_y) ** 2, axis=0)
        cross = np.mean(transformed_x.conj() * transformed_y, axis=0)
        denominator = power_x[bins] * power_y[bins]
        if np.any(denominator <= 0):
            raise UnavailableContext(f"ZERO_LOCAL_SPECTRAL_POWER:{channel}")
        values = np.abs(cross[bins]) ** 2 / denominator
        if not np.isfinite(values).all():
            raise UnavailableContext(f"NONFINITE_LOCAL_COHERENCE:{channel}")
        peak = int(np.argmax(values))
        details[channel] = {
            "maximum": float(values[peak]),
            "peak_frequency_hz": float(frequencies[bins[peak]]),
        }
    return {
        "maximum": max(v["maximum"] for v in details.values()),
        "channels": details,
        "frequency_bins_hz": frequencies[bins].tolist(),
        "welch_segments": len(starts),
    }


class NativeContextReader:
    """Slices only already verified local parent containers, never fetches.

    The caller must replay the complete parent before constructing this reader.
    Reopening it in the standalone verifier uses fresh file handles/memmaps.
    """

    def __init__(self, root: Path, plan: dict, channels: list[str]):
        self.root, self.plan, self.channels = root, plan, channels
        self.arrays: dict[tuple[str, str], np.ndarray] = {}

    def read(self, start: int, duration: int, role: str):
        end = start + duration
        spans = [
            s
            for s in self.plan["spans"]
            if s["role"] == role
            and s["interval_gps"][0] <= start
            and end <= s["interval_gps"][1]
            and s["detector"] == "L1"
        ]
        if len(spans) != 1:
            raise ContractError("native context not in one frozen parent span")
        source = self.plan["strain_source"]
        rate = source["sample_rate_hz"]
        pieces, cursor = [], start
        for frame in sorted(self.plan["frames"], key=lambda f: f["gps_start"]):
            frame_start = frame["gps_start"]
            frame_end = frame_start + source["frame_duration_s"]
            if frame_end <= cursor or frame_start >= end:
                continue
            if frame_start > cursor:
                raise ContractError("native strain frame gap")
            last = min(end, frame_end)
            path = self.root / "frame_acquisition" / "frames" / frame["filename"]
            with h5py.File(path, "r") as handle:
                dataset = handle["strain/Strain"]
                if (
                    dataset.dtype != np.dtype("float64")
                    or float(dataset.attrs["Xstart"]) != frame_start
                    or float(dataset.attrs["Xspacing"]) != 1 / rate
                ):
                    raise ContractError("native strain geometry changed after replay")
                pieces.append(
                    dataset[(cursor - frame_start) * rate : (last - frame_start) * rate]
                )
            cursor = last
            if cursor == end:
                break
        if cursor != end:
            raise ContractError("native strain context incomplete")
        strain = np.concatenate(pieces)
        specs = (
            self.plan["event_auxiliary_specs"]
            if role == "event"
            else self.plan["auxiliary_series"]
        )
        aux_root = (
            Path(self.plan["event_auxiliary_parent_root"])
            if role == "event"
            else self.root / "auxiliary"
        )
        auxiliary, rates = {}, {}
        for channel in self.channels:
            matching = [
                s
                for s in specs
                if s["channel"] == channel
                and s["detector"] == "L1"
                and s["run"] == "O3a"
                and s["interval_gps"][0] <= start
                and end <= s["interval_gps"][1]
            ]
            if len(matching) != 1:
                raise ContractError(
                    "native auxiliary context identity/coverage changed"
                )
            spec = matching[0]
            key = (str(aux_root), spec["key"])
            if key not in self.arrays:
                self.arrays[key] = np.load(
                    data_path(aux_root, spec), mmap_mode="r", allow_pickle=False
                )
            array = self.arrays[key]
            if array.dtype != np.dtype("float32") or array.shape != (
                spec["sample_count"],
            ):
                raise ContractError("native auxiliary dtype/shape changed after replay")
            aux_rate = spec["sample_rate_hz"]
            offset = (start - spec["interval_gps"][0]) * aux_rate
            auxiliary[channel] = np.array(array[offset : offset + duration * aux_rate])
            rates[channel] = aux_rate
        return strain, auxiliary, rate, rates


def measure_context(
    reader, start: int, role: str, plan: dict, *, independent: bool
) -> dict:
    design, target = plan["method"], plan["target_region"]
    duration = design["controls"]["context_duration_s"]
    identity = {"gps_start": start, "duration_s": duration, "role": role}
    try:
        strain, auxiliary, strain_rate, rates = reader.read(start, duration, role)
        x, aux, provenance = preprocess_context(
            strain,
            auxiliary,
            strain_rate=strain_rate,
            auxiliary_rates=rates,
            channels=plan["channels"],
            duration=duration,
            target_rate=design["measurement"]["sample_rate_hz"],
            highpass_hz=plan["strain_highpass_hz"],
            interval=target["local_offset_interval_s"],
        )
        # The production statistic is the unchanged Gate B kernel.
        try:
            value = local_coherence_max(
                x,
                aux,
                channels=plan["channels"],
                band=target["frequency_band_hz"],
                measurement=design["measurement"],
            )
        except ContractError as exc:
            # Geometry/identity failures still stop. A valid region without
            # finite spectral power is unavailable, not a negative screen.
            if str(exc) == "local coherence spectral bins unavailable":
                raise UnavailableContext("UNAVAILABLE_LOCAL_SPECTRAL_POWER") from exc
            raise
        if independent:
            replay = independent_coherence(
                x,
                aux,
                channels=plan["channels"],
                band=target["frequency_band_hz"],
                measurement=design["measurement"],
            )
            validation = plan["execution_contract"]["validation"]
            if not np.isclose(
                value,
                replay["maximum"],
                atol=validation["numerical_comparison_atol"],
                rtol=validation["numerical_comparison_rtol"],
            ):
                raise ContractError("independent FFT versus Welch maximum mismatch")
        return {
            **identity,
            "status": "MEASURED",
            "value": value,
            "provenance": provenance,
        }
    except UnavailableContext as exc:
        return {**identity, "status": "UNAVAILABLE", "reason": str(exc)}


def block_record(contexts: list[dict], starts: list[int], design: dict) -> dict:
    if (
        [c["gps_start"] for c in contexts] != starts
        or len(starts) != design["controls"]["contexts_per_block"]
        or any(c["role"] != "background" for c in contexts)
        or any(
            c["duration_s"] != design["controls"]["context_duration_s"]
            for c in contexts
        )
        or any(
            b - a != design["controls"]["context_duration_s"]
            for a, b in zip(starts, starts[1:])
        )
    ):
        raise ContractError("local whole-block context accounting changed")
    record = {"context_starts_gps": starts, "contexts": contexts}
    if any(c["status"] != "MEASURED" for c in contexts):
        return {**record, "status": "EXCLUDED_INCOMPLETE_BLOCK"}
    return {**record, "status": "MEASURED", "value": max(c["value"] for c in contexts)}


def decision_and_bootstrap(
    event: dict, blocks: list[dict], design: dict, *, independent: bool
) -> dict:
    if event["status"] != "MEASURED":
        return {"status": "INCONCLUSIVE", "reason": "EVENT_NUMERICALLY_UNAVAILABLE"}
    values = np.asarray([b["value"] for b in blocks if b["status"] == "MEASURED"])
    if (
        not np.isfinite(event["value"])
        or not 0 <= event["value"] <= 1
        or not np.isfinite(values).all()
        or np.any((values < 0) | (values > 1))
    ):
        raise ContractError("local reference numeric range invalid")
    if independent:
        if values.size < design["controls"]["minimum_reference_blocks"]:
            decision = {"status": "INCONCLUSIVE", "reason": "REFERENCE_TAIL_UNRESOLVED"}
        else:
            count = sum(v >= event["value"] for v in values.tolist())
            score = min(
                1.0,
                design["decision"]["family_target_count"]
                * (1 + count)
                / (1 + len(values)),
            )
            decision = {
                "status": design["decision"]["screen_positive"]
                if score <= design["decision"]["screen_cutoff"]
                else design["decision"]["screen_negative"],
                "corrected_reference_tail_fraction": score,
            }
    else:
        decision = reference_screen(event["value"], values, design)
    if decision["status"] == "INCONCLUSIVE":
        return decision
    rng = np.random.Generator(np.random.PCG64(design["controls"]["bootstrap_seed"]))
    counts = []
    for _ in range(design["controls"]["bootstrap_resamples"]):
        indices = rng.integers(0, len(values), size=len(values))
        resampled = values[indices]
        counts.append(
            sum(v >= event["value"] for v in resampled.tolist())
            if independent
            else int(np.count_nonzero(resampled >= event["value"]))
        )
    return {
        **decision,
        "reference_block_count": len(values),
        "exceedance_count": int(np.count_nonzero(values >= event["value"])),
        "bootstrap_exceedance_counts": counts,
        "bootstrap_role": design["controls"]["bootstrap_role"],
        "bootstrap_unit": design["controls"]["bootstrap_unit"],
        "bootstrap_is_additional_reference_data": False,
    }
