"""Outcome-blind, append-only human-review telemetry for DANTE-Light v8.1.

This module measures queue waiting and operator service time.  It deliberately
does not implement prioritization, review outcomes, a top-X budget, a deadline,
or a readiness gate.  Those are separate scientific decisions.
"""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
from html import escape
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config/dante_light_v8_1_review_telemetry_contract.json"
SCHEMA_VERSION = 1
EMPTY_LEDGER_SHA256 = hashlib.sha256(b"").hexdigest()
EVENT_TYPES = ("ENROLLED", "STARTED", "COMPLETED")
SOURCE_SEMANTICS = ("historical_backlog_enrollment", "poll_observed_enrollment")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(value), handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _utc_now() -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    return now.isoformat(timespec="microseconds").replace("+00:00", "Z"), int(
        now.timestamp() * 1_000_000_000
    )


def _validate_timestamp(timestamp_utc: str, timestamp_unix_ns: int) -> None:
    try:
        parsed = datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"invalid UTC timestamp: {timestamp_utc!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ContractError("telemetry timestamp must be UTC")
    expected = int(parsed.timestamp() * 1_000_000_000)
    # ISO microseconds cannot represent the final three nanosecond digits.
    if abs(expected - int(timestamp_unix_ns)) >= 1_000:
        raise ContractError("UTC and Unix telemetry timestamps disagree")


