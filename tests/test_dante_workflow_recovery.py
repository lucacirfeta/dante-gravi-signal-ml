"""P5 fault injection: isolated storage/processes, no network/CUDA/science runs."""

import errno
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from src.dante_workflow.adapters import O4aCorrectedAdapter, WorkflowPaths
from src.dante_workflow.orchestrator import CommandResult, OrchestrationError, WorkflowOrchestrator
from src.dante_workflow.schema import load_workflow_spec
from src.dante_workflow.state import ArtifactReceipt, ContractMismatchError, WorkflowLedger

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dante_workflow_productization_v1.json"


def make_workflow(directory, runner):
    spec = load_workflow_spec(CONFIG, root=ROOT)
    return WorkflowOrchestrator(
        spec=spec, adapter=O4aCorrectedAdapter(spec),
        paths=WorkflowPaths(repository_root=ROOT, raw_root=directory / "raw", cache_root=directory / "cache"),
        workflow_root=directory / "workflow", runner=runner,
        source_identity={"fixture": "recovery-only-no-scientific-execution"},
    )


@pytest.mark.parametrize("failure", ["network", "cuda", "dependency", "disk", "verifier"])
def test_transient_failure_preserves_evidence_and_resumes_same_identity(tmp_path, failure):
    calls = []

    def failing(command):
        calls.append((command.stage, command.action))
        if command.stage == "ACQUIRE":
            if failure == "disk":
                raise OSError(errno.ENOSPC, "injected disk pressure")
            if failure == "network":
                raise subprocess.TimeoutExpired(command.argv, timeout=1)
            if failure != "verifier" or command.action == "verify":
                return CommandResult(1, "sealed-outcome", f"injected {failure} failure")
        return CommandResult(0, "{}", "")

    workflow = make_workflow(tmp_path, failing)
    if failure in {"disk", "network"}:
        with pytest.raises(OrchestrationError, match="ACQUIRE"):
            workflow.execute(through_stage="CALIBRATE")
    else:
        result = workflow.execute(through_stage="CALIBRATE")
        assert result["results"][-1]["status"] == "FAILED"
    assert workflow.ledger.stage_status("PREFLIGHT") == "VERIFIED"
    assert workflow.ledger.stage_status("ACQUIRE") == "FAILED"
    assert workflow.ledger.stage_status("CALIBRATE") == "PENDING"
    assert not workflow.ledger.lease_path.exists()
    assert "sealed-outcome" not in json.dumps(workflow.status())
    before = workflow.ledger.event_path.read_bytes()
    failed_evidence = {path: path.read_bytes() for path in (workflow.run_dir / "attempts").rglob("*") if path.is_file()}
    calls.clear()

    def recovered(command):
        calls.append((command.stage, command.action))
        return CommandResult(0, "{}", "")

    resumed = make_workflow(tmp_path, recovered)
    result = resumed.execute(through_stage="CALIBRATE")
    assert resumed.run_key == workflow.run_key
    assert result["results"][0]["status"] == "SKIPPED_VERIFIED"
    assert calls == [("ACQUIRE", "run"), ("ACQUIRE", "verify"), ("CALIBRATE", "run"), ("CALIBRATE", "verify")]
    assert resumed.ledger.event_path.read_bytes().startswith(before)
    assert all(path.read_bytes() == data for path, data in failed_evidence.items())


@pytest.mark.parametrize("repair", [False, True])
def test_corrupt_verified_artifact_blocks_downstream_without_overwrite(tmp_path, repair):
    workflow = make_workflow(tmp_path, lambda cmd: CommandResult(0, "{}", ""))
    workflow.execute(through_stage="PREFLIGHT")
    artifact = workflow.ledger.latest_verified_artifact("PREFLIGHT", "preflight_receipt")
    Path(artifact.path).write_text("corrupt", encoding="utf-8")
    before = workflow.ledger.event_path.read_bytes()
    workflow.runner = lambda cmd: pytest.fail("corrupt predecessor must block execution")
    with pytest.raises((ContractMismatchError, OrchestrationError)):
        if repair:
            workflow.execute(repair_stage="ACQUIRE")
        else:
            workflow.execute(through_stage="ACQUIRE")
    assert Path(artifact.path).read_text(encoding="utf-8") == "corrupt"
    assert workflow.ledger.event_path.read_bytes().startswith(before)
    assert not workflow.ledger.lease_path.exists()


def test_real_worker_termination_recovers_stale_lease_append_only(tmp_path):
    directory = tmp_path / "isolated-ledger"
    worker = subprocess.Popen(
        [sys.executable, str(ROOT / "tests/fixtures/dante_workflow_failures/interrupted_worker.py"), str(directory)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while not (directory / "ready").exists() and time.monotonic() < deadline:
            assert worker.poll() is None, "fixture worker exited before recording its attempt"
            time.sleep(0.05)
        assert (directory / "ready").exists()
        spec = load_workflow_spec(CONFIG, root=ROOT)
        ledger = WorkflowLedger.open(directory, spec=spec, run_key="isolated-recovery-fixture")
        before = ledger.event_path.read_bytes()
        worker.terminate()
        worker.wait(timeout=5)
        lease = ledger.acquire_lease()
        assert ledger.stage_status("PREFLIGHT") == "INTERRUPTED"
        assert ledger.event_path.read_bytes().startswith(before)
        assert ledger.read_events()[-1]["reason"] == "STALE_WORKER_LEASE"
        attempt = ledger.start_attempt(lease, "PREFLIGHT")
        artifact = directory / "fixture-receipt.json"
        artifact.write_bytes(b"{}")
        ledger.record_artifact(lease, attempt, ArtifactReceipt(
            name="preflight_receipt", path=str(artifact), sha256=hashlib.sha256(b"{}").hexdigest(),
        ))
        ledger.finish_attempt(lease, attempt, exit_status=0, verifier_verdict="PASS")
        ledger.release_lease(lease)
        assert ledger.next_incomplete_stage() == "ACQUIRE"
    finally:
        if worker.poll() is None:
            worker.terminate()
        worker.wait(timeout=5)


def test_terminal_ledger_write_failure_can_resume_without_overwrite(tmp_path):
    workflow = make_workflow(tmp_path, lambda cmd: CommandResult(0, "{}", ""))
    append_event = workflow.ledger._append_event

    def fail_terminal_events(event):
        if event["event_type"] == "ATTEMPT_FINISHED":
            raise OSError(errno.ENOSPC, "injected terminal ledger failure")
        append_event(event)

    workflow.ledger._append_event = fail_terminal_events

    with pytest.raises(
        OrchestrationError, match="terminal state could not be persisted"
    ):
        workflow.execute(through_stage="PREFLIGHT")

    assert workflow.ledger.stage_status("PREFLIGHT") == "RUNNING"
    assert not workflow.ledger.lease_path.exists()
    evidence_before = workflow.ledger.event_path.read_bytes()

    resumed = make_workflow(tmp_path, lambda cmd: CommandResult(0, "{}", ""))
    result = resumed.execute(through_stage="PREFLIGHT")

    assert resumed.run_key == workflow.run_key
    assert result["results"][-1]["status"] == "VERIFIED"
    assert resumed.ledger.event_path.read_bytes().startswith(evidence_before)
    assert any(
        event.get("reason") == "ORPHANED_ATTEMPT_WITHOUT_LEASE"
        for event in resumed.ledger.read_events()
    )
    assert not resumed.ledger.lease_path.exists()
