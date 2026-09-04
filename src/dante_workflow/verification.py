"""Aggregate existing stage verifiers into one content-signed receipt."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from .orchestrator import WorkflowOrchestrator
from .schema import canonical_json_sha256
from .state import ArtifactReceipt, ContractMismatchError


RELEASE_RECEIPT_NAME = "workflow_release_receipt.json"


class WorkflowVerificationError(RuntimeError):
    """Raised when the productized artifact graph does not verify."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowVerificationError(f"{label} is corrupt: {path}") from exc
    if not isinstance(value, dict):
        raise WorkflowVerificationError(f"{label} is not a JSON object: {path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    )
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise WorkflowVerificationError(f"{label} escapes the workflow run") from exc
    return resolved


def _validate_stage_receipt(
    orchestrator: WorkflowOrchestrator,
    *,
    stage: str,
    receipt: ArtifactReceipt,
) -> dict[str, Any]:
    path = _inside(Path(receipt.path), orchestrator.run_dir, "stage receipt")
    value = _load_json(path, f"{stage} stage receipt")
    required = {
        "schema_version",
        "status",
        "workflow_id",
        "run_key",
        "contract_digest",
        "stage",
        "attempt_id",
        "run_command_digest",
        "verify_command_digest",
        "run_exit_status",
        "verify_exit_status",
        "logs",
    }
    if set(value) != required and set(value) != required | {"verified_run_dir"}:
        raise WorkflowVerificationError(f"{stage} stage receipt fields changed")
    expected = {
        "schema_version": 1,
        "status": "VERIFIED_STAGE_RECEIPT",
        "workflow_id": orchestrator.spec.workflow_id,
        "run_key": orchestrator.run_key,
        "contract_digest": orchestrator.spec.contract_digest,
        "stage": stage,
        "run_command_digest": orchestrator.commands[stage]["run"].command_digest,
        "verify_command_digest": orchestrator.commands[stage][
            "verify"
        ].command_digest,
        "run_exit_status": 0,
        "verify_exit_status": 0,
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise WorkflowVerificationError(f"{stage} stage receipt identity is stale")
    if not isinstance(value.get("attempt_id"), str) or not value["attempt_id"]:
        raise WorkflowVerificationError(f"{stage} stage receipt attempt is absent")
    logs = value.get("logs")
    expected_logs = {
        "run.stdout.txt",
        "run.stderr.txt",
        "verify.stdout.txt",
        "verify.stderr.txt",
    }
    if not isinstance(logs, Mapping) or set(logs) != expected_logs:
        raise WorkflowVerificationError(f"{stage} stage receipt logs are incomplete")
    for name, log in logs.items():
        if not isinstance(log, Mapping) or set(log) != {"path", "sha256"}:
            raise WorkflowVerificationError(f"{stage} log receipt is malformed")
        log_path = _inside(Path(str(log["path"])), orchestrator.run_dir, f"{stage} log")
        if not log_path.is_file() or _sha256_file(log_path) != log["sha256"]:
            raise WorkflowVerificationError(f"{stage} log receipt digest mismatch")
        if log_path.name != name:
            raise WorkflowVerificationError(f"{stage} log receipt name mismatch")
    return {
        "path": str(path),
        "sha256": receipt.sha256,
        **(
            {"verified_run_dir": value["verified_run_dir"]}
            if "verified_run_dir" in value
            else {}
        ),
    }


def verify_workflow(orchestrator: WorkflowOrchestrator) -> dict[str, Any]:
    """Fail closed unless the full artifact graph and every verifier pass."""

    stage_receipts: list[dict[str, Any]] = []
    manifests: dict[str, ArtifactReceipt] = {}
    for stage in orchestrator.spec.topological_stage_names():
        if orchestrator.ledger.stage_status(stage) != "VERIFIED":
            raise WorkflowVerificationError(f"required stage is not verified: {stage}")
        artifacts: list[dict[str, str]] = []
        wrapper: dict[str, Any] | None = None
        for output in orchestrator.spec.stage(stage).expected_outputs:
            try:
                artifact = orchestrator.ledger.latest_verified_artifact(stage, output)
            except ContractMismatchError as exc:
                raise WorkflowVerificationError(
                    f"{stage} artifact failed content verification"
                ) from exc
            artifacts.append(artifact.to_dict())
            if output in {"native_cohort_manifest", "index_window_manifest"}:
                manifests[output] = artifact
            else:
                checked = _validate_stage_receipt(
                    orchestrator, stage=stage, receipt=artifact
                )
                if wrapper is None:
                    wrapper = checked
                elif wrapper != checked:
                    raise WorkflowVerificationError(
                        f"{stage} outputs do not share one verified stage receipt"
                    )
        verifier = orchestrator.runner(orchestrator.commands[stage]["verify"])
        if verifier.exit_status != 0:
            raise WorkflowVerificationError(f"stage verifier failed: {stage}")
        stage_receipts.append(
            {
                "stage": stage,
                "verifier_command_digest": orchestrator.commands[stage][
                    "verify"
                ].command_digest,
                "verifier_exit_status": verifier.exit_status,
                "artifacts": artifacts,
                **({"stage_receipt": wrapper} if wrapper is not None else {}),
            }
        )

    cohort = manifests.get("native_cohort_manifest")
    consumed = manifests.get("index_window_manifest")
    if cohort is None or consumed is None:
        raise WorkflowVerificationError("INDEX consumption manifests are incomplete")
    if cohort.sha256 != consumed.sha256 or Path(cohort.path).resolve() != Path(
        consumed.path
    ).resolve():
        raise WorkflowVerificationError(
            "INDEX did not consume the exact verified COHORT manifest"
        )

    body = {
        "schema_version": 1,
        "status": "PASS_VERIFIED_WORKFLOW",
        "workflow_id": orchestrator.spec.workflow_id,
        "run_key": orchestrator.run_key,
        "contract_digest": orchestrator.spec.contract_digest,
        "source_identity": orchestrator.source_identity,
        "artifact_graph_digest": canonical_json_sha256(stage_receipts),
        "stages": stage_receipts,
        "scientific_boundary": {
            "existing_stage_verifiers_replayed": True,
            "metrics_transcribed": False,
            "outcomes_interpreted": False,
            "index_consumption_manifest_exact_match": True,
        },
    }
    release = {**body, "receipt_digest": canonical_json_sha256(body)}
    path = orchestrator.run_dir / RELEASE_RECEIPT_NAME
    if path.is_file():
        if _load_json(path, "workflow release receipt") != release:
            raise WorkflowVerificationError(
                "existing workflow release receipt differs from verified evidence"
            )
    else:
        _atomic_json(path, release)
    return {**release, "receipt_path": str(path), "receipt_sha256": _sha256_file(path)}


def verify_release_receipt(path: Path) -> dict[str, Any]:
    """Verify the self digest of an already generated release receipt."""

    value = _load_json(path.resolve(), "workflow release receipt")
    body = dict(value)
    declared = body.pop("receipt_digest", None)
    if declared != canonical_json_sha256(body):
        raise WorkflowVerificationError("workflow release receipt digest mismatch")
    if value.get("status") != "PASS_VERIFIED_WORKFLOW":
        raise WorkflowVerificationError("workflow release receipt is not PASS")
    return value
