#!/usr/bin/env python3
"""Aggregate the exact 18-event O4b public auxiliary diagnostic."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import canonical_json_sha256  # noqa: E402
from src.dante_light.o4b_auxiliary import sha256_file  # noqa: E402


MANIFEST = Path("artifacts/dante_light/o4b_followup/manifest_v1.json")
EVENT_DIR = Path("artifacts/dante_light/o4b_auxiliary/events")
OUTPUT = Path("artifacts/dante_light/o4b_auxiliary/result_v1.json")


def _source_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = {
        (row["detector"], int(row["gps_start"])): row
        for row in manifest["candidates"]
    }
    paths = sorted(EVENT_DIR.glob("*_v1.json"))
    if not expected or len(paths) != len(expected):
        raise RuntimeError("event artifact count does not match frozen cohort")
    rows = []
    calibrations = {}
    seen = set()
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidate = payload["candidate"]
        key = (candidate["detector"], int(candidate["gps_start"]))
        if key not in expected or key in seen:
            raise RuntimeError("event artifact coverage is not exact")
        seen.add(key)
        source = payload["provenance"].get("calibration_source")
        if not source:
            raise RuntimeError("final event lacks a calibration source")
        source_path = Path(source["path"])
        if not source_path.is_file() or sha256_file(source_path) != source["sha256"]:
            raise RuntimeError("calibration source hash mismatch")
        calibrations[source["path"]] = source["sha256"]
        observed = payload["observed"]
        maximum_channel, maximum_row = max(
            observed.items(), key=lambda item: item[1]["max_coherence"]
        )
        calibration = payload["calibration"]
        rows.append(
            {
                "detector": key[0],
                "gps_start": key[1],
                "window_id": candidate["window_id"],
                "candidate_sha256": candidate["candidate_sha256"],
                "diagnostic_verdict": payload["diagnostic_verdict"],
                "maximum_channel": maximum_channel,
                "maximum_role": maximum_row["role"],
                "maximum_coherence": maximum_row["max_coherence"],
                "peak_frequency_hz": maximum_row["peak_frequency_hz"],
                "time_shift_threshold": calibration["time_shift_threshold"],
                "zero_lag_threshold": calibration["zero_lag_threshold"],
                "event_to_background_distance_s": payload["background"][
                    "event_to_background_distance_s"
                ],
                "calibration_path": source["path"],
                "event_artifact_path": str(path).replace("\\", "/"),
                "event_artifact_sha256": sha256_file(path),
            }
        )
    if seen != set(expected):
        raise RuntimeError("frozen candidate coverage is incomplete")
    rows.sort(key=lambda row: (row["detector"], row["gps_start"]))
    counts = Counter(row["diagnostic_verdict"] for row in rows)
    detector_counts = {
        detector: dict(
            Counter(
                row["diagnostic_verdict"]
                for row in rows
                if row["detector"] == detector
            )
        )
        for detector in ("H1", "L1")
    }
    body = {
        "schema_version": 1,
        "status": "PASS",
        "scientific_status": "DIAGNOSTIC_ONLY",
        "scope": "all frozen O4b DANTE-Light escalations",
        "n_events": len(rows),
        "detector_counts": {
            detector: sum(row["detector"] == detector for row in rows)
            for detector in ("H1", "L1")
        },
        "n_calibration_epochs": len(calibrations),
        "verdict_counts": dict(sorted(counts.items())),
        "verdict_counts_by_detector": detector_counts,
        "maximum_event_to_background_distance_s": max(
            row["event_to_background_distance_s"] for row in rows
        ),
        "calibration_artifacts": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(calibrations.items())
        ],
        "events": rows,
        "interpretation": (
            "No event exceeds its local quiet zero-lag family-wise threshold. "
            "PERSISTENT_BASELINE_COMPATIBLE events exceed only the time-shift "
            "threshold and cannot support candidate-specific coupling. This "
            "limited public-channel diagnostic neither excludes an instrumental "
            "origin nor establishes novelty or astrophysical origin."
        ),
        "provenance": {
            "manifest_path": str(MANIFEST).replace("\\", "/"),
            "manifest_sha256": sha256_file(MANIFEST),
            "implementation_hash_semantics": "utf8_lf_v1",
            "implementation_sha256": {
                source: _source_sha256(source)
                for source in (
                    "src/dante_light/o4b_auxiliary.py",
                    "scripts/run_dante_light_o4b_auxiliary.py",
                    "scripts/run_dante_light_o4b_auxiliary_calibrations.sh",
                    "scripts/run_dante_light_o4b_auxiliary_batch.sh",
                    "scripts/aggregate_dante_light_o4b_auxiliary.py",
                    "environment-o4b-aux.yml",
                )
            },
        },
    }
    payload = {**body, "result_sha256": canonical_json_sha256(body)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    encoded = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
        "utf-8"
    )
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, OUTPUT)
    print(json.dumps({
        "output": str(OUTPUT),
        "n_events": len(rows),
        "n_calibration_epochs": len(calibrations),
        "verdict_counts": dict(counts),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
