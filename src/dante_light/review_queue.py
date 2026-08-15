"""Append-only, idempotent review records for DANTE-Light."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from src.dante_light.contracts import ContractError, canonical_json_sha256


class ReviewQueue:
    def __init__(self, output_dir: str | Path, run_manifest: dict[str, Any]):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.output_dir / "run_manifest.json"
        self.records_path = self.output_dir / "records.jsonl"
        self._manifest = dict(run_manifest)
        self._manifest["manifest_sha256"] = canonical_json_sha256(run_manifest)
        self._records_by_window: dict[str, dict[str, Any]] = {}
        self._open_or_create_manifest()
        self._load_records()

    def _atomic_json(self, path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def _open_or_create_manifest(self) -> None:
        if self.manifest_path.exists():
            existing = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if existing != self._manifest:
                raise ContractError(
                    "Cannot resume DANTE-Light queue with a divergent run manifest"
                )
            return
        self._atomic_json(self.manifest_path, self._manifest)

    def _load_records(self) -> None:
        if not self.records_path.exists():
            return
        for line_number, line in enumerate(
            self.records_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ContractError(
                    f"Incomplete review queue at line {line_number}; recover from "
                    "the last durable artifact rather than ignoring the tail"
                ) from exc
            declared = record.get("record_id")
            body = dict(record)
            body.pop("record_id", None)
            expected = f"dlr1-{canonical_json_sha256(body)[:24]}"
            if declared != expected:
                raise ContractError(f"Review record digest mismatch at line {line_number}")
            window_id = record["window"]["window_id"]
            previous = self._records_by_window.get(window_id)
            if previous is not None and previous != record:
                raise ContractError(f"Divergent duplicate review record for {window_id}")
            self._records_by_window[window_id] = record

    @property
    def completed_window_ids(self) -> frozenset[str]:
        return frozenset(self._records_by_window)

    def append(self, records: Iterable[dict[str, Any]]) -> int:
        pending: list[dict[str, Any]] = []
        for raw in records:
            body = dict(raw)
            body.pop("record_id", None)
            record = {
                **body,
                "record_id": f"dlr1-{canonical_json_sha256(body)[:24]}",
            }
            window_id = record["window"]["window_id"]
            previous = self._records_by_window.get(window_id)
            if previous is not None:
                if previous != record:
                    raise ContractError(
                        f"Divergent replay for completed window {window_id}"
                    )
                continue
            pending.append(record)

        if not pending:
            return 0
        with self.records_path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in pending:
                handle.write(
                    json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        for record in pending:
            self._records_by_window[record["window"]["window_id"]] = record
        return len(pending)

    def write_summary(self, summary: dict[str, Any]) -> None:
        body = dict(summary)
        attempt = {
            **body,
            "attempt_id": f"dla1-{canonical_json_sha256(body)[:24]}",
        }
        attempts_path = self.output_dir / "attempts.jsonl"
        with attempts_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(attempt, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._atomic_json(self.output_dir / "summary.json", summary)
