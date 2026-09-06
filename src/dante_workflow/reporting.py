"""Render a human report from hash-bound, fully verified workflow evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
import hashlib
from pathlib import Path
from typing import Any
from uuid import uuid4

from .orchestrator import WorkflowOrchestrator
from .verification import verify_workflow, verify_release_receipt


class WorkflowReportingError(RuntimeError):
    """Raised when a PASS report cannot be derived from verified evidence."""


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise WorkflowReportingError("workflow event timestamp is malformed") from exc


def _stage_durations(orchestrator: WorkflowOrchestrator) -> dict[str, float]:
    starts: dict[str, datetime] = {}
    durations: dict[str, float] = {}
    for event in orchestrator.ledger.read_events():
        if event["event_type"] == "ATTEMPT_STARTED":
            starts[event["attempt_id"]] = _timestamp(event["timestamp"])
        elif event["event_type"] == "ATTEMPT_FINISHED" and event.get(
            "verifier_verdict"
        ) == "PASS":
            start = starts.get(event["attempt_id"])
            if start is None:
                raise WorkflowReportingError("verified attempt start is absent")
            durations[event["stage"]] = (
                _timestamp(event["timestamp"]) - start
            ).total_seconds()
    return durations


def _collect_exclusion_fields(
    value: Any, *, prefix: str = ""
) -> list[tuple[str, Any]]:
    fields: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, nested in sorted(value.items()):
            path = f"{prefix}.{key}" if prefix else str(key)
            lowered = str(key).lower()
            if isinstance(nested, (str, int, float, bool)) and any(
                marker in lowered
                for marker in ("excluded", "exclusion", "missing", "degraded")
            ):
                fields.append((path, nested))
            elif lowered == "invalid_or_silent_drop_count" and isinstance(
                nested, (int, float)
            ):
                fields.append((path, nested))
            fields.extend(_collect_exclusion_fields(nested, prefix=path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            fields.extend(
                _collect_exclusion_fields(nested, prefix=f"{prefix}[{index}]")
            )
    return fields


def _table_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True).replace("|", "\\|")


def _verified_payload(
    orchestrator: WorkflowOrchestrator, stage_receipt: Mapping[str, Any]
) -> dict[str, Any] | None:
    wrapper = stage_receipt.get("stage_receipt")
    if not isinstance(wrapper, Mapping):
        return None
    path = wrapper.get("path")
    if not isinstance(path, str):
        return None
    try:
        receipt = json.loads(Path(path).read_text(encoding="utf-8"))
        verify_log = Path(receipt["logs"]["verify.stdout.txt"]["path"])
        payload = json.loads(verify_log.read_text(encoding="utf-8"))
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise WorkflowReportingError(
            f"verified payload cannot be read for {stage_receipt.get('stage')}"
        ) from exc
    return payload if isinstance(payload, dict) else None


def build_workflow_report(orchestrator: WorkflowOrchestrator) -> str:
    """Return Markdown only after full graph re-verification succeeds."""

    try:
        release = verify_workflow(orchestrator)
    except Exception as exc:
        raise WorkflowReportingError(
            "a PASS report requires a complete, currently verified workflow"
        ) from exc
    durations = _stage_durations(orchestrator)
    lines = [
        "# DANTE workflow report",
        "",
        "## Verification",
        "",
        "- Status: `PASS_VERIFIED_WORKFLOW`",
        f"- Workflow: `{release['workflow_id']}`",
        f"- Run key: `{release['run_key']}`",
        f"- Contract digest: `{release['contract_digest']}`",
        f"- Artifact graph digest: `{release['artifact_graph_digest']}`",
        f"- Release receipt: [{Path(release['receipt_path']).name}](<{release['receipt_path']}>)",
        "",
        "## Scientific scope",
        "",
        "- The artifact graph and all existing stage verifiers passed.",
        "- Stages marked `ADOPTED_VERIFIED_EXISTING` were verifier-replayed from frozen artifacts; their scientific calculation commands were not executed by this workflow run.",
        "- Coincidence and PEM products remain diagnostic follow-up outputs.",
        "- No global-significance or discovery claim is made.",
        "- This workflow is not a public real-time or operational alerting system.",
        "- Missing or degraded inputs remain explicit and are not reinterpreted here as negative evidence.",
        "",
        "## Provenance",
        "",
    ]
    for key, value in sorted(release["source_identity"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Stages",
            "",
            "| Stage | Verdict | Mode | Duration (s) | Verified output |",
            "|---|---:|---|---:|---|",
        ]
    )
    for stage in release["stages"]:
        wrapper = stage.get("stage_receipt", {})
        target = wrapper.get("verified_run_dir") or wrapper.get("path") or ""
        link = f"[open](<{target}>)" if target else "n/a"
        mode = wrapper.get("execution_mode", "UNKNOWN")
        lines.append(
            f"| {stage['stage']} | PASS | `{mode}` | {durations[stage['stage']]:.3f} | {link} |"
        )

    exclusions: list[tuple[str, str, Any]] = []
    for stage in release["stages"]:
        payload = _verified_payload(orchestrator, stage)
        if payload is None:
            continue
        exclusions.extend(
            (stage["stage"], key, value)
            for key, value in _collect_exclusion_fields(payload)
        )
    lines.extend(
        [
            "",
            "## Exclusions and degraded-input accounting",
            "",
            "Values below are read directly from hash-bound verifier output; they are not manually transcribed.",
            "",
        ]
    )
    if exclusions:
        lines.extend(
            [
                "| Stage | Verified field | Value |",
                "|---|---|---:|",
                *[
                    f"| {stage} | `{key}` | `{_table_value(value)}` |"
                    for stage, key, value in exclusions
                ],
            ]
        )
    else:
        lines.append("No exclusion or degraded-input scalar was declared by the verifiers.")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This report is a derived navigation layer over verified artifacts. The scientific outputs remain the source of truth; this document neither recomputes nor reclassifies them.",
            "",
        ]
    )
    return "\n".join(lines)


def write_workflow_report(
    orchestrator: WorkflowOrchestrator, path: Path | None = None
) -> Path:
    """Atomically write the derived report after verification."""

    target = (path or orchestrator.run_dir / "workflow_report.md").resolve()
    report = build_workflow_report(orchestrator)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(report, encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    # Administrative binding of the derived text, not a new scientific verdict.
    receipt_path = orchestrator.run_dir / "workflow_release_receipt.json"
    binding = {
        "run_key": orchestrator.run_key,
        "report_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "release_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
    }
    binding_path = target.with_suffix(target.suffix + ".receipt.json")
    temporary = binding_path.with_name(f".{binding_path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(binding, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(binding_path)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def verify_report_file(orchestrator: WorkflowOrchestrator) -> Path:
    """Check stored report bytes and their evidence without running stage code.

    This is an HTTP read boundary, not a replacement for verify_workflow. The
    latter must have replayed all scientific verifiers before report creation.
    """
    target = orchestrator.run_dir / "workflow_report.md"
    receipt_path = orchestrator.run_dir / "workflow_release_receipt.json"
    try:
        release = verify_release_receipt(receipt_path)
        binding = json.loads(
            target.with_suffix(".md.receipt.json").read_text(encoding="utf-8")
        )
        expected = {
            "run_key": orchestrator.run_key,
            "report_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "release_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        }
        if binding != expected or release["run_key"] != orchestrator.run_key:
            raise ValueError("report binding differs")
        if [row["stage"] for row in release["stages"]] != list(
            orchestrator.spec.topological_stage_names()
        ):
            raise ValueError("report stage graph differs")
        for row in release["stages"]:
            stage = row["stage"]
            if orchestrator.ledger.stage_status(stage) != "VERIFIED":
                raise ValueError("report stage is no longer verified")
            current = [
                orchestrator.ledger.latest_verified_artifact(stage, name).to_dict()
                for name in orchestrator.spec.stage(stage).expected_outputs
            ]
            if row["artifacts"] != current:
                raise ValueError("report artifacts differ")
            wrapper = row.get("stage_receipt")
            if wrapper:
                value = json.loads(Path(wrapper["path"]).read_text(encoding="utf-8"))
                for log in value["logs"].values():
                    if hashlib.sha256(Path(log["path"]).read_bytes()).hexdigest() != log["sha256"]:
                        raise ValueError("report source log differs")
    except Exception as exc:
        raise WorkflowReportingError("stored report or its evidence is unavailable or altered") from exc
    return target.resolve()
