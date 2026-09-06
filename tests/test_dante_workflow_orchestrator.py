from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest

from src.dante_workflow.adapters import O4aCorrectedAdapter, StageCommand, WorkflowPaths
from src.dante_workflow.orchestrator import (
    CommandResult,
    OrchestrationError,
    WorkflowOrchestrator,
)
from src.dante_workflow.schema import load_workflow_spec
from src.dante_workflow.state import InvalidTransitionError


ROOT = Path(__file__).resolve().parents[1]
SPEC = load_workflow_spec(
    ROOT / "config/dante_workflow_productization_v1.json", root=ROOT
)
SOURCE = {"git_head": "a" * 40, "tracked_worktree_diff_sha256": "b" * 64}


class FakeRunner:
    def __init__(self, artifact_root: Path, *, fail: tuple[str, str] | None = None):
        self.artifact_root = artifact_root
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.cohort_bytes = b'{"detector":"H1","gps_start":1}\n'

    def __call__(self, command: StageCommand) -> CommandResult:
        call = (command.stage, command.action)
        self.calls.append(call)
        if call == self.fail:
            return CommandResult(7, "sensitive-outcome", "synthetic failure")
        run_dir = self.artifact_root / command.stage.lower()
        run_dir.mkdir(parents=True, exist_ok=True)
        payload: dict[str, object] = {"run_dir": str(run_dir)}
        if call == ("COHORT", "verify"):
            ledger = run_dir / "native_cohort.jsonl"
            ledger.write_bytes(self.cohort_bytes)
            payload["ledger"] = {
                "filename": ledger.name,
                "sha256": hashlib.sha256(self.cohort_bytes).hexdigest(),
            }
        return CommandResult(0, json.dumps(payload), "")


def _orchestrator(
    tmp_path: Path,
    runner: FakeRunner,
    *,
    source: dict[str, str] | None = None,
) -> WorkflowOrchestrator:
    paths = WorkflowPaths(
        repository_root=ROOT,
        raw_root=tmp_path / "raw",
        cache_root=tmp_path / "cache",
    )
    return WorkflowOrchestrator(
        spec=SPEC,
        adapter=O4aCorrectedAdapter(SPEC),
        paths=paths,
        runner=runner,
        source_identity=source or SOURCE,
        workflow_root=tmp_path / "workflow-runs",
    )


def test_plan_exposes_frozen_fifteen_stage_dag_and_manifest_gate(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path, FakeRunner(tmp_path / "artifacts"))

    plan = orchestrator.plan()

    assert len(plan["stages"]) == 15
    native = next(
        stage for stage in plan["stages"] if stage["name"] == "NATIVE_CALIBRATION"
    )
    assert native["dependencies"] == [
        {"stage": "COHORT", "gate": "VERIFIED_STAGE"},
        {
            "stage": "INDEX",
            "gate": "CONTENT_DIGESTED_ARTIFACT",
            "artifact": "index_window_manifest",
        },
    ]


def test_corrected_factory_binds_stage_commands_to_current_python(
    tmp_path: Path,
) -> None:
    paths = WorkflowPaths(
        repository_root=ROOT,
        raw_root=tmp_path / "raw",
        cache_root=tmp_path / "cache",
    )
    orchestrator = WorkflowOrchestrator.corrected_o4a(
        spec=SPEC,
        paths=paths,
        source_identity=SOURCE,
        workflow_root=tmp_path / "workflow-runs",
    )

    assert {
        command.argv[0]
        for actions in orchestrator.commands.values()
        for command in actions.values()
    } == {sys.executable}


