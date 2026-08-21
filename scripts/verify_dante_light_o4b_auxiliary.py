#!/usr/bin/env python3
"""Fail-closed verification for public O4b auxiliary diagnostics."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4b_auxiliary import (  # noqa: E402
    AuxiliarySeriesCache,
    AuxiliarySeriesKey,
    diagnostic_verdict,
    load_channel_policy,
    sha256_file,
)
from src.dante_light.contracts import canonical_json_sha256  # noqa: E402


POLICY = Path("config/dante_light_o4b_aux_channels_v1.json")
SOURCE_CSV = Path(
    "artifacts/dante_light/o4b_auxiliary/O4_bulk_aux_channel_list.csv"
)
MANIFEST = Path("artifacts/dante_light/o4b_followup/manifest_v1.json")
PILOTS = (
    Path("artifacts/dante_light/o4b_auxiliary/pilot_h1_1404598432_v1.json"),
    Path("artifacts/dante_light/o4b_auxiliary/pilot_l1_1409756544_v1.json"),
)
CALIBRATIONS = (
    Path("artifacts/dante_light/o4b_auxiliary/calibration_h1_1404598432_v1.json"),
    Path("artifacts/dante_light/o4b_auxiliary/calibration_h1_1409759680_v1.json"),
    Path("artifacts/dante_light/o4b_auxiliary/calibration_h1_1415053344_v1.json"),
    Path("artifacts/dante_light/o4b_auxiliary/calibration_l1_1409759744_v1.json"),
    Path("artifacts/dante_light/o4b_auxiliary/calibration_l1_1414942688_v1.json"),
)
EVENT_DIR = Path("artifacts/dante_light/o4b_auxiliary/events")
RESULT = Path("artifacts/dante_light/o4b_auxiliary/result_v1.json")


def _fail(message: str) -> None:
    raise RuntimeError(message)


def _source_sha256(path: str | Path) -> str:
    normalized = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def verify_policy() -> None:
    policy = load_channel_policy(POLICY)
    if _source_sha256(SOURCE_CSV) != policy["source"]["sha256_utf8_lf"]:
        _fail("vendored O4 auxiliary inventory hash mismatch")
    with SOURCE_CSV.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    source_names = {row["Channel"] for row in rows}
    policy_names = {
        item["name"]
        for detector_rows in policy["channels"].values()
        for item in detector_rows
    }
    if source_names != policy_names or len(rows) != 25:
        _fail("policy channels do not exactly match official inventory")
    print("PASS policy: official 25-channel inventory exact; diagnostic-only")


def _verify_event_payload(path: Path, payload: dict, candidates: dict, policy: dict) -> None:
    if payload.get("status") != "PASS":
        _fail(f"{path}: status is not PASS")
    if payload.get("scientific_status") != "DIAGNOSTIC_ONLY":
        _fail(f"{path}: scientific boundary was promoted")
    if payload.get("channel_roles") != ["environmental_monitor"]:
        _fail(f"{path}: final diagnostic uses a non-environmental role")
    candidate = payload["candidate"]
    key = (candidate["detector"], int(candidate["gps_start"]))
    source_candidate = candidates.get(key)
    if source_candidate is None:
        _fail(f"{path}: candidate absent from frozen manifest")
    if candidate["window_id"] != source_candidate["window_id"]:
        _fail(f"{path}: window identity mismatch")
    if candidate["candidate_sha256"] != source_candidate["candidate_sha256"]:
        _fail(f"{path}: candidate hash mismatch")
    background = payload["background"]
    distance = background.get("event_to_background_distance_s")
    if not isinstance(distance, int) or distance < 0 or distance > 12 * 3600:
        _fail(f"{path}: calibration distance exceeds the frozen guard")
    if background.get("maximum_allowed_distance_s") != 12 * 3600:
        _fail(f"{path}: calibration distance guard changed")
    provenance = payload["provenance"]
    if provenance.get("implementation_hash_semantics") != "utf8_lf_v1":
        _fail(f"{path}: implementation hash semantics mismatch")
    implementation = provenance.get("implementation_sha256", {})
    if set(implementation) != {
        "src/dante_light/o4b_auxiliary.py",
        "scripts/run_dante_light_o4b_auxiliary.py",
    }:
        _fail(f"{path}: implementation provenance is incomplete")
    for source, expected_hash in implementation.items():
        if not Path(source).is_file() or _source_sha256(source) != expected_hash:
            _fail(f"{path}: implementation provenance mismatch: {source}")
    if provenance["manifest_sha256"] != sha256_file(MANIFEST):
        _fail(f"{path}: manifest provenance mismatch")
    if provenance["policy_sha256"] != sha256_file(POLICY):
        _fail(f"{path}: policy provenance mismatch")
    if provenance["policy_source"] != policy["source"]:
        _fail(f"{path}: upstream source provenance mismatch")
    dependencies = provenance.get("dependency_versions", {})
    required_dependencies = {
        "numpy",
        "scipy",
        "gwpy",
        "gwosc",
        "gwdatafind",
        "python-nds2-client",
    }
    if set(dependencies) != required_dependencies or "NOT_INSTALLED" in dependencies.values():
        _fail(f"{path}: dependency provenance is incomplete")
    calibration = payload["calibration"]
    n_windows = calibration["n_windows"]
    if n_windows < 30:
        _fail(f"{path}: insufficient quiet-window count")
    if calibration["n_time_shift_pairs"] != n_windows * (n_windows - 1):
        _fail(f"{path}: time-shift pair count mismatch")
    for name in ("time_shift_threshold", "zero_lag_threshold"):
        value = calibration[name]
        if not math.isfinite(value) or not 0 <= value <= 1:
            _fail(f"{path}: invalid {name}")
    observed = {
        channel: row["max_coherence"]
        for channel, row in payload["observed"].items()
    }
    expected = diagnostic_verdict(
        observed,
        calibration["time_shift_threshold"],
        calibration["zero_lag_threshold"],
    )
    if payload["diagnostic_verdict"] != expected:
        _fail(f"{path}: verdict does not reproduce")
    forbidden = {"VETO", "COUPLED", "INSTRUMENTAL", "PHYSICAL"}
    if payload["diagnostic_verdict"] in forbidden:
        _fail(f"{path}: forbidden physical verdict")


def verify_artifacts() -> None:
    policy = load_channel_policy(POLICY)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    candidates = {
        (row["detector"], int(row["gps_start"])): row
        for row in manifest["candidates"]
    }
    for path in (*PILOTS, *CALIBRATIONS):
        payload = json.loads(path.read_text(encoding="utf-8"))
        _verify_event_payload(path, payload, candidates, policy)
        candidate = payload["candidate"]
        print(
            f"PASS artifact: {candidate['detector']} {candidate['gps_start']} "
            f"{payload['diagnostic_verdict']} sha256={sha256_file(path)}"
        )

    event_paths = sorted(EVENT_DIR.glob("*_v1.json"))
    if len(event_paths) != 18:
        _fail("final event artifact count is not 18")
    event_keys = set()
    calibration_paths = {str(path).replace("\\", "/") for path in CALIBRATIONS}
    for path in event_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        _verify_event_payload(path, payload, candidates, policy)
        candidate = payload["candidate"]
        key = (candidate["detector"], int(candidate["gps_start"]))
        if key in event_keys:
            _fail("duplicate final event key")
        event_keys.add(key)
        source = payload["provenance"].get("calibration_source")
        if not source or source["path"] not in calibration_paths:
            _fail(f"{path}: invalid calibration source")
        source_path = Path(source["path"])
        if sha256_file(source_path) != source["sha256"]:
            _fail(f"{path}: calibration source SHA256 mismatch")
        source_payload = json.loads(source_path.read_text(encoding="utf-8"))
        for name in ("channels", "channel_roles", "calibration"):
            if payload[name] != source_payload[name]:
                _fail(f"{path}: reused {name} differs from calibration source")
        for name in (
            "cat1_flag",
            "span",
            "window_starts",
            "candidate_exclusion_s_center_to_center",
            "maximum_allowed_distance_s",
        ):
            if payload["background"][name] != source_payload["background"][name]:
                _fail(f"{path}: reused background {name} differs from source")
        if (
            payload["provenance"]["dependency_versions"]
            != source_payload["provenance"]["dependency_versions"]
        ):
            _fail(f"{path}: event/calibration dependency versions differ")
    if event_keys != set(candidates):
        _fail("final event coverage differs from frozen cohort")

    result = json.loads(RESULT.read_text(encoding="utf-8"))
    body = dict(result)
    digest = body.pop("result_sha256", None)
    if digest != canonical_json_sha256(body):
        _fail("aggregate result self-hash mismatch")
    if result.get("status") != "PASS" or result.get("scientific_status") != "DIAGNOSTIC_ONLY":
        _fail("aggregate result status/boundary mismatch")
    if result.get("n_events") != 18 or result.get("n_calibration_epochs") != 5:
        _fail("aggregate result cohort/calibration count mismatch")
    event_hashes = {
        row["event_artifact_path"]: row["event_artifact_sha256"]
        for row in result["events"]
    }
    if event_hashes != {
        str(path).replace("\\", "/"): sha256_file(path) for path in event_paths
    }:
        _fail("aggregate event artifact hashes mismatch")
    counts = {}
    for path in event_paths:
        verdict = json.loads(path.read_text(encoding="utf-8"))["diagnostic_verdict"]
        counts[verdict] = counts.get(verdict, 0) + 1
    if result["verdict_counts"] != dict(sorted(counts.items())):
        _fail("aggregate verdict counts do not reproduce")
    if result["verdict_counts"].get("AUXILIARY_EXCESS", 0) != 0:
        _fail("unexpected AUXILIARY_EXCESS in frozen result")
    result_implementation = result["provenance"]["implementation_sha256"]
    if set(result_implementation) != {
        "src/dante_light/o4b_auxiliary.py",
        "scripts/run_dante_light_o4b_auxiliary.py",
        "scripts/run_dante_light_o4b_auxiliary_calibrations.sh",
        "scripts/run_dante_light_o4b_auxiliary_batch.sh",
        "scripts/aggregate_dante_light_o4b_auxiliary.py",
        "environment-o4b-aux.yml",
    }:
        _fail("aggregate implementation provenance is incomplete")
    for source, expected_hash in result_implementation.items():
        if _source_sha256(source) != expected_hash:
            _fail(f"aggregate implementation mismatch: {source}")
    calibration_hashes = {
        row["path"]: row["sha256"] for row in result["calibration_artifacts"]
    }
    if calibration_hashes != {
        str(path).replace("\\", "/"): sha256_file(path) for path in CALIBRATIONS
    }:
        _fail("aggregate calibration artifact hashes mismatch")
    result_rows = {
        (row["detector"], int(row["gps_start"])): row for row in result["events"]
    }
    for path in event_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        candidate = payload["candidate"]
        key = (candidate["detector"], int(candidate["gps_start"]))
        row = result_rows.get(key)
        if row is None:
            _fail("aggregate result is missing an event row")
        maximum_channel, maximum = max(
            payload["observed"].items(), key=lambda item: item[1]["max_coherence"]
        )
        expected_fields = {
            "window_id": candidate["window_id"],
            "candidate_sha256": candidate["candidate_sha256"],
            "diagnostic_verdict": payload["diagnostic_verdict"],
            "maximum_channel": maximum_channel,
            "maximum_role": maximum["role"],
            "maximum_coherence": maximum["max_coherence"],
            "peak_frequency_hz": maximum["peak_frequency_hz"],
            "time_shift_threshold": payload["calibration"]["time_shift_threshold"],
            "zero_lag_threshold": payload["calibration"]["zero_lag_threshold"],
            "event_to_background_distance_s": payload["background"][
                "event_to_background_distance_s"
            ],
            "calibration_path": payload["provenance"]["calibration_source"]["path"],
            "event_artifact_path": str(path).replace("\\", "/"),
            "event_artifact_sha256": sha256_file(path),
        }
        for name, expected_value in expected_fields.items():
            if row.get(name) != expected_value:
                _fail(f"aggregate event field mismatch: {key} {name}")
    print("PASS final: exact 18-event coverage, 5 local epochs, aggregate self-hash")


def verify_cache(cache_dir: Path) -> None:
    cache = AuxiliarySeriesCache(cache_dir)
    for path in (*PILOTS, *CALIBRATIONS, *sorted(EVENT_DIR.glob("*_v1.json"))):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for receipt in payload["provenance"]["cache_receipts"]:
            key = AuxiliarySeriesKey(**receipt["key"])
            loaded = cache.load(key)
            if loaded is None:
                _fail(f"{path}: cache object {key.cache_id} missing")
            _, metadata = loaded
            for name in ("cache_id", "key", "values_sha256", "npy_sha256"):
                if metadata[name] != receipt[name]:
                    _fail(f"{path}: cache receipt mismatch for {key.cache_id}")
    print("PASS cache: every pilot receipt resolves with exact hashes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("policy", "artifacts", "cache", "all"), default="all")
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    if args.stage in {"policy", "all"}:
        verify_policy()
    if args.stage in {"artifacts", "all"}:
        verify_artifacts()
    if args.stage in {"cache", "all"}:
        if args.cache_dir is None:
            _fail("--cache-dir is required for cache verification")
        verify_cache(args.cache_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