def _operator_digest(operator_id: str) -> str:
    normalized = str(operator_id).strip()
    if not normalized:
        raise ContractError("operator_id must be non-empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _read_json(Path(path))
    body = dict(contract)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v8.1 review telemetry contract digest mismatch")
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported v8.1 review telemetry schema")
    if contract.get("status") != "FROZEN_TELEMETRY_ONLY_NO_OPERATIONAL_GATE":
        raise ContractError("review telemetry contract is not telemetry-only")
    if contract["sufficiency"]["status"] != "UNFROZEN_NOT_A_READINESS_GATE":
        raise ContractError("telemetry contract must not freeze a sufficiency gate")
    if contract["operational_parameters"] != {
        "age_override": None,
        "deadline": None,
        "top_x_budget": None,
    }:
        raise ContractError("telemetry contract must not contain operational parameters")
    procedure = contract.get("review_procedure", {})
    if procedure.get("procedure_revision") != 2:
        raise ContractError("review telemetry requires frozen procedure revision 2")
    if len(procedure.get("frozen_checklist", [])) != 6:
        raise ContractError("review telemetry checklist must contain six frozen items")
    return contract


def _load_source(source_dir: str | Path) -> dict[str, Any]:
    source_dir = Path(source_dir).resolve()
    manifest_path = source_dir / "run_manifest.json"
    records_path = source_dir / "records.jsonl"
    manifest = _read_json(manifest_path)
    manifest_body = dict(manifest)
    declared = manifest_body.pop("manifest_sha256", None)
    if declared != canonical_json_sha256(manifest_body):
        raise ContractError("source run manifest digest mismatch")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        lines = records_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read source records: {records_path}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid source record at line {line_number}") from exc
        body = dict(record)
        record_id = body.pop("record_id", None)
        if record_id != f"dlr1-{canonical_json_sha256(body)[:24]}":
            raise ContractError(f"source record digest mismatch at line {line_number}")
        if record_id in seen:
            raise ContractError(f"duplicate source record: {record_id}")
        seen.add(record_id)
        if record.get("disposition") == "ESCALATE":
            window = record.get("window", {})
            records.append(
                {
                    "source_record_id": record_id,
                    "window_id": window["window_id"],
                    "run": window["run"],
                    "detector": window["detector"],
                    "gps_start": float(window["gps_start"]),
                    "duration_s": float(window["duration_s"]),
                }
            )
    records.sort(key=lambda row: (row["gps_start"], row["detector"], row["source_record_id"]))
    return {
        "source_dir": source_dir,
        "manifest": manifest,
        "manifest_file_sha256": sha256_file(manifest_path),
        "records_file_sha256": sha256_file(records_path),
        "escalations": records,
    }


def _verify_anchor(contract: Mapping[str, Any], source: Mapping[str, Any]) -> None:
    anchor = contract.get("historical_scale_anchor", {})
    if not anchor:
        return
    expected = {
        "manifest_file_sha256": anchor["run_manifest_sha256"],
        "records_file_sha256": anchor["records_sha256"],
    }
    for key, value in expected.items():
        if source[key] != value:
            raise ContractError(f"historical scale anchor {key} mismatch")
    if len(source["escalations"]) != int(anchor["observed_escalations"]):
        raise ContractError("historical scale anchor escalation count mismatch")


def verify_contract_provenance(
    contract: Mapping[str, Any], *, root: str | Path = ROOT
) -> dict[str, Any]:
    root = Path(root).resolve()

    def member(relative: str) -> Path:
        path = (root / relative).resolve()
        if path != root and root not in path.parents:
            raise ContractError(f"contract path escapes repository root: {relative}")
        return path

    phase0 = contract["provenance"]
    phase0_path = member(phase0["phase0_result_path"])
    if sha256_file(phase0_path) != phase0["phase0_result_sha256"]:
        raise ContractError("phase-zero result provenance mismatch")
    anchor = contract["historical_scale_anchor"]
    source_dir = member(anchor["run_manifest_path"]).parent
    source = _load_source(source_dir)
    _verify_anchor(contract, source)
    if member(anchor["records_path"]) != source_dir / "records.jsonl":
        raise ContractError("historical records path does not match anchor source")
    packet_artifacts: dict[str, str] = {}
    for item in contract["review_procedure"]["packet_artifacts"]:
        path = member(item["path"])
        if sha256_file(path) != item["sha256"]:
            raise ContractError(f"review packet provenance mismatch: {item['role']}")
        packet_artifacts[item["role"]] = "PASS"
    return {
        "phase0_result": "PASS",
        "historical_scale_anchor": "PASS",
        "historical_escalations": len(source["escalations"]),
        "review_packet_artifacts": dict(sorted(packet_artifacts.items())),
    }


def iid_order_statistic_floor(population_quantile: float, confidence: float) -> int:
    """Return the iid sample-size floor P(max >= q_p) >= confidence.

    This is an illustrative mathematical floor only.  It is not used as a
    telemetry readiness gate because human-review observations are temporally
    dependent and may arrive in batches.
    """

    p = float(population_quantile)
    c = float(confidence)
    if not (0.0 < p < 1.0 and 0.0 < c < 1.0):
        raise ContractError("quantile and confidence must lie strictly within (0, 1)")
    return int(math.ceil(math.log1p(-c) / math.log(p)))


def sufficiency_scenarios(contract: Mapping[str, Any]) -> dict[str, Any]:
    scenarios = []
    for item in contract["sufficiency"]["illustrative_iid_order_statistic_scenarios"]:
        p = float(item["population_quantile"])
        c = float(item["confidence"])
        scenarios.append(
            {
                "population_quantile": p,
                "confidence": c,
                "minimum_completed_escalations_iid": iid_order_statistic_floor(p, c),
            }
        )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "ILLUSTRATIVE_ONLY_NOT_A_TELEMETRY_READINESS_GATE",
        "formula": "ceil(log(1-confidence)/log(population_quantile))",
        "iid_assumption_accepted_for_inference": False,
        "required_inference_unit": contract["measurement"]["inference_unit"],
        "scenarios": scenarios,
        "unfrozen_decisions": list(contract["sufficiency"]["unfrozen_decisions"]),
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


class ReviewTelemetryLedger:
    """Durable telemetry state machine with an append-only SHA256 chain."""

    def __init__(
        self,
        telemetry_dir: str | Path,
        *,
        contract: Mapping[str, Any],
        operator_id: str | None = None,
        create: bool = False,
        now: tuple[str, int] | None = None,
    ) -> None:
        self.telemetry_dir = Path(telemetry_dir).resolve()
        self.manifest_path = self.telemetry_dir / "telemetry_manifest.json"
        self.events_path = self.telemetry_dir / "events.jsonl"
        self.contract = dict(contract)
        if create:
            if self.manifest_path.exists() or self.events_path.exists():
                raise ContractError("refusing to overwrite existing telemetry ledger")
            if operator_id is None:
                raise ContractError("operator_id is required when creating telemetry")
            self.telemetry_dir.mkdir(parents=True, exist_ok=True)
            timestamp_utc, timestamp_unix_ns = now or _utc_now()
            _validate_timestamp(timestamp_utc, timestamp_unix_ns)
            base = {
                "schema_version": SCHEMA_VERSION,
                "contract_digest": self.contract["contract_digest"],
                "operator_pseudonym_sha256": _operator_digest(operator_id),
                "created_at_utc": timestamp_utc,
                "created_at_unix_ns": int(timestamp_unix_ns),
                "outcome_fields_permitted": [],
                "status": "ACTIVE_TELEMETRY_NO_OPERATIONAL_GATE",
            }
            telemetry_id = f"dlt81-{canonical_json_sha256(base)[:24]}"
            manifest_body = {**base, "telemetry_id": telemetry_id}
            manifest = {
                **manifest_body,
                "manifest_digest": canonical_json_sha256(manifest_body),
            }
            _atomic_json(self.manifest_path, manifest)
        self.manifest = self._load_manifest()
        self.events = self._load_events()

    def _load_manifest(self) -> dict[str, Any]:
        manifest = _read_json(self.manifest_path)
        body = dict(manifest)
        declared = body.pop("manifest_digest", None)
        if declared != canonical_json_sha256(body):
            raise ContractError("telemetry manifest digest mismatch")
        if body.get("contract_digest") != self.contract["contract_digest"]:
            raise ContractError("telemetry manifest is bound to another contract")
        if body.get("outcome_fields_permitted") != []:
            raise ContractError("telemetry manifest permits outcome fields")
        if body.get("status") != "ACTIVE_TELEMETRY_NO_OPERATIONAL_GATE":
            raise ContractError("telemetry manifest has an invalid status")
        expected_id = f"dlt81-{canonical_json_sha256({k: v for k, v in body.items() if k != 'telemetry_id'})[:24]}"
        if body.get("telemetry_id") != expected_id:
            raise ContractError("telemetry identity mismatch")
        _validate_timestamp(body["created_at_utc"], body["created_at_unix_ns"])
        return manifest

    def _load_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        entries: list[dict[str, Any]] = []
        previous = EMPTY_LEDGER_SHA256
        state: dict[str, str] = {}
        previous_time = int(self.manifest["created_at_unix_ns"])
        for index, line in enumerate(self.events_path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractError(f"incomplete telemetry ledger at line {index + 1}") from exc
            body = dict(entry)
            declared = body.pop("event_digest", None)
            if body.get("sequence") != len(entries):
                raise ContractError("telemetry event sequence is broken")
            if body.get("previous_digest") != previous:
                raise ContractError("telemetry event hash chain is broken")
            if declared != canonical_json_sha256(body):
                raise ContractError("telemetry event digest mismatch")
            if body.get("manifest_digest") != self.manifest["manifest_digest"]:
                raise ContractError("telemetry event is bound to another manifest")
            event_type = body.get("event_type")
            if event_type not in EVENT_TYPES:
                raise ContractError(f"invalid telemetry event type: {event_type!r}")
            _validate_timestamp(body["timestamp_utc"], body["timestamp_unix_ns"])
            if int(body["timestamp_unix_ns"]) < previous_time:
                raise ContractError("telemetry events are not monotonic")
            previous_time = int(body["timestamp_unix_ns"])
            self._validate_event_fields(body)
            record_id = body["source_record_id"]
            prior = state.get(record_id)
            expected_prior = {"ENROLLED": None, "STARTED": "ENROLLED", "COMPLETED": "STARTED"}[event_type]
            if prior != expected_prior:
                raise ContractError(
                    f"invalid telemetry transition for {record_id}: {prior!r} -> {event_type}"
                )
            state[record_id] = event_type
            entries.append(entry)
            previous = declared
        return entries

    @staticmethod
    def _validate_event_fields(body: Mapping[str, Any]) -> None:
        base = {
            "schema_version",
            "sequence",
            "previous_digest",
            "manifest_digest",
            "event_type",
            "source_record_id",
            "window_id",
            "detector",
            "timestamp_utc",
            "timestamp_unix_ns",
        }
        enrollment = {
            "run",
            "gps_start",
            "duration_s",
            "source_semantics",
            "source_manifest_file_sha256",
            "source_records_file_sha256",
        }
        allowed = base | (enrollment if body.get("event_type") == "ENROLLED" else set())
        if set(body) != allowed:
            forbidden = sorted(set(body) - allowed)
            raise ContractError(f"unexpected/outcome telemetry fields: {forbidden}")
        if body["event_type"] == "ENROLLED" and body["source_semantics"] not in SOURCE_SEMANTICS:
            raise ContractError("invalid source enrollment semantics")

    def _state(self) -> dict[str, dict[str, Any]]:
        state: dict[str, dict[str, Any]] = {}
        for event in self.events:
            record_id = event["source_record_id"]
            row = state.setdefault(record_id, {"events": []})
            row["events"].append(event)
            row["state"] = event["event_type"]
            if event["event_type"] == "ENROLLED":
                row["identity"] = {
                    key: event[key]
                    for key in ("source_record_id", "window_id", "run", "detector", "gps_start", "duration_s")
                }
        return state

    def _append(self, fields: Mapping[str, Any], *, now: tuple[str, int] | None = None) -> dict[str, Any]:
        # Re-read before appending so a concurrent/stale object cannot silently fork the chain.
        self.events = self._load_events()
        timestamp_utc, timestamp_unix_ns = now or _utc_now()
        previous_time = (
            int(self.events[-1]["timestamp_unix_ns"])
            if self.events
            else int(self.manifest["created_at_unix_ns"])
        )
        if int(timestamp_unix_ns) < previous_time:
            raise ContractError("new telemetry event predates the durable ledger")
        body = {
            "schema_version": SCHEMA_VERSION,
            "sequence": len(self.events),
            "previous_digest": self.events[-1]["event_digest"] if self.events else EMPTY_LEDGER_SHA256,
            "manifest_digest": self.manifest["manifest_digest"],
            "timestamp_utc": timestamp_utc,
            "timestamp_unix_ns": int(timestamp_unix_ns),
            **dict(fields),
        }
        _validate_timestamp(timestamp_utc, timestamp_unix_ns)
        self._validate_event_fields(body)
        entry = {**body, "event_digest": canonical_json_sha256(body)}
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.events_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(
                descriptor,
                (json.dumps(entry, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8"),
            )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.events = self._load_events()
        return entry

    def sync_source(
        self,
        source_dir: str | Path,
        *,
        source_semantics: str,
        require_historical_anchor: bool = False,
        now: tuple[str, int] | None = None,
    ) -> int:
        if source_semantics not in SOURCE_SEMANTICS:
            raise ContractError("unsupported source semantics")
        source = _load_source(source_dir)
        if require_historical_anchor:
            _verify_anchor(self.contract, source)
        existing = set(self._state())
        additions = [row for row in source["escalations"] if row["source_record_id"] not in existing]
        for row in additions:
            self._append(
                {
                    "event_type": "ENROLLED",
                    **row,
                    "source_semantics": source_semantics,
                    "source_manifest_file_sha256": source["manifest_file_sha256"],
                    "source_records_file_sha256": source["records_file_sha256"],
                },
                now=now,
            )
        return len(additions)

    def transition(
        self,
        source_record_id: str,
        event_type: str,
        *,
        now: tuple[str, int] | None = None,
    ) -> dict[str, Any]:
        if event_type not in ("STARTED", "COMPLETED"):
            raise ContractError("manual telemetry transition must be STARTED or COMPLETED")
        state = self._state()
        if source_record_id not in state:
            raise ContractError(f"unknown telemetry record: {source_record_id}")
        expected = "ENROLLED" if event_type == "STARTED" else "STARTED"
        if state[source_record_id]["state"] != expected:
            raise ContractError(
                f"cannot mark {source_record_id} {event_type} from {state[source_record_id]['state']}"
            )
        identity = state[source_record_id]["identity"]
        return self._append(
            {
                "event_type": event_type,
                "source_record_id": source_record_id,
                "window_id": identity["window_id"],
                "detector": identity["detector"],
            },
            now=now,
        )

    def pending(self) -> list[dict[str, Any]]:
        state = self._state()
        return [
            row["identity"]
            for row in state.values()
            if row["state"] == "ENROLLED"
        ]

    def build_review_packet(
        self,
        source_record_id: str,
        *,
        packet_dir: str | Path | None = None,
        root: str | Path = ROOT,
    ) -> dict[str, Any]:
        """Build a provenance-bound packet without recording a review outcome."""

        root = Path(root).resolve()
        state = self._state()
        if source_record_id not in state:
            raise ContractError(f"unknown telemetry record: {source_record_id}")
        identity = state[source_record_id]["identity"]
        procedure = self.contract["review_procedure"]

        artifacts: dict[str, Path] = {}
        for item in procedure["packet_artifacts"]:
            path = (root / item["path"]).resolve()
            if path != root and root not in path.parents:
                raise ContractError(f"review packet path escapes repository: {item['path']}")
            if sha256_file(path) != item["sha256"]:
                raise ContractError(f"review packet provenance mismatch: {item['role']}")
            artifacts[item["role"]] = path

        manifest = _read_json(artifacts["candidate_manifest"])
        manifest_body = dict(manifest)
        manifest_digest = manifest_body.pop("manifest_sha256", None)
        if manifest_digest != canonical_json_sha256(manifest_body):
            raise ContractError("review packet candidate manifest digest mismatch")
        candidates = list(manifest.get("candidates", []))
        candidate_matches = [
            (index, row)
            for index, row in enumerate(candidates)
            if row.get("window_id") == identity["window_id"]
        ]
        if len(candidate_matches) != 1:
            raise ContractError("telemetry identity is not unique in review packet manifest")
        candidate_index, candidate = candidate_matches[0]
        for key in ("detector", "gps_start", "duration_s"):
            if candidate.get(key) != identity[key]:
                raise ContractError(f"review packet identity mismatch: {key}")

        physical = _read_json(artifacts["cross_detector_physical"])
        catalog = _read_json(artifacts["catalog_crossmatch"])
        gallery = _read_json(artifacts["gallery_evidence"])
        for name, payload in (
            ("physical", physical),
            ("catalog", catalog),
            ("gallery", gallery),
        ):
            if payload.get("manifest_sha256") != manifest["manifest_sha256"]:
                raise ContractError(f"review packet {name} belongs to another manifest")
        if gallery.get("gallery_sha256") != sha256_file(artifacts["canonical_gallery"]):
            raise ContractError("review packet gallery image digest mismatch")
        if gallery.get("physical_artifact_sha256") != sha256_file(
            artifacts["cross_detector_physical"]
        ):
            raise ContractError("review packet physical/gallery binding mismatch")

        physical_matches = [
            row for row in physical.get("events", []) if row.get("window_id") == identity["window_id"]
        ]
        catalog_matches = [
            row for row in catalog.get("crossmatches", []) if row.get("window_id") == identity["window_id"]
        ]
        gallery_checks = [
            row for row in gallery.get("checks", []) if row.get("window_id") == identity["window_id"]
        ]
        if len(physical_matches) != 1 or len(catalog_matches) != 1 or len(gallery_checks) != 1:
            raise ContractError("review packet follow-up coverage is incomplete")
        if not gallery_checks[0].get("strain_hash_match") or not gallery_checks[0].get(
            "image_hash_match"
        ):
            raise ContractError("review packet canonical gallery check failed")

        grid = procedure["visual_crop_contract"]
        rows, columns = int(grid["rows"]), int(grid["columns"])
        if len(candidates) != rows * columns:
            raise ContractError("review packet gallery population/grid mismatch")
        row_index, column_index = divmod(candidate_index, columns)
        destination = Path(packet_dir or self.telemetry_dir / "packets").resolve()
        destination.mkdir(parents=True, exist_ok=True)
        crop_path = destination / f"{source_record_id}.png"

        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - repository dependency
            raise ContractError("Pillow is required to render review packets") from exc
        with Image.open(artifacts["canonical_gallery"]) as image:
            expected_size = (
                int(grid["expected_image_width_px"]),
                int(grid["expected_image_height_px"]),
            )
            if image.size != expected_size:
                raise ContractError("review packet gallery dimensions changed")
            centers = [int(value) for value in grid["column_centers_px"]]
            if len(centers) != columns:
                raise ContractError("review packet column-center contract mismatch")
            left_width = int(grid["crop_left_width_px"])
            right_width = int(grid["crop_right_width_px"])
            x0 = max(0, centers[column_index] - left_width)
            x1 = min(image.width, centers[column_index] + right_width)
            boundaries = [int(value) for value in grid["row_boundaries_px"]]
            y0, y1 = boundaries[row_index], boundaries[row_index + 1]
            crop = image.crop((x0, y0, x1, y1))
            crop.save(crop_path)

        physical_row = physical_matches[0]
        catalog_row = catalog_matches[0]
        body = {
            "schema_version": SCHEMA_VERSION,
            "procedure_revision": procedure["procedure_revision"],
            "telemetry_id": self.manifest["telemetry_id"],
            "source_record_id": source_record_id,
            "window": dict(identity),
            "gallery_position": {
                "one_based_index": candidate_index + 1,
                "row": row_index + 1,
                "column": column_index + 1,
            },
            "visual": {
                "candidate_crop_sha256": sha256_file(crop_path),
                "legend": dict(gallery["axis_contract"]),
            },
            "exact_decision": {
                "score_name": candidate["decision_score_name"],
                "score": candidate["decision_score"],
                "threshold": candidate["decision_threshold"],
                "frozen_dsd_class": candidate["frozen_dsd_class"],
            },
            "localization": dict(candidate["localization"]),
            "cross_detector": {
                key: physical_row.get(key)
                for key in (
                    "measurement_status",
                    "partner",
                    "cc_onsource",
                    "cc_null_mean",
                    "cc_null_max",
                    "n_null",
                    "patch_iou",
                    "per_event_null_exceeded",
                )
            },
            "catalog_crossmatch": {
                "matched_catalog_events": list(catalog_row["matched_catalog_events"]),
                "match_count": len(catalog_row["matched_catalog_events"]),
                "rule": catalog["window_match_rule"],
            },
            "checklist": list(procedure["frozen_checklist"]),
            "completion_definition": procedure["completion_definition"],
            "scientific_boundary": (
                "packet content is displayed for a standardized human task; no review outcome "
                "is written to the telemetry ledger and no ranking is active"
            ),
        }
        packet = {**body, "packet_digest": canonical_json_sha256(body)}
        json_path = destination / f"{source_record_id}.json"
        html_path = destination / f"{source_record_id}.html"
        _atomic_json(json_path, packet)

        checklist_html = "".join(
            f"<li>{escape(item)}</li>" for item in packet["checklist"]
        )
        matched = packet["catalog_crossmatch"]["matched_catalog_events"]
        matched_text = "none" if not matched else json.dumps(matched, sort_keys=True)
        html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>DANTE-Light review {escape(source_record_id)}</title>
<style>body{{font:16px system-ui;max-width:980px;margin:2rem auto;padding:0 1rem}}img{{max-width:100%;border:1px solid #999}}table{{border-collapse:collapse}}td,th{{padding:.35rem .6rem;border:1px solid #ccc;text-align:left}}code{{background:#eee;padding:.1rem .25rem}}</style></head>
<body><h1>DANTE-Light standardized review packet</h1>
<p><code>{escape(source_record_id)}</code> — {escape(identity['detector'])}, GPS {identity['gps_start']:.3f}</p>
<img src="{escape(crop_path.name)}" alt="canonical Q-transform candidate crop">
<table><tr><th>Exact score</th><td>{candidate['decision_score']:.6f}</td><th>Threshold</th><td>{candidate['decision_threshold']:.6f}</td></tr>
<tr><th>DSD class</th><td>{escape(str(candidate['frozen_dsd_class']))}</td><th>Gallery cell</th><td>row {row_index + 1}, column {column_index + 1}</td></tr>
<tr><th>Physical status</th><td>{escape(str(physical_row.get('measurement_status')))}</td><th>Partner</th><td>{escape(str(physical_row.get('partner')))}</td></tr>
<tr><th>cc on-source</th><td>{escape(str(physical_row.get('cc_onsource')))}</td><th>null max</th><td>{escape(str(physical_row.get('cc_null_max')))}</td></tr>
<tr><th>Catalog matches</th><td colspan="3">{escape(matched_text)}</td></tr></table>
<h2>Frozen checklist</h2><ol>{checklist_html}</ol>
<p><strong>Completion:</strong> {escape(procedure['completion_definition'])}</p>
<p>No review outcome is stored in telemetry.</p></body></html>"""
        temporary = html_path.with_suffix(".html.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(html)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, html_path)
        return {
            "packet": packet,
            "packet_json": str(json_path),
            "packet_html": str(html_path),
            "candidate_image": str(crop_path),
        }

    def export_review_batch(
        self,
        output_dir: str | Path,
        *,
        root: str | Path = ROOT,
    ) -> dict[str, Any]:
        """Export every enrolled candidate without changing telemetry state."""

        output = Path(output_dir).resolve()
        packet_dir = output / "candidates"
        state = self._state()
        identities = [row["identity"] for row in state.values()]
        if not identities:
            raise ContractError("cannot export an empty review cohort")

        rendered = [
            self.build_review_packet(
                identity["source_record_id"], packet_dir=packet_dir, root=root
            )
            for identity in identities
        ]
        packets = [item["packet"] for item in rendered]

        csv_path = output / "candidate_summary.csv"
        csv_temporary = csv_path.with_suffix(".csv.tmp")
        output.mkdir(parents=True, exist_ok=True)
        columns = (
            "index",
            "source_record_id",
            "window_id",
            "detector",
            "gps_start",
            "exact_score",
            "exact_threshold",
            "frozen_dsd_class",
            "physical_status",
            "partner",
            "cc_onsource",
            "cc_null_max",
            "catalog_match_count",
            "candidate_html",
        )
        with csv_temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for index, packet in enumerate(packets, 1):
                writer.writerow(
                    {
                        "index": index,
                        "source_record_id": packet["source_record_id"],
                        "window_id": packet["window"]["window_id"],
                        "detector": packet["window"]["detector"],
                        "gps_start": packet["window"]["gps_start"],
                        "exact_score": packet["exact_decision"]["score"],
                        "exact_threshold": packet["exact_decision"]["threshold"],
                        "frozen_dsd_class": packet["exact_decision"]["frozen_dsd_class"],
                        "physical_status": packet["cross_detector"]["measurement_status"],
                        "partner": packet["cross_detector"]["partner"],
                        "cc_onsource": packet["cross_detector"]["cc_onsource"],
                        "cc_null_max": packet["cross_detector"]["cc_null_max"],
                        "catalog_match_count": packet["catalog_crossmatch"]["match_count"],
                        "candidate_html": f"candidates/{packet['source_record_id']}.html",
                    }
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(csv_temporary, csv_path)

        cards = []
        for index, packet in enumerate(packets, 1):
            record_id = packet["source_record_id"]
            decision = packet["exact_decision"]
            physical = packet["cross_detector"]
            cards.append(
                f"""<article><h2>{index}. {escape(packet['window']['detector'])} GPS {packet['window']['gps_start']:.3f}</h2>
<a href="candidates/{escape(record_id)}.html"><img src="candidates/{escape(record_id)}.png" alt="candidate {index}"></a>
<p><code>{escape(record_id)}</code></p>
<p>Exact score {decision['score']:.6f}; threshold {decision['threshold']:.6f}; DSD {escape(str(decision['frozen_dsd_class']))}.</p>
<p>Physical {escape(str(physical['measurement_status']))}; cc={escape(str(physical['cc_onsource']))}; null max={escape(str(physical['cc_null_max']))}; catalog matches={packet['catalog_crossmatch']['match_count']}.</p></article>"""
            )
        index_html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>DANTE-Light O4b review batch</title>
<style>body{{font:16px system-ui;margin:2rem}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:1.5rem}}article{{border:1px solid #bbb;padding:1rem;border-radius:.4rem}}img{{width:100%;height:auto}}code{{font-size:.85rem}}</style></head>
<body><h1>DANTE-Light O4b frozen escalation review batch</h1>
<p>All 18 already-computed exact escalation follow-ups. This export does not start telemetry, request a human outcome, or gate pipeline execution. Click a panel for the full standardized checklist packet.</p>
<main>{''.join(cards)}</main></body></html>"""
        index_path = output / "index.html"
        _atomic_text(index_path, index_html)

        readme_path = output / "README.md"
        _atomic_text(
            readme_path,
            "# DANTE-Light O4b review export\n\n"
            "Open `index.html` to inspect all 18 frozen escalation follow-ups.\n\n"
            "This directory repackages already-computed DANTE-Light final follow-up evidence. "
            "No manual response is required by the program, no score is recomputed, and no "
            "pipeline stage waits for a human decision. `candidate_summary.csv` provides the "
            "same cohort as a compact table.\n",
        )

        artifact_paths = [index_path, csv_path, readme_path]
        artifact_paths.extend(Path(item["packet_json"]) for item in rendered)
        artifact_paths.extend(Path(item["packet_html"]) for item in rendered)
        artifact_paths.extend(Path(item["candidate_image"]) for item in rendered)
        manifest_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "COMPLETE_STATIC_REVIEW_EXPORT",
            "telemetry_state_changed": False,
            "program_waits_for_manual_response": False,
            "source_telemetry_id": self.manifest["telemetry_id"],
            "contract_digest": self.contract["contract_digest"],
            "candidates": len(packets),
            "artifacts": [
                {
                    "path": str(path.relative_to(output)).replace("\\", "/"),
                    "sha256": sha256_file(path),
                }
                for path in sorted(artifact_paths)
            ],
        }
        export_manifest = {
            **manifest_body,
            "export_digest": canonical_json_sha256(manifest_body),
        }
        manifest_path = output / "export_manifest.json"
        _atomic_json(manifest_path, export_manifest)
        return {
            "status": export_manifest["status"],
            "candidates": len(packets),
            "output_dir": str(output),
            "index_html": str(index_path),
            "summary_csv": str(csv_path),
            "manifest": str(manifest_path),
            "export_digest": export_manifest["export_digest"],
            "telemetry_state_changed": False,
            "program_waits_for_manual_response": False,
        }

    def status(self) -> dict[str, Any]:
        state = self._state()
        counts = Counter(row["state"] for row in state.values())
        wait_s: list[float] = []
        service_s: list[float] = []
        cycle_s: list[float] = []
        completed_by_detector: Counter[str] = Counter()
        source_semantics: Counter[str] = Counter()
        review_days: set[str] = set()
        for row in state.values():
            events = {event["event_type"]: event for event in row["events"]}
            source_semantics[events["ENROLLED"]["source_semantics"]] += 1
            if "STARTED" in events:
                wait_s.append((events["STARTED"]["timestamp_unix_ns"] - events["ENROLLED"]["timestamp_unix_ns"]) / 1e9)
                review_days.add(events["STARTED"]["timestamp_utc"][:10])
            if "COMPLETED" in events:
                service_s.append((events["COMPLETED"]["timestamp_unix_ns"] - events["STARTED"]["timestamp_unix_ns"]) / 1e9)
                cycle_s.append((events["COMPLETED"]["timestamp_unix_ns"] - events["ENROLLED"]["timestamp_unix_ns"]) / 1e9)
                completed_by_detector[events["COMPLETED"]["detector"]] += 1
                review_days.add(events["COMPLETED"]["timestamp_utc"][:10])

        def describe(values: Iterable[float]) -> dict[str, Any]:
            array = np.asarray(list(values), dtype=np.float64)
            if not len(array):
                return {"count": 0, "median_s": None, "p90_s": None, "max_s": None}
            return {
                "count": int(len(array)),
                "median_s": float(median(array.tolist())),
                "p90_s": float(np.percentile(array, 90)),
                "max_s": float(np.max(array)),
            }

        return {
            "schema_version": SCHEMA_VERSION,
            "telemetry_id": self.manifest["telemetry_id"],
            "events": len(self.events),
            "enrolled": len(state),
            "queued": int(counts["ENROLLED"]),
            "in_progress": int(counts["STARTED"]),
            "completed": int(counts["COMPLETED"]),
            "completed_by_detector": dict(sorted(completed_by_detector.items())),
            "source_semantics": dict(sorted(source_semantics.items())),
            "observed_wait_from_enrollment": describe(wait_s),
            "operator_service_time": describe(service_s),
            "observed_cycle_from_enrollment": describe(cycle_s),
            "observed_review_day_blocks": len(review_days),
            "inference_status": "DESCRIPTIVE_ONLY_SUFFICIENCY_THRESHOLD_UNFROZEN",
            "operational_budget_freeze_allowed": False,
        }


def initialize_telemetry(
    telemetry_dir: str | Path,
    *,
    operator_id: str,
    source_dir: str | Path,
    source_semantics: str,
    contract_path: str | Path = DEFAULT_CONTRACT,
    require_historical_anchor: bool = False,
) -> tuple[ReviewTelemetryLedger, int]:
    contract = load_contract(contract_path)
    verify_contract_provenance(contract)
    ledger = ReviewTelemetryLedger(
        telemetry_dir,
        contract=contract,
        operator_id=operator_id,
        create=True,
    )
    enrolled = ledger.sync_source(
        source_dir,
        source_semantics=source_semantics,
        require_historical_anchor=require_historical_anchor,
    )
    return ledger, enrolled
