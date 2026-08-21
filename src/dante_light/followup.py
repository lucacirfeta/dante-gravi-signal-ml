"""Frozen offline follow-up of DANTE-Light prospective escalations.

The shadow decision is immutable.  This module only derives a detector-aware
ledger from the exact canonical/shared records and measures the established
physical coincidence statistic for every escalated detector/GPS window.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from src.core.index_contract import sha256_file
from src.core.patch_scorer import PatchScorer
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v2_production.coincidence_physical import (
    CoincidenceDataUnavailable,
    _patch_time_band,
    analyze_candidate,
)


DEFAULT_CANONICAL = Path("runs/dante_light/o4b_v2/canonical/records.jsonl")
DEFAULT_SHARED = Path("runs/dante_light/o4b_v2/shared/records.jsonl")
DEFAULT_MANIFEST = Path("artifacts/dante_light/o4b_followup/manifest_v1.json")
DEFAULT_RESULTS = Path("artifacts/dante_light/o4b_followup/physical_v1.json")
DEFAULT_CATALOG = Path("artifacts/dante_light/o4b_followup/catalog_v1.json")
DEFAULT_CATALOG_RAW = Path(
    "artifacts/dante_light/o4b_followup/gwtc5_events_raw_v1.json"
)
DEFAULT_GALLERY = Path("artifacts/dante_light/o4b_followup/gallery_v1.png")
DEFAULT_GALLERY_EVIDENCE = Path(
    "artifacts/dante_light/o4b_followup/gallery_v1.json"
)
DEFAULT_PRIMARY_INDEX = Path("data/reference/patch_compressed_index_o3b.npz")
GWTC5_URL = (
    "https://gwosc.org/api/v2/catalogs/GWTC-5.0/events"
    "?include-default-parameters=true&pagesize=500"
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid JSONL at {path}:{line_number}") from exc
    return rows


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes((json.dumps(payload, indent=2) + "\n").encode("utf-8"))
    temporary.replace(path)


def _source_sha256(path: str | Path) -> str:
    """Hash source text with the cross-platform ``utf8_lf_v1`` contract."""
    text = Path(path).read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _record_key(record: dict[str, Any]) -> tuple[str, float]:
    window = record["window"]
    return str(window["detector"]), float(window["gps_start"])


def _records_by_key(path: Path) -> dict[tuple[str, float], dict[str, Any]]:
    rows = _read_jsonl(path)
    keyed = {_record_key(row): row for row in rows}
    if len(keyed) != len(rows):
        raise ContractError(f"duplicate detector/GPS identities in {path}")
    return keyed


def _exact_shadow_pair(
    canonical: dict[str, Any], shared: dict[str, Any], key: tuple[str, float]
) -> None:
    fields = ("window", "disposition", "epoch_id", "scores", "representation_sha256")
    for field in fields:
        if canonical.get(field) != shared.get(field):
            raise ContractError(f"canonical/shared {field} mismatch at {key}")
    evidence_fields = (
        "strain_sha256",
        "image_sha256",
        "decision_score",
        "decision_threshold",
        "primary_top_k_indices",
        "primary_top_k_sha256",
        "primary_mil_vector_sha256",
    )
    for field in evidence_fields:
        if canonical.get("evidence", {}).get(field) != shared.get("evidence", {}).get(field):
            raise ContractError(f"canonical/shared evidence {field} mismatch at {key}")


def build_followup_manifest(
    *,
    canonical_records: str | Path = DEFAULT_CANONICAL,
    shared_records: str | Path = DEFAULT_SHARED,
    output_path: str | Path = DEFAULT_MANIFEST,
) -> dict[str, Any]:
    """Freeze the exact escalation cohort without rescoring or relabelling it."""
    canonical_path, shared_path = Path(canonical_records), Path(shared_records)
    canonical = _records_by_key(canonical_path)
    shared = _records_by_key(shared_path)
    if canonical.keys() != shared.keys():
        raise ContractError("canonical/shared detector/GPS coverage mismatch")

    candidates = []
    for key in sorted(canonical):
        left, right = canonical[key], shared[key]
        _exact_shadow_pair(left, right, key)
        if left["disposition"] != "ESCALATE":
            continue
        evidence = left["evidence"]
        top_k = np.asarray(evidence["primary_top_k_indices"], dtype=np.int64)
        if top_k.ndim != 1 or top_k.size == 0 or len(np.unique(top_k)) != top_k.size:
            raise ContractError(f"invalid Top-k localization evidence at {key}")
        if np.any((top_k < 0) | (top_k >= 37 * 37)):
            raise ContractError(f"out-of-grid Top-k index at {key}")
        t_offset, f_lo, f_hi = _patch_time_band(top_k)
        score_name = str(evidence["decision_score"])
        score = float(left["scores"][score_name])
        threshold = float(evidence["decision_threshold"])
        if not score > threshold:
            raise ContractError(f"ESCALATE does not reproduce frozen threshold at {key}")
        window = left["window"]
        candidate = {
            "window_id": window["window_id"],
            "detector": window["detector"],
            "partner": "L1" if window["detector"] == "H1" else "H1",
            "gps_start": float(window["gps_start"]),
            "duration_s": float(window["duration_s"]),
            "epoch_id": left["epoch_id"],
            "decision_score_name": score_name,
            "decision_score": score,
            "decision_threshold": threshold,
            "frozen_dsd_class": "ROBUST",
            "primary_top_k_indices": top_k.tolist(),
            "primary_top_k_sha256": evidence["primary_top_k_sha256"],
            "strain_sha256": evidence["strain_sha256"],
            "localization": {
                "method": "primary_top_k_patch_median_v1",
                "t_offset_s": t_offset,
                "feature_gps": float(window["gps_start"]) + t_offset,
                "f_lo_hz": f_lo,
                "f_hi_hz": f_hi,
            },
        }
        candidate["candidate_sha256"] = canonical_json_sha256(candidate)
        candidates.append(candidate)
    if not candidates:
        raise ContractError("shadow records contain no ESCALATE cohort")

    body = {
        "schema_version": 1,
        "status": "frozen",
        "purpose": "offline detector-aware follow-up; never a shadow relabelling",
        "implementation_hash_semantics": "utf8_lf_v1",
        "implementation_sha256": {
            path: _source_sha256(path)
            for path in (
                "src/dante_light/followup.py",
                "src/dante_light/contracts.py",
                "src/dante_light/preprocessing.py",
                "src/pipeline_v2_production/coincidence_physical.py",
            )
        },
        "source_artifacts": [
            {"path": str(canonical_path).replace("\\", "/"), "sha256": sha256_file(canonical_path)},
            {"path": str(shared_path).replace("\\", "/"), "sha256": sha256_file(shared_path)},
        ],
        "selection": {
            "disposition": "ESCALATE",
            "n_source_windows": len(canonical),
            "n_candidates": len(candidates),
            "detector_counts": {
                detector: sum(row["detector"] == detector for row in candidates)
                for detector in ("H1", "L1")
            },
        },
        "scientific_boundary": (
            "ROBUST reproduces the frozen O4a detector threshold only; it does not "
            "mean novel, instrumental, astrophysical, or physically coincident."
        ),
        "candidates": candidates,
    }
    payload = {**body, "manifest_sha256": canonical_json_sha256(body)}
    _atomic_json(Path(output_path), payload)
    return payload


def load_followup_manifest(path: str | Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    body = dict(payload)
    digest = body.pop("manifest_sha256", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("follow-up manifest digest mismatch")
    for source, expected in payload["implementation_sha256"].items():
        if not Path(source).is_file() or _source_sha256(source) != expected:
            raise ContractError(f"follow-up implementation mismatch: {source}")
    for artifact in payload["source_artifacts"]:
        source_path = Path(artifact["path"])
        if not source_path.is_file() or sha256_file(source_path) != artifact["sha256"]:
            raise ContractError(f"follow-up source artifact mismatch: {source_path}")
    if payload["selection"]["n_candidates"] != len(payload["candidates"]):
        raise ContractError("follow-up candidate count mismatch")
    for candidate in payload["candidates"]:
        body = dict(candidate)
        digest = body.pop("candidate_sha256", None)
        if digest != canonical_json_sha256(body):
            raise ContractError(f"candidate digest mismatch: {candidate.get('window_id')}")
    return payload


def run_physical_followup(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    output_path: str | Path = DEFAULT_RESULTS,
    primary_index: str | Path = DEFAULT_PRIMARY_INDEX,
    device: str | None = None,
    with_iou: bool = True,
) -> dict[str, Any]:
    """Measure physical coincidence for every frozen escalation, fail-closed."""
    manifest = load_followup_manifest(manifest_path)
    index_path = Path(primary_index)
    scorer = PatchScorer(index_path, device=device, k=68)
    output = Path(output_path)
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    if output.is_file():
        previous = json.loads(output.read_text(encoding="utf-8"))
        if previous.get("manifest_sha256") != manifest["manifest_sha256"]:
            raise ContractError("physical checkpoint belongs to another cohort")
        if previous.get("primary_index_sha256") != sha256_file(index_path):
            raise ContractError("physical checkpoint uses another primary index")
        events = list(previous.get("events", []))
        seen = {str(event["window_id"]) for event in events}

    failures = []
    checkpoint = {
        "schema_version": 1,
        "status": "partial",
        "manifest_path": str(Path(manifest_path)).replace("\\", "/"),
        "manifest_sha256": manifest["manifest_sha256"],
        "primary_index_path": str(index_path).replace("\\", "/"),
        "primary_index_sha256": sha256_file(index_path),
        "with_patch_iou": bool(with_iou),
        "events": events,
        "failures": failures,
    }
    for candidate in manifest["candidates"]:
        if candidate["window_id"] in seen:
            continue
        try:
            event = analyze_candidate(
                scorer,
                candidate["detector"],
                candidate["partner"],
                float(candidate["gps_start"]),
                np.asarray(candidate["primary_top_k_indices"], dtype=np.int64),
                with_iou=with_iou,
            )
            event.update(
                {
                    "measurement_status": "MEASURED",
                    "window_id": candidate["window_id"],
                    "candidate_sha256": candidate["candidate_sha256"],
                    "decision_score": candidate["decision_score"],
                    "decision_threshold": candidate["decision_threshold"],
                    "frozen_dsd_class": candidate["frozen_dsd_class"],
                    "per_event_null_exceeded": (
                        event["cc_null_max"] is not None
                        and event["cc_onsource"] > event["cc_null_max"]
                    ),
                }
            )
            events.append(event)
        except CoincidenceDataUnavailable as exc:
            events.append(
                {
                    "window_id": candidate["window_id"],
                    "candidate_sha256": candidate["candidate_sha256"],
                    "gps": candidate["gps_start"],
                    "detector": candidate["detector"],
                    "partner": candidate["partner"],
                    "decision_score": candidate["decision_score"],
                    "decision_threshold": candidate["decision_threshold"],
                    "frozen_dsd_class": candidate["frozen_dsd_class"],
                    "measurement_status": (
                        "PARTNER_DATA_UNAVAILABLE"
                        if exc.role == "partner"
                        else "CANDIDATE_DATA_UNAVAILABLE"
                    ),
                    "unavailable_detector": exc.detector,
                    "unavailable_reason": str(exc),
                    "cc_onsource": None,
                    "cc_null_values": [],
                    "cc_null_mean": None,
                    "cc_null_max": None,
                    "n_null": 0,
                    "patch_iou": None,
                    "per_event_null_exceeded": None,
                }
            )
        except Exception as exc:  # persisted, then the run fails closed below
            failures.append(
                {
                    "window_id": candidate["window_id"],
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
        checkpoint["events"] = events
        checkpoint["failures"] = failures
        _atomic_json(output, checkpoint)

    expected = {row["window_id"] for row in manifest["candidates"]}
    accounted = {row["window_id"] for row in events}
    measured_events = [
        event for event in events if event.get("measurement_status") == "MEASURED"
    ]
    unavailable_events = [
        event
        for event in events
        if str(event.get("measurement_status", "")).endswith("DATA_UNAVAILABLE")
    ]
    complete = accounted == expected and not failures
    null_values = np.asarray(
        [
            value
            for event in measured_events
            for value in event.get("cc_null_values", [])
        ],
        dtype=float,
    )
    summary = {
        "n_candidates": len(expected),
        "n_accounted": len(accounted),
        "n_physical_measured": len(measured_events),
        "n_data_unavailable": len(unavailable_events),
        "data_unavailable_by_status": {
            status: sum(event["measurement_status"] == status for event in unavailable_events)
            for status in ("CANDIDATE_DATA_UNAVAILABLE", "PARTNER_DATA_UNAVAILABLE")
        },
        "n_failed": len(failures),
        "n_per_event_null_exceeded": sum(
            bool(event["per_event_null_exceeded"]) for event in measured_events
        ),
        "n_null_values": int(null_values.size),
        "pooled_null_p99_diagnostic": (
            float(np.percentile(null_values, 99)) if null_values.size else None
        ),
        "interpretation": (
            "Per-event and pooled null comparisons are descriptive follow-up. "
            "They are not a pre-registered O4b population threshold and do not "
            "establish novelty or astrophysical origin."
        ),
    }
    final = {
        **checkpoint,
        "status": (
            "complete_with_unavailable"
            if complete and unavailable_events
            else "complete"
            if complete
            else "failed"
        ),
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
    }
    _atomic_json(output, final)
    if not complete:
        raise RuntimeError(
            f"physical follow-up incomplete: {len(accounted)}/{len(expected)}, "
            f"{len(failures)} failures"
        )
    return final


def build_catalog_crossmatch(
    catalog_payload: dict[str, Any],
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    output_path: str | Path = DEFAULT_CATALOG,
    source_url: str = GWTC5_URL,
    response_sha256: str,
) -> dict[str, Any]:
    """Cross-match every frozen window against a frozen GWTC-5.0 response."""
    manifest = load_followup_manifest(manifest_path)
    rows = catalog_payload.get("results")
    if not isinstance(rows, list) or int(catalog_payload.get("results_count", -1)) != len(rows):
        raise ContractError("incomplete or malformed GWTC-5.0 catalog response")
    if catalog_payload.get("next") is not None:
        raise ContractError("paginated GWTC-5.0 response is incomplete")
    if any(str(row.get("catalog")) != "GWTC-5.0" for row in rows):
        raise ContractError("catalog response contains a non-GWTC-5.0 event")
    events = sorted(
        (
            {
                "name": str(row["name"]),
                "version": int(row["version"]),
                "gps": float(row["gps"]),
                "detectors": sorted(str(value) for value in row.get("detectors", [])),
            }
            for row in rows
        ),
        key=lambda row: (row["gps"], row["name"], row["version"]),
    )
    crossmatches = []
    for candidate in manifest["candidates"]:
        start = float(candidate["gps_start"])
        end = start + float(candidate["duration_s"])
        matches = [event for event in events if start <= event["gps"] < end]
        crossmatches.append(
            {
                "window_id": candidate["window_id"],
                "detector": candidate["detector"],
                "gps_start": start,
                "feature_gps": candidate["localization"]["feature_gps"],
                "matched_catalog_events": matches,
            }
        )
    payload = {
        "schema_version": 1,
        "status": "complete",
        "manifest_sha256": manifest["manifest_sha256"],
        "catalog": "GWTC-5.0",
        "catalog_source_url": source_url,
        "catalog_response_sha256": response_sha256,
        "catalog_event_count": len(events),
        "window_match_rule": "catalog GPS in [gps_start, gps_start + 32 s)",
        "n_candidates": len(crossmatches),
        "n_candidates_with_catalog_match": sum(
            bool(row["matched_catalog_events"]) for row in crossmatches
        ),
        "crossmatches": crossmatches,
        "scientific_boundary": (
            "No catalog match excludes association with a listed GWTC-5.0 event "
            "inside the window; it does not establish a novel glitch morphology."
        ),
    }
    _atomic_json(Path(output_path), payload)
    return payload


def fetch_and_crossmatch_gwtc5(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    output_path: str | Path = DEFAULT_CATALOG,
    raw_output_path: str | Path = DEFAULT_CATALOG_RAW,
    source_url: str = GWTC5_URL,
) -> dict[str, Any]:
    """Fetch the official public catalog once, preserve bytes, then cross-match."""
    import requests

    response = requests.get(
        source_url,
        headers={"Accept": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    raw = response.content
    raw_path = Path(raw_output_path)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = raw_path.with_suffix(raw_path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(raw_path)
    digest = hashlib.sha256(raw).hexdigest()
    payload = build_catalog_crossmatch(
        response.json(),
        manifest_path=manifest_path,
        output_path=output_path,
        source_url=source_url,
        response_sha256=digest,
    )
    payload["catalog_response_path"] = str(raw_path).replace("\\", "/")
    payload["fetched_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(Path(output_path), payload)
    return payload


def build_morphology_gallery(
    *,
    manifest_path: str | Path = DEFAULT_MANIFEST,
    physical_path: str | Path = DEFAULT_RESULTS,
    output_path: str | Path = DEFAULT_GALLERY,
    evidence_path: str | Path = DEFAULT_GALLERY_EVIDENCE,
) -> dict[str, Any]:
    """Regenerate exact canonical images and render an audit gallery."""
    import matplotlib.pyplot as plt
    from matplotlib import patches

    from src.dante_light.contracts import WindowIdentity
    from src.dante_light.preprocessing import prepare_canonical_window

    manifest = load_followup_manifest(manifest_path)
    physical_source = Path(physical_path)
    physical = json.loads(physical_source.read_text(encoding="utf-8"))
    if physical.get("manifest_sha256") != manifest["manifest_sha256"]:
        raise ContractError("gallery physical artifact belongs to another cohort")
    physical_by_id = {event["window_id"]: event for event in physical["events"]}
    expected_ids = {row["window_id"] for row in manifest["candidates"]}
    if physical_by_id.keys() != expected_ids:
        raise ContractError("gallery requires all physical outcomes")
    shared_source = Path(manifest["source_artifacts"][1]["path"])
    shared_by_id = {
        row["window"]["window_id"]: row for row in _read_jsonl(shared_source)
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(3, 6, figsize=(20, 10), dpi=160)
    checks = []
    dx, dy = 32.0 / 37.0, 256.0 / 37.0
    frequency_pixels = np.linspace(0, 256, 5)
    frequency_labels = [
        f"{20.0 * (1291.0 / 20.0) ** (pixel / 256.0):.0f}"
        for pixel in frequency_pixels
    ]
    for axis, candidate in zip(axes.ravel(), manifest["candidates"]):
        window = WindowIdentity(
            "O4B", candidate["detector"], float(candidate["gps_start"]), 32.0
        )
        prepared = prepare_canonical_window(
            window, local_only=False, remote_only=True
        )
        strain_match = prepared.strain_sha256 == candidate["strain_sha256"]
        record = shared_by_id[candidate["window_id"]]
        image_match = prepared.image_sha256 == record["evidence"]["image_sha256"]
        if not strain_match or not image_match:
            raise ContractError(
                f"canonical gallery regeneration mismatch: {candidate['window_id']}"
            )
        axis.imshow(np.transpose(prepared.image, (1, 0, 2)), origin="lower", aspect="auto")
        for index in candidate["primary_top_k_indices"]:
            time_cell, frequency_cell = divmod(int(index), 37)
            axis.add_patch(
                patches.Rectangle(
                    (time_cell * dx, frequency_cell * dy),
                    dx,
                    dy,
                    linewidth=0.28,
                    edgecolor="white",
                    facecolor="none",
                    alpha=0.42,
                )
            )
        localization = candidate["localization"]
        axis.axvline(localization["t_offset_s"], color="red", linewidth=1.0)
        result = physical_by_id[candidate["window_id"]]
        status = result["measurement_status"].replace("_", " ")
        if status == "MEASURED":
            status = (
                f"cc={result['cc_onsource']:.3f}; "
                f"nullmax={result['cc_null_max']:.3f}"
            )
        axis.set_title(
            f"{candidate['detector']} {int(candidate['gps_start'])}\n"
            f"DSD={candidate['decision_score']:.3f} | {status}",
            fontsize=7,
        )
        axis.set_xlim(0, 32)
        axis.set_ylim(0, 256)
        axis.set_xticks((0, 16, 32))
        axis.set_yticks(frequency_pixels)
        axis.set_yticklabels(frequency_labels, fontsize=6)
        axis.tick_params(axis="x", labelsize=6)
        checks.append(
            {
                "window_id": candidate["window_id"],
                "strain_sha256": prepared.strain_sha256,
                "image_sha256": prepared.image_sha256,
                "strain_hash_match": strain_match,
                "image_hash_match": image_match,
            }
        )
    fig.supxlabel("Time from 32 s window start (s)")
    fig.supylabel("Frequency (Hz; log-spaced ticks)")
    fig.suptitle(
        "DANTE-Light O4b frozen escalations: canonical Q-transforms and Top-k localization",
        fontsize=12,
    )
    fig.tight_layout(rect=(0.02, 0.02, 1, 0.96))
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)
    evidence = {
        "schema_version": 1,
        "status": "complete",
        "manifest_sha256": manifest["manifest_sha256"],
        "physical_artifact_path": str(physical_source).replace("\\", "/"),
        "physical_artifact_sha256": sha256_file(physical_source),
        "gallery_path": str(output).replace("\\", "/"),
        "gallery_sha256": sha256_file(output),
        "n_candidates": len(checks),
        "n_exact_strain_hash": sum(row["strain_hash_match"] for row in checks),
        "n_exact_image_hash": sum(row["image_hash_match"] for row in checks),
        "axis_contract": {
            "horizontal": "time, 0--32 s",
            "vertical": "Q-transform frequency pixels with log-spaced Hz ticks, 20--1291 Hz",
            "top_k": "white boxes; row=time and column=frequency",
            "localization": "red vertical line at median Top-k time",
        },
        "checks": checks,
    }
    _atomic_json(Path(evidence_path), evidence)
    return evidence
