#!/usr/bin/env python3
"""Run a public O4b auxiliary-coherence pilot on frozen escalations.

The output is diagnostic-only.  It cannot veto, confirm, or establish an
instrumental origin for a candidate.
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4b_auxiliary import (
    AuxiliarySeriesCache,
    AuxiliarySeriesKey,
    calibrate_familywise_null,
    diagnostic_verdict,
    load_channel_policy,
    max_coherence,
    sha256_file,
)


DEFAULT_MANIFEST = Path("artifacts/dante_light/o4b_followup/manifest_v1.json")
DEFAULT_POLICY = Path("config/dante_light_o4b_aux_channels_v1.json")
DEFAULT_OUTPUT = Path("artifacts/dante_light/o4b_auxiliary/pilot_v1.json")
MAX_CALIBRATION_DISTANCE_S = 12 * 3600


def _source_sha256(path: str | Path) -> str:
    normalized = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def _dependency_versions() -> dict[str, str]:
    result = {}
    for package in (
        "numpy",
        "scipy",
        "gwpy",
        "gwosc",
        "gwdatafind",
    ):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "NOT_INSTALLED"
    try:
        import nds2

        result["python-nds2-client"] = str(nds2.__version__)
    except (ImportError, AttributeError):
        result["python-nds2-client"] = "NOT_INSTALLED"
    return result


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _candidate(manifest: dict, detector: str, gps: int | None) -> dict:
    options = [
        row
        for row in manifest["candidates"]
        if row["detector"].upper() == detector.upper()
    ]
    if gps is not None:
        options = [row for row in options if int(row["gps_start"]) == gps]
    if len(options) != 1 and gps is not None:
        raise RuntimeError("detector/GPS does not select exactly one frozen candidate")
    if not options:
        raise RuntimeError("no frozen candidate matches the requested detector")
    return options[0]


def _pick_background(
    detector: str,
    event_gps: int,
    block_seconds: int,
    excluded_gps: list[float],
) -> tuple[int, int, np.ndarray]:
    from gwosc.timeline import get_segments

    segments = get_segments(
        f"{detector}_BURST_CAT1", event_gps - 7 * 86400, event_gps + 7 * 86400
    )
    best: tuple[float, int, int, np.ndarray] | None = None
    for seg_start, seg_end in segments:
        first = int(np.ceil(float(seg_start)))
        last = int(np.floor(float(seg_end)))
        if last - first < block_seconds:
            continue
        starts = {
            first,
            last - block_seconds,
            min(max(event_gps - block_seconds // 2, first), last - block_seconds),
        }
        for start in starts:
            end = start + block_seconds
            windows = np.arange(start, end - 32 + 1, 96, dtype=np.int64)
            centers = windows.astype(float) + 16.0
            keep = np.ones(len(windows), dtype=bool)
            for excluded in excluded_gps:
                keep &= np.abs(centers - (float(excluded) + 16.0)) > 112.0
            clean = windows[keep]
            if len(clean) < 30:
                continue
            distance = abs((start + end) / 2.0 - event_gps)
            if best is None or distance < best[0]:
                best = (distance, start, end, clean)
    if best is None:
        raise RuntimeError("no CAT1 block with at least 30 candidate-excluded windows")
    return best[1], best[2], best[3]


def _fetch_cached_series(
    cache: AuxiliarySeriesCache,
    key: AuxiliarySeriesKey,
    *,
    open_strain: bool,
) -> tuple[np.ndarray, dict, bool]:
    from gwpy.timeseries import TimeSeries

    def fetch(request: AuxiliarySeriesKey) -> np.ndarray:
        if open_strain:
            series = TimeSeries.fetch_open_data(
                request.detector,
                request.gps_start,
                request.gps_end,
                sample_rate=int(request.native_sample_rate_hz),
                cache=True,
            )
        else:
            series = TimeSeries.fetch(
                request.channel,
                request.gps_start,
                request.gps_end,
                host=request.source,
            )
        actual_rate = float(series.sample_rate.value)
        if actual_rate != request.native_sample_rate_hz:
            raise RuntimeError(
                f"{request.channel} native rate {actual_rate} != frozen "
                f"{request.native_sample_rate_hz}"
            )
        if actual_rate > request.stored_sample_rate_hz:
            series = series.resample(request.stored_sample_rate_hz)
        if float(series.sample_rate.value) != request.stored_sample_rate_hz:
            raise RuntimeError("stored auxiliary rate does not match request")
        return series.value

    return cache.get_or_fetch(key, fetch)


def _windows(values: np.ndarray, block_start: int, starts: np.ndarray, fs: float) -> np.ndarray:
    length = int(round(32 * fs))
    rows = []
    for start in starts:
        offset = int(round((int(start) - block_start) * fs))
        row = values[offset : offset + length]
        if len(row) != length:
            raise RuntimeError("background crop does not contain a full window")
        rows.append(row)
    return np.stack(rows)


def _distance_to_span(event_start: int, event_end: int, span_start: int, span_end: int) -> int:
    if event_end < span_start:
        return span_start - event_end
    if event_start > span_end:
        return event_start - span_end
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detector", choices=("H1", "L1"), default="H1")
    parser.add_argument("--gps", type=int)
    parser.add_argument("--block-seconds", type=int, default=4096)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--calibration-from",
        type=Path,
        help="reuse a verified same-detector/role calibration for this event",
    )
    parser.add_argument(
        "--roles",
        nargs="+",
        default=["environmental_monitor"],
        choices=("environmental_monitor", "control_or_subtraction", "calibration_injection"),
    )
    args = parser.parse_args()
    if args.block_seconds < 4096:
        raise RuntimeError("pilot block must be at least 4096 s")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    policy = load_channel_policy(args.policy)
    event = _candidate(manifest, args.detector, args.gps)
    event_gps = int(event["gps_start"])
    selected = [
        entry
        for entry in policy["channels"][args.detector]
        if entry["analyze"] and entry["role"] in set(args.roles)
    ]
    if not selected:
        raise RuntimeError("channel-role selection is empty")

    all_gps = [
        float(row["gps_start"])
        for row in manifest["candidates"]
        if row["detector"] == args.detector
    ]
    cache = AuxiliarySeriesCache(args.cache_dir)
    stored_rate = 2048.0
    calibration_source = None
    if args.calibration_from is not None:
        source_payload = json.loads(args.calibration_from.read_text(encoding="utf-8"))
        if source_payload.get("status") != "PASS":
            raise RuntimeError("calibration source is not PASS")
        if source_payload.get("scientific_status") != "DIAGNOSTIC_ONLY":
            raise RuntimeError("calibration source violates diagnostic-only policy")
        if source_payload["candidate"]["detector"] != args.detector:
            raise RuntimeError("calibration source detector mismatch")
        if source_payload["channels"] != [entry["name"] for entry in selected]:
            raise RuntimeError("calibration source channel set mismatch")
        if source_payload["channel_roles"] != args.roles:
            raise RuntimeError("calibration source role set mismatch")
        source_provenance = source_payload["provenance"]
        if source_provenance["manifest_sha256"] != sha256_file(args.manifest):
            raise RuntimeError("calibration source manifest mismatch")
        if source_provenance["policy_sha256"] != sha256_file(args.policy):
            raise RuntimeError("calibration source policy mismatch")
        background = source_payload["background"]
        block_start, block_end = map(int, background["span"])
        calibration_distance = _distance_to_span(
            event_gps, event_gps + 32, block_start, block_end
        )
        if calibration_distance > MAX_CALIBRATION_DISTANCE_S:
            raise RuntimeError("event is more than 12 h from calibration epoch")
        window_starts = np.asarray(background["window_starts"], dtype=np.int64)
        calibration = source_payload["calibration"]
        calibration_source = {
            "path": str(args.calibration_from).replace("\\", "/"),
            "sha256": sha256_file(args.calibration_from),
        }
        strain_windows = None
        calibration_inputs = None
        cache_receipts = []
    else:
        block_start, block_end, window_starts = _pick_background(
            args.detector, event_gps, args.block_seconds, all_gps
        )
        calibration_distance = _distance_to_span(
            event_gps, event_gps + 32, block_start, block_end
        )
        if calibration_distance > MAX_CALIBRATION_DISTANCE_S:
            raise RuntimeError("nearest 4 h CAT1 calibration is more than 12 h away")
        strain_key = AuxiliarySeriesKey(
            detector=args.detector,
            channel=f"{args.detector}:GWOSC-4KHZ_R1_STRAIN",
            gps_start=block_start,
            gps_end=block_end,
            native_sample_rate_hz=4096.0,
            stored_sample_rate_hz=stored_rate,
            source="gwosc-open-data",
        )
        strain, strain_meta, _ = _fetch_cached_series(
            cache, strain_key, open_strain=True
        )
        strain_windows = _windows(strain, block_start, window_starts, stored_rate)
        calibration_inputs = {}
        cache_receipts = [strain_meta]
    event_inputs = {}
    for entry in selected:
        channel_rate = min(stored_rate, float(entry["sample_rate_hz"]))
        if calibration_inputs is not None:
            background_key = AuxiliarySeriesKey(
                detector=args.detector,
                channel=entry["name"],
                gps_start=block_start,
                gps_end=block_end,
                native_sample_rate_hz=float(entry["sample_rate_hz"]),
                stored_sample_rate_hz=channel_rate,
            )
            auxiliary, metadata, _ = _fetch_cached_series(
                cache, background_key, open_strain=False
            )
            cache_receipts.append(metadata)
            if channel_rate == stored_rate:
                channel_strain_windows = strain_windows
            else:
                from scipy.signal import resample_poly

                channel_strain_windows = resample_poly(
                    strain_windows, int(channel_rate), int(stored_rate), axis=1
                )
            calibration_inputs[entry["name"]] = (
                channel_strain_windows,
                _windows(auxiliary, block_start, window_starts, channel_rate),
                channel_rate,
            )

        event_aux_key = AuxiliarySeriesKey(
            detector=args.detector,
            channel=entry["name"],
            gps_start=event_gps,
            gps_end=event_gps + 32,
            native_sample_rate_hz=float(entry["sample_rate_hz"]),
            stored_sample_rate_hz=channel_rate,
        )
        event_aux, event_meta, _ = _fetch_cached_series(
            cache, event_aux_key, open_strain=False
        )
        cache_receipts.append(event_meta)
        event_inputs[entry["name"]] = (event_aux, channel_rate, entry["role"])

    event_strain_key = AuxiliarySeriesKey(
        detector=args.detector,
        channel=f"{args.detector}:GWOSC-4KHZ_R1_STRAIN",
        gps_start=event_gps,
        gps_end=event_gps + 32,
        native_sample_rate_hz=4096.0,
        stored_sample_rate_hz=stored_rate,
        source="gwosc-open-data",
    )
    event_strain, event_strain_meta, _ = _fetch_cached_series(
        cache, event_strain_key, open_strain=True
    )
    cache_receipts.append(event_strain_meta)

    if calibration_inputs is not None:
        calibration = calibrate_familywise_null(calibration_inputs)
    observed = {}
    observed_values = {}
    for channel, (event_aux, channel_rate, role) in event_inputs.items():
        if channel_rate == stored_rate:
            channel_strain = event_strain
        else:
            from scipy.signal import resample_poly

            channel_strain = resample_poly(
                event_strain, int(channel_rate), int(stored_rate)
            )
        measurement = max_coherence(channel_strain, event_aux, channel_rate)
        observed[channel] = dict(measurement, role=role)
        observed_values[channel] = measurement["max_coherence"]

    result = {
        "schema_version": 1,
        "status": "PASS",
        "scope": "O4b frozen escalation auxiliary-coherence pilot",
        "scientific_status": "DIAGNOSTIC_ONLY",
        "candidate": {
            "window_id": event["window_id"],
            "detector": args.detector,
            "gps_start": event_gps,
            "candidate_sha256": event["candidate_sha256"],
        },
        "channel_roles": args.roles,
        "channels": [entry["name"] for entry in selected],
        "background": {
            "cat1_flag": f"{args.detector}_BURST_CAT1",
            "span": [block_start, block_end],
            "window_starts": [int(value) for value in window_starts],
            "candidate_exclusion_s_center_to_center": 112.0,
            "event_to_background_distance_s": calibration_distance,
            "maximum_allowed_distance_s": MAX_CALIBRATION_DISTANCE_S,
        },
        "calibration": calibration,
        "observed": observed,
        "diagnostic_verdict": diagnostic_verdict(
            observed_values,
            calibration["time_shift_threshold"],
            calibration["zero_lag_threshold"],
        ),
        "claim_boundary": (
            "This diagnostic cannot veto, confirm, classify, or establish the "
            "physical origin of a candidate; public channel availability does "
            "not establish astrophysical safety."
        ),
        "provenance": {
            "implementation_hash_semantics": "utf8_lf_v1",
            "implementation_sha256": {
                source: _source_sha256(source)
                for source in (
                    "src/dante_light/o4b_auxiliary.py",
                    "scripts/run_dante_light_o4b_auxiliary.py",
                )
            },
            "manifest_path": str(args.manifest).replace("\\", "/"),
            "manifest_sha256": sha256_file(args.manifest),
            "policy_path": str(args.policy).replace("\\", "/"),
            "policy_sha256": sha256_file(args.policy),
            "policy_source": policy["source"],
            "calibration_source": calibration_source,
            "cache_receipts": cache_receipts,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "dependency_versions": _dependency_versions(),
        },
    }
    _atomic_json(args.output, result)
    print(json.dumps({
        "output": str(args.output),
        "diagnostic_verdict": result["diagnostic_verdict"],
        "n_channels": calibration["n_channels"],
        "n_windows": calibration["n_windows"],
        "time_shift_threshold": calibration["time_shift_threshold"],
        "zero_lag_threshold": calibration["zero_lag_threshold"],
        "max_observed": max(observed_values.values()),
    }, indent=2))


if __name__ == "__main__":
    main()
