"""Fail-closed verification of the frozen O4b escalation follow-up."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.index_contract import sha256_file  # noqa: E402
from src.dante_light.followup import (  # noqa: E402
    DEFAULT_CATALOG,
    DEFAULT_CATALOG_RAW,
    DEFAULT_GALLERY_EVIDENCE,
    DEFAULT_MANIFEST,
    DEFAULT_RESULTS,
    load_followup_manifest,
)

AVAILABILITY = Path(
    "artifacts/dante_light/o4b_followup/partner_availability_v1.json"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify_manifest() -> dict:
    payload = load_followup_manifest(DEFAULT_MANIFEST)
    candidates = payload["candidates"]
    require(payload["status"] == "frozen", "manifest status is not frozen")
    require(payload["selection"]["n_source_windows"] == 768, "source count drift")
    require(len(candidates) == 18, "escalation cohort count drift")
    require(
        payload["selection"]["detector_counts"] == {"H1": 8, "L1": 10},
        "detector counts drift",
    )
    keys = {(row["detector"], float(row["gps_start"])) for row in candidates}
    require(len(keys) == len(candidates), "duplicate detector/GPS candidates")
    require(
        all(row["decision_score"] > row["decision_threshold"] for row in candidates),
        "frozen ESCALATE threshold does not reproduce",
    )
    return payload


def verify_physical(manifest: dict) -> dict:
    payload = json.loads(DEFAULT_RESULTS.read_text(encoding="utf-8"))
    require(
        payload["manifest_sha256"] == manifest["manifest_sha256"],
        "physical manifest mismatch",
    )
    require(payload["status"] in {"complete", "complete_with_unavailable"}, "physical run incomplete")
    require(sha256_file(payload["primary_index_path"]) == payload["primary_index_sha256"], "physical index hash mismatch")
    candidates = {row["window_id"]: row for row in manifest["candidates"]}
    events = {row["window_id"]: row for row in payload["events"]}
    require(len(events) == len(payload["events"]), "duplicate physical outcomes")
    require(events.keys() == candidates.keys(), "physical outcome coverage mismatch")
    measured, unavailable = [], []
    for window_id, event in events.items():
        require(event["candidate_sha256"] == candidates[window_id]["candidate_sha256"], f"candidate provenance mismatch: {window_id}")
        status = event["measurement_status"]
        if status == "MEASURED":
            values = np.asarray(event["cc_null_values"], dtype=float)
            require(values.size == int(event["n_null"]), f"null count mismatch: {window_id}")
            require(values.size > 0 and np.isfinite(values).all(), f"invalid null values: {window_id}")
            require(math.isfinite(float(event["cc_onsource"])), f"invalid onsource: {window_id}")
            require(float(event["cc_null_mean"]) == float(np.mean(values)), f"null mean mismatch: {window_id}")
            require(float(event["cc_null_max"]) == float(np.max(values)), f"null max mismatch: {window_id}")
            require(
                bool(event["per_event_null_exceeded"])
                == (float(event["cc_onsource"]) > float(event["cc_null_max"])),
                f"null verdict mismatch: {window_id}",
            )
            measured.append(event)
        else:
            require(status in {"CANDIDATE_DATA_UNAVAILABLE", "PARTNER_DATA_UNAVAILABLE"}, f"unknown physical status: {window_id}")
            require(event["cc_onsource"] is None and not event["cc_null_values"], f"unavailable event contains statistic: {window_id}")
            unavailable.append(event)
    summary = payload["summary"]
    require(summary["n_candidates"] == len(candidates), "physical summary candidate count")
    require(summary["n_accounted"] == len(events), "physical summary accounting")
    require(summary["n_physical_measured"] == len(measured), "physical measured count")
    require(summary["n_data_unavailable"] == len(unavailable), "physical unavailable count")
    require(summary["n_failed"] == 0, "physical failures present")
    require(
        summary["n_per_event_null_exceeded"]
        == sum(bool(row["per_event_null_exceeded"]) for row in measured),
        "physical exceedance count mismatch",
    )
    availability = json.loads(AVAILABILITY.read_text(encoding="utf-8"))
    require(availability["status"] == "complete", "partner availability incomplete")
    require(availability["manifest_sha256"] == manifest["manifest_sha256"], "partner availability manifest mismatch")
    require(availability["physical_artifact_sha256"] == sha256_file(DEFAULT_RESULTS), "partner availability physical hash mismatch")
    require(availability["n_unavailable"] == len(unavailable), "partner availability count mismatch")
    require(availability["n_without_whole_context_cat1"] == len(unavailable), "unavailable partners unexpectedly have CAT1 coverage")
    availability_ids = {row["window_id"] for row in availability["checks"]}
    require(availability_ids == {row["window_id"] for row in unavailable}, "partner availability coverage mismatch")
    return payload


def verify_catalog(manifest: dict) -> dict:
    payload = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))
    raw = DEFAULT_CATALOG_RAW.read_bytes()
    require(payload["status"] == "complete", "catalog status incomplete")
    require(payload["manifest_sha256"] == manifest["manifest_sha256"], "catalog manifest mismatch")
    require(hashlib.sha256(raw).hexdigest() == payload["catalog_response_sha256"], "catalog raw hash mismatch")
    source = json.loads(raw)
    require(source.get("next") is None, "catalog response is paginated")
    require(int(source["results_count"]) == len(source["results"]), "catalog response count mismatch")
    require(payload["catalog_event_count"] == len(source["results"]), "catalog event count drift")
    require(payload["n_candidates"] == len(manifest["candidates"]), "catalog candidate count drift")
    recomputed = {}
    for candidate in manifest["candidates"]:
        start = float(candidate["gps_start"])
        end = start + float(candidate["duration_s"])
        recomputed[candidate["window_id"]] = sorted(
            row["name"] for row in source["results"] if start <= float(row["gps"]) < end
        )
    stored = {
        row["window_id"]: sorted(event["name"] for event in row["matched_catalog_events"])
        for row in payload["crossmatches"]
    }
    require(stored == recomputed, "catalog cross-match does not reproduce")
    require(
        payload["n_candidates_with_catalog_match"]
        == sum(bool(value) for value in recomputed.values()),
        "catalog match summary drift",
    )
    return payload


def verify_gallery(manifest: dict, physical: dict) -> dict:
    payload = json.loads(DEFAULT_GALLERY_EVIDENCE.read_text(encoding="utf-8"))
    require(payload["status"] == "complete", "gallery status incomplete")
    require(payload["manifest_sha256"] == manifest["manifest_sha256"], "gallery manifest mismatch")
    require(payload["physical_artifact_sha256"] == sha256_file(DEFAULT_RESULTS), "gallery physical hash mismatch")
    require(sha256_file(payload["gallery_path"]) == payload["gallery_sha256"], "gallery image hash mismatch")
    require(payload["n_candidates"] == len(manifest["candidates"]), "gallery candidate count")
    require(payload["n_exact_strain_hash"] == len(manifest["candidates"]), "gallery strain mismatch")
    require(payload["n_exact_image_hash"] == len(manifest["candidates"]), "gallery image mismatch")
    require(len(physical["events"]) == payload["n_candidates"], "gallery physical coverage")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=("manifest", "physical", "catalog", "gallery", "all"), default="all"
    )
    args = parser.parse_args()
    try:
        manifest = verify_manifest()
        print("PASS manifest - exact 768 -> 18 frozen detector/GPS cohort")
        physical = None
        if args.stage in {"physical", "gallery", "all"}:
            physical = verify_physical(manifest)
            print("PASS physical - every escalation measured or explicitly unavailable")
        if args.stage in {"catalog", "all"}:
            verify_catalog(manifest)
            print("PASS catalog - official frozen GWTC-5.0 response reproduces")
        if args.stage in {"gallery", "all"}:
            assert physical is not None
            verify_gallery(manifest, physical)
            print("PASS gallery - 18/18 canonical strain and image hashes reproduce")
    except Exception as exc:
        print(f"FAIL {args.stage} - {exc}")
        return 1
    print(f"RESULT {args.stage}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
