from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.dante_workflow.adapters import O4aCorrectedAdapter, StageCommand, WorkflowPaths
from src.dante_workflow.orchestrator import CommandResult, WorkflowOrchestrator
from src.dante_workflow.schema import load_workflow_spec
from src.dante_workflow.verification import (
    WorkflowVerificationError,
    verify_release_receipt,
    verify_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
SPEC = load_workflow_spec(
    ROOT / "config/dante_workflow_productization_v1.json", root=ROOT
)
SOURCE = {"git_head": "a" * 40, "tracked_worktree_diff_sha256": "b" * 64}


class VerificationRunner:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.fail: tuple[str, str] | None = None

    def __call__(self, command: StageCommand) -> CommandResult:
        if (command.stage, command.action) == self.fail:
            return CommandResult(9, "", "failed")
        stage_dir = self.root / command.stage.lower()
        stage_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {
            "run_dir": str(stage_dir),
            "score_secret_not_for_receipt": 42,
        }
        if (command.stage, command.action) == ("COHORT", "verify"):
            content = b'{"detector":"H1","gps_start":1}\n'
            ledger = stage_dir / "native_cohort.jsonl"
            ledger.write_bytes(content)
            payload["ledger"] = {
                "filename": ledger.name,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        return CommandResult(0, json.dumps(payload), "")


def _orchestrator(tmp_path: Path) -> tuple[WorkflowOrchestrator, VerificationRunner]:
    runner = VerificationRunner(tmp_path / "scientific-artifacts")
    orchestrator = WorkflowOrchestrator(
        spec=SPEC,
        adapter=O4aCorrectedAdapter(SPEC),
        paths=WorkflowPaths(
            repository_root=ROOT,
            raw_root=tmp_path / "raw",
            cache_root=tmp_path / "cache",
        ),
        runner=runner,
        source_identity=SOURCE,
        workflow_root=tmp_path / "workflow-runs",
    )
    return orchestrator, runner


def _complete(tmp_path: Path) -> tuple[WorkflowOrchestrator, VerificationRunner]:
    orchestrator, runner = _orchestrator(tmp_path)
    execution = orchestrator.execute()
    assert all(item["status"] == "VERIFIED" for item in execution["results"])
    return orchestrator, runner


def test_full_graph_emits_deterministic_content_signed_receipt(tmp_path: Path) -> None:
    orchestrator, _ = _complete(tmp_path)

    first = verify_workflow(orchestrator)
    second = verify_workflow(orchestrator)

    assert first == second
    assert first["status"] == "PASS_VERIFIED_WORKFLOW"
    assert len(first["stages"]) == 15
    assert first["scientific_boundary"] == {
        "existing_stage_verifiers_replayed": True,
        "metrics_transcribed": False,
        "outcomes_interpreted": False,
        "index_consumption_manifest_exact_match": True,
    }
    assert "score_secret_not_for_receipt" not in json.dumps(first)
    persisted = verify_release_receipt(Path(first["receipt_path"]))
    assert persisted["receipt_digest"] == first["receipt_digest"]


def test_incomplete_workflow_cannot_emit_pass_receipt(tmp_path: Path) -> None:
    orchestrator, _ = _orchestrator(tmp_path)
    orchestrator.execute(through_stage="SCAN")

    with pytest.raises(WorkflowVerificationError, match="COHORT"):
        verify_workflow(orchestrator)


def test_changed_artifact_bytes_fail_content_verification(tmp_path: Path) -> None:
    orchestrator, _ = _complete(tmp_path)
    artifact = orchestrator.ledger.latest_verified_artifact(
        "PREFLIGHT", "preflight_receipt"
    )
    Path(artifact.path).write_text("changed", encoding="utf-8")

    with pytest.raises(WorkflowVerificationError, match="content verification"):
        verify_workflow(orchestrator)


def test_cross_run_stage_receipt_fails_even_with_rewritten_ledger_digest(
    tmp_path: Path,
) -> None:
    orchestrator, _ = _complete(tmp_path)
    artifact = orchestrator.ledger.latest_verified_artifact(
        "PREFLIGHT", "preflight_receipt"
    )
    path = Path(artifact.path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["run_key"] = "foreign-run"
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    changed_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    events = [
        json.loads(line)
        for line in orchestrator.ledger.event_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    for event in events:
        if (
            event["event_type"] == "ARTIFACT_RECORDED"
            and Path(event["artifact"]["path"]).resolve() == path.resolve()
        ):
            event["artifact"]["sha256"] = changed_sha
    orchestrator.ledger.event_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowVerificationError, match="identity is stale"):
        verify_workflow(orchestrator)


def test_index_manifest_must_be_same_path_and_bytes_as_cohort(tmp_path: Path) -> None:
    orchestrator, _ = _complete(tmp_path)
    cohort = orchestrator.ledger.latest_verified_artifact(
        "COHORT", "native_cohort_manifest"
    )
    copied = tmp_path / "copied-cohort.jsonl"
    copied.write_bytes(Path(cohort.path).read_bytes())
    events = [
        json.loads(line)
        for line in orchestrator.ledger.event_path.read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    for event in events:
        if (
            event["event_type"] == "ARTIFACT_RECORDED"
            and event["stage"] == "INDEX"
            and event["artifact"]["name"] == "index_window_manifest"
        ):
            event["artifact"]["path"] = str(copied)
    orchestrator.ledger.event_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )

    with pytest.raises(WorkflowVerificationError, match="exact verified COHORT"):
        verify_workflow(orchestrator)


def test_existing_stage_verifier_failure_blocks_release(tmp_path: Path) -> None:
    orchestrator, runner = _complete(tmp_path)
    runner.fail = ("PEM", "verify")

    with pytest.raises(WorkflowVerificationError, match="PEM"):
        verify_workflow(orchestrator)


def test_release_receipt_rejects_tampered_self_digest(tmp_path: Path) -> None:
    orchestrator, _ = _complete(tmp_path)
    release = verify_workflow(orchestrator)
    path = Path(release["receipt_path"])
    value = json.loads(path.read_text(encoding="utf-8"))
    value["run_key"] = "changed"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(WorkflowVerificationError, match="digest mismatch"):
        verify_release_receipt(path)
