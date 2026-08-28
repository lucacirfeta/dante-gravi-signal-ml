"""Outcome-blind, append-only human-review telemetry for DANTE-Light v8.1.

This module measures queue waiting and operator service time.  It deliberately
does not implement prioritization, review outcomes, a top-X budget, a deadline,
or a readiness gate.  Those are separate scientific decisions.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
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
    return {
        "phase0_result": "PASS",
        "historical_scale_anchor": "PASS",
        "historical_escalations": len(source["escalations"]),
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
