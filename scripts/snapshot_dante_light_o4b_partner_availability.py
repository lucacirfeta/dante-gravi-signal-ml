"""Freeze GWOSC CAT1 coverage for unavailable O4b coincidence partners."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gwosc.timeline import get_segments  # noqa: E402

from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.followup import DEFAULT_MANIFEST, DEFAULT_RESULTS, load_followup_manifest  # noqa: E402


OUTPUT = Path("artifacts/dante_light/o4b_followup/partner_availability_v1.json")


def main() -> int:
    manifest = load_followup_manifest(DEFAULT_MANIFEST)
    physical = json.loads(DEFAULT_RESULTS.read_text(encoding="utf-8"))
    unavailable = [
        row
        for row in physical["events"]
        if str(row["measurement_status"]).endswith("DATA_UNAVAILABLE")
    ]
    if not unavailable:
        raise RuntimeError("physical artifact contains no unavailable outcomes")
    candidates = {row["window_id"]: row for row in manifest["candidates"]}
    detectors = sorted({row["unavailable_detector"] for row in unavailable})
    query_start = int(min(float(row["gps"]) for row in unavailable) - 8)
    query_end = int(max(float(row["gps"]) for row in unavailable) + 48)
    timelines = {}
    for detector in detectors:
        name = f"{detector}_CBC_CAT1"
        segments = [
            [float(start), float(end)]
            for start, end in get_segments(name, query_start, query_end)
        ]
        timelines[detector] = {"timeline": name, "segments": segments}
    checks = []
    for event in unavailable:
        candidate = candidates[event["window_id"]]
        start = float(candidate["gps_start"]) - 4.0
        end = float(candidate["gps_start"]) + float(candidate["duration_s"]) + 4.0
        detector = event["unavailable_detector"]
        covered = any(
            left <= start and right >= end
            for left, right in timelines[detector]["segments"]
        )
        checks.append(
            {
                "window_id": event["window_id"],
                "unavailable_detector": detector,
                "required_interval": [start, end],
                "whole_context_cat1_covered": covered,
            }
        )
    payload = {
        "schema_version": 1,
        "status": "complete",
        "source": "GWOSC public timeline API",
        "fetched_utc": datetime.now(timezone.utc).isoformat(),
        "query_interval": [query_start, query_end],
        "manifest_sha256": manifest["manifest_sha256"],
        "physical_artifact_sha256": sha256_file(DEFAULT_RESULTS),
        "timelines": timelines,
        "checks": checks,
        "n_unavailable": len(checks),
        "n_without_whole_context_cat1": sum(
            not row["whole_context_cat1_covered"] for row in checks
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_bytes((json.dumps(payload, indent=2) + "\n").encode("utf-8"))
    temporary.replace(OUTPUT)
    print(json.dumps({key: payload[key] for key in ("n_unavailable", "n_without_whole_context_cat1")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
