"""Reconstruct published CBC injections for L4 cheap-feature evaluation."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import time
from typing import Callable

import numpy as np

from src.dante_light.contracts import ContractError, FailClosedReason
from src.dante_light.executor import DeferredWindow, WindowTask
from src.dante_light.prefilter import extract_excess_energy_features
from src.dante_light.preprocessing import PreparedPrefilterFeatures


RAW_FETCH_EDGE_TOLERANCE_S = 1.0 / 4096.0


def _sha(values: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()


def load_injection_trials(path: str | Path) -> dict[str, dict[str, str]]:
    trials: dict[str, dict[str, str]] = {}
    with Path(path).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            key = f"{row['system']}:{float(row['distance_mpc']):g}:{int(row['trial_index'])}"
            if key in trials:
                raise ContractError(f"duplicate published injection trial: {key}")
            trials[key] = row
    if not trials:
        raise ContractError("published injection trial table is empty")
    return trials


def prepare_injection_prefilter_features(
    task: WindowTask,
    *,
    trials: dict[str, dict[str, str]],
    feature_builder: Callable[[np.ndarray, int], object] | None = None,
) -> PreparedPrefilterFeatures:
    """Rebuild one raw-strain injection and verify its published SNR."""

    from src.core.data_loader import fetch_local_or_remote_strain
    from src.core.injection import InjectionEngine
    from src.core.preprocessor import extract_clean_subwindow, whiten_context
    from src.pipeline_v2_production.astrophysical_injection import (
        SAMPLE_RATE,
        SEGMENT_LENGTH,
        SYSTEMS,
        _project,
        _waveform,
    )

    source = task.payload
    key = (
        f"{source['morphology']}:{float(source['distance_mpc']):g}:"
        f"{int(source['trial_index'])}"
    )
    published = trials.get(key)
    if published is None:
        raise ContractError(f"published injection parameters are missing: {key}")
    detector = task.window.detector
    expected_snr = float(published[f"snr_{detector}"])
    systems = {system["name"]: system for system in SYSTEMS}
    system = systems.get(source["morphology"])
    if system is None:
        raise ContractError(f"unknown injection system: {source['morphology']}")
    gps = float(task.window.gps_start)
    began = time.perf_counter()
    hp, hc = _waveform(
        system["m1"],
        system["m2"],
        float(source["distance_mpc"]),
        float(source["inclination"]),
        system["f_low"],
    )
    projected, delay = _project(
        hp,
        hc,
        detector,
        float(source["ra"]),
        float(source["dec"]),
        float(source["psi"]),
        gps + SEGMENT_LENGTH / 2.0,
    )
    waveform_s = time.perf_counter() - began
    began = time.perf_counter()
    try:
        raw = fetch_local_or_remote_strain(
            detector,
            gps - 4.0,
            gps + SEGMENT_LENGTH + 4.0,
            # Whitening requires the full four-second context on both sides.
            # A multi-second lookup tolerance can accept a nearby local block
            # which does not actually cover the requested padded interval.
            edge_tolerance=RAW_FETCH_EDGE_TOLERANCE_S,
        )
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise DeferredWindow(FailClosedReason.DEPENDENCY_UNAVAILABLE) from exc
    data_read_s = time.perf_counter() - began
    raw_values = np.asarray(raw.value)
    if not np.all(np.isfinite(raw_values)):
        raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    raw_sha256 = _sha(raw_values)
    engine = InjectionEngine(sample_rate=SAMPLE_RATE)
    measured_snr = float(
        engine.compute_snr(raw.crop(gps, gps + SEGMENT_LENGTH), projected)
    )
    if not np.isclose(measured_snr, expected_snr, rtol=1e-9, atol=1e-9):
        raise ContractError(
            f"published injection SNR mismatch for {key}/{detector}: "
            f"{measured_snr} != {expected_snr}"
        )
    placement = (
        gps
        + SEGMENT_LENGTH / 2.0
        + float(delay)
        - (len(projected) / SAMPLE_RATE) / 2.0
    )
    injected = engine.inject(raw, projected, placement)
    injected_values = np.asarray(injected.value)
    if not np.all(np.isfinite(injected_values)):
        raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    began = time.perf_counter()
    whitened, padding = whiten_context(
        injected, gps, gps + SEGMENT_LENGTH, pad=4.0
    )
    clean = extract_clean_subwindow(
        whitened, gps, gps + SEGMENT_LENGTH
    )
    whitening_s = time.perf_counter() - began
    tolerance = 1.0 / float(clean.sample_rate.value)
    if (
        float(padding.get("effective_left", 0.0)) + tolerance < 4.0
        or float(padding.get("effective_right", 0.0)) + tolerance < 4.0
        or abs(float(clean.duration.value) - SEGMENT_LENGTH) > tolerance
    ):
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    began = time.perf_counter()
    if feature_builder is None:
        features = extract_excess_energy_features(
            np.asarray(clean.value), sample_rate_hz=SAMPLE_RATE
        )
    else:
        features = feature_builder(np.asarray(clean.value), int(SAMPLE_RATE))
    feature_s = time.perf_counter() - began
    return PreparedPrefilterFeatures(
        features=features,
        strain_sha256=_sha(injected_values),
        timings={
            "waveform_projection_s": waveform_s,
            "data_read_s": data_read_s,
            "whitening_s": whitening_s,
            "feature_extraction_s": feature_s,
        },
        metadata={
            "raw_strain_sha256": raw_sha256,
            "waveform_plus_sha256": _sha(hp),
            "waveform_cross_sha256": _sha(hc),
            "projected_waveform_sha256": _sha(projected),
            "expected_snr": expected_snr,
            "measured_snr": measured_snr,
            "geocentre_delay_s": float(delay),
            "placement_gps": float(placement),
        },
    )