def test_execute_records_exact_index_consumption_before_native_calibration(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(tmp_path / "artifacts")
    orchestrator = _orchestrator(tmp_path, runner)

    result = orchestrator.execute(through_stage="NATIVE_CALIBRATION")

    assert [item["stage"] for item in result["results"]] == [
        "PREFLIGHT",
        "ACQUIRE",
        "CALIBRATE",
        "SCAN",
        "COHORT",
        "INDEX",
        "NATIVE_CALIBRATION",
    ]
    assert all(item["status"] == "VERIFIED" for item in result["results"])
    cohort = orchestrator.ledger.latest_verified_artifact(
        "COHORT", "native_cohort_manifest"
    )
    consumed = orchestrator.ledger.latest_verified_artifact(
        "INDEX", "index_window_manifest"
    )
    assert Path(cohort.path).read_bytes() == runner.cohort_bytes
    assert consumed.sha256 == cohort.sha256
    assert orchestrator.ledger.stage_status("NATIVE_CALIBRATION") == "VERIFIED"
    assert not orchestrator.ledger.lease_path.exists()


def test_adopt_verified_existing_replays_only_verifiers_and_records_mode(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(tmp_path / "artifacts")
    orchestrator = _orchestrator(tmp_path, runner)

    result = orchestrator.adopt_verified_existing()

    assert len(result["results"]) == 15
    assert all(
        item["status"] == "ADOPTED_VERIFIED_EXISTING"
        for item in result["results"]
    )
    assert all(action == "verify" for _, action in runner.calls)
    receipt = orchestrator.ledger.latest_verified_artifact(
        "PREFLIGHT", "preflight_receipt"
    )
    value = json.loads(Path(receipt.path).read_text(encoding="utf-8"))
    assert value["execution_mode"] == "ADOPTED_VERIFIED_EXISTING"
    assert value["run_command_executed"] is False
    assert value["run_exit_status"] is None
    assert (
        json.loads(
            Path(value["logs"]["run.stdout.txt"]["path"]).read_text(
                encoding="utf-8"
            )
        )["status"]
        == "RUN_COMMAND_NOT_EXECUTED"
    )
    cohort = orchestrator.ledger.latest_verified_artifact(
        "COHORT", "native_cohort_manifest"
    )
    consumed = orchestrator.ledger.latest_verified_artifact(
        "INDEX", "index_window_manifest"
    )
    assert Path(cohort.path).resolve() == Path(consumed.path).resolve()
    assert cohort.sha256 == consumed.sha256


def test_adoption_verifier_failure_stops_fail_closed(tmp_path: Path) -> None:
    runner = FakeRunner(
        tmp_path / "artifacts", fail=("CALIBRATE", "verify")
    )
    orchestrator = _orchestrator(tmp_path, runner)

    result = orchestrator.adopt_verified_existing(through_stage="SCAN")

    assert result["results"][-1] == {
        "stage": "CALIBRATE",
        "status": "FAILED",
        "phase": "verify-existing",
    }
    assert orchestrator.ledger.stage_status("CALIBRATE") == "FAILED"
    assert ("CALIBRATE", "run") not in runner.calls
    assert ("SCAN", "verify") not in runner.calls
    assert not orchestrator.ledger.lease_path.exists()


def test_repeated_execution_is_idempotent(tmp_path: Path) -> None:
    runner = FakeRunner(tmp_path / "artifacts")
    first = _orchestrator(tmp_path, runner)
    first.execute(through_stage="COHORT")
    calls_after_first = list(runner.calls)

    reopened = _orchestrator(tmp_path, runner)
    result = reopened.execute(through_stage="COHORT")

    assert runner.calls == calls_after_first
    assert all(item["status"] == "SKIPPED_VERIFIED" for item in result["results"])


def test_failure_stops_pipeline_and_status_does_not_expose_unverified_output(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(tmp_path / "artifacts", fail=("CALIBRATE", "run"))
    orchestrator = _orchestrator(tmp_path, runner)

    result = orchestrator.execute(through_stage="SCAN")

    assert result["results"][-1] == {
        "stage": "CALIBRATE",
        "status": "FAILED",
        "phase": "run",
    }
    assert orchestrator.ledger.stage_status("CALIBRATE") == "FAILED"
    calibrate = next(
        stage
        for stage in result["workflow_status"]["stages"]
        if stage["name"] == "CALIBRATE"
    )
    assert calibrate == {"name": "CALIBRATE", "status": "FAILED"}
    assert "sensitive-outcome" not in json.dumps(result)
    assert ("SCAN", "run") not in runner.calls


def test_single_stage_repair_cannot_bypass_dependencies(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, FakeRunner(tmp_path / "artifacts"))

    with pytest.raises(InvalidTransitionError, match="requires verified CALIBRATE"):
        orchestrator.execute(repair_stage="SCAN")

    assert not orchestrator.ledger.lease_path.exists()


def test_source_change_creates_a_new_content_addressed_run(tmp_path: Path) -> None:
    runner = FakeRunner(tmp_path / "artifacts")
    first = _orchestrator(tmp_path, runner)
    changed = _orchestrator(
        tmp_path,
        runner,
        source={"git_head": "c" * 40, "tracked_worktree_diff_sha256": "b" * 64},
    )

    assert changed.run_key != first.run_key
    assert changed.run_dir != first.run_dir


def test_verify_completed_replays_only_existing_verified_stages(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(tmp_path / "artifacts")
    orchestrator = _orchestrator(tmp_path, runner)
    orchestrator.execute(through_stage="ACQUIRE")
    runner.calls.clear()

    result = orchestrator.verify_completed()

    assert result["verdict"] == "PASS"
    assert runner.calls == [("PREFLIGHT", "verify"), ("ACQUIRE", "verify")]
    assert result["results"] == [
        {"stage": "PREFLIGHT", "verdict": "PASS", "exit_status": 0},
        {"stage": "ACQUIRE", "verdict": "PASS", "exit_status": 0},
    ]


def test_unknown_or_conflicting_stage_selection_fails_closed(tmp_path: Path) -> None:
    orchestrator = _orchestrator(tmp_path, FakeRunner(tmp_path / "artifacts"))

    with pytest.raises(OrchestrationError, match="unknown through stage"):
        orchestrator.execute(through_stage="NOPE")
    with pytest.raises(OrchestrationError, match="mutually exclusive"):
        orchestrator.execute(through_stage="SCAN", repair_stage="SCAN")


def test_cooperative_stop_finishes_current_stage_and_preserves_resume(
    tmp_path: Path,
) -> None:
    class StopAfterPreflightRunner(FakeRunner):
        orchestrator: WorkflowOrchestrator

        def __call__(self, command: StageCommand) -> CommandResult:
            result = super().__call__(command)
            if (command.stage, command.action) == ("PREFLIGHT", "verify"):
                self.orchestrator.request_stop()
            return result

    runner = StopAfterPreflightRunner(tmp_path / "artifacts")
    orchestrator = _orchestrator(tmp_path, runner)
    runner.orchestrator = orchestrator

    result = orchestrator.execute(through_stage="ACQUIRE")

    assert result["status"] == "WORKFLOW_EXECUTION_STOPPED"
    assert result["results"] == [{"stage": "PREFLIGHT", "status": "VERIFIED"}]
    assert orchestrator.ledger.stage_status("PREFLIGHT") == "VERIFIED"
    assert orchestrator.ledger.stage_status("ACQUIRE") == "PENDING"
    assert not orchestrator.ledger.lease_path.exists()
    assert not orchestrator.stop_request_path.exists()

    resumed = orchestrator.execute(through_stage="ACQUIRE")

    assert resumed["status"] == "WORKFLOW_EXECUTION"
    assert resumed["results"] == [
        {"stage": "PREFLIGHT", "status": "SKIPPED_VERIFIED"},
        {"stage": "ACQUIRE", "status": "VERIFIED"},
    ]
