from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from src.dante_workflow.schema import load_workflow_spec
from src.dante_workflow.state import (
    ArtifactReceipt,
    ConcurrentExecutionError,
    ContractMismatchError,
    InvalidTransitionError,
    ProcessIdentity,
    WorkflowLedger,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/dante_workflow_productization_v1.json"


class IncrementingClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


def _process(pid: int, token: str) -> ProcessIdentity:
    return ProcessIdentity(
        pid=pid,
        hostname="test-host",
        started_at="2026-09-04T08:00:00Z",
        token=token,
    )


def _receipt(ledger: WorkflowLedger, name: str) -> ArtifactReceipt:
    path = ledger.run_dir / "artifacts" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode("utf-8"))
    return ArtifactReceipt(
        name=name,
        path=path.relative_to(ledger.run_dir).as_posix(),
        sha256=hashlib.sha256(name.encode("utf-8")).hexdigest(),
    )


@pytest.fixture
def spec():
    return load_workflow_spec(CONFIG_PATH, root=ROOT)


@pytest.fixture
def ledger(tmp_path: Path, spec):
    return WorkflowLedger.open(
        tmp_path / "workflow_run",
        spec=spec,
        run_key="test-run-key",
        clock=IncrementingClock(),
    )


def _complete_stage(
    ledger: WorkflowLedger,
    lease,
    name: str,
) -> None:
    attempt = ledger.start_attempt(lease, name)
    for output in ledger.spec.stage(name).expected_outputs:
        ledger.record_artifact(lease, attempt, _receipt(ledger, output))
    ledger.finish_attempt(
        lease,
        attempt,
        exit_status=0,
        verifier_verdict="PASS",
    )


def _complete_through(ledger: WorkflowLedger, lease, final_stage: str) -> None:
    for name in ledger.spec.topological_stage_names():
        _complete_stage(ledger, lease, name)
        if name == final_stage:
            return
    raise AssertionError(final_stage)


def test_run_identity_is_atomic_and_changed_contract_is_rejected(
    tmp_path: Path, spec
) -> None:
    run_dir = tmp_path / "workflow_run"
    first = WorkflowLedger.open(run_dir, spec=spec, run_key="stable-key")
    identity_before = (run_dir / "run_identity.json").read_bytes()

    reopened = WorkflowLedger.open(run_dir, spec=spec, run_key="stable-key")
    assert reopened.run_identity == first.run_identity
    assert (run_dir / "run_identity.json").read_bytes() == identity_before
    assert not list(run_dir.glob("*.tmp"))

    changed = replace(spec, contract_digest="0" * 64)
    with pytest.raises(ContractMismatchError, match="contract"):
        WorkflowLedger.open(run_dir, spec=changed, run_key="stable-key")


def test_attempt_ledger_persists_process_artifacts_exit_and_verdict(
    ledger: WorkflowLedger,
) -> None:
    process = _process(101, "worker-a")
    lease = ledger.acquire_lease(process=process, process_alive=lambda _: True)
    _complete_stage(ledger, lease, "PREFLIGHT")
    ledger.release_lease(lease)

    events = ledger.read_events()
    assert [event["event_type"] for event in events] == [
        "ATTEMPT_STARTED",
        "ARTIFACT_RECORDED",
        "ATTEMPT_FINISHED",
    ]
    assert all(event["run_key"] == "test-run-key" for event in events)
    assert all(event["contract_digest"] == ledger.spec.contract_digest for event in events)
    assert all(event["process"]["pid"] == 101 for event in events)
    assert events[1]["artifact"]["name"] == "preflight_receipt"
    assert events[1]["artifact"]["sha256"] == _receipt(
        ledger, "preflight_receipt"
    ).sha256
    assert events[2]["exit_status"] == 0
    assert events[2]["verifier_verdict"] == "PASS"
    assert ledger.stage_status("PREFLIGHT") == "VERIFIED"


def test_duplicate_live_worker_for_same_run_key_is_rejected(
    ledger: WorkflowLedger,
) -> None:
    ledger.acquire_lease(
        process=_process(101, "worker-a"),
        process_alive=lambda process: process.pid == 101,
    )

    with pytest.raises(ConcurrentExecutionError, match="already active"):
        ledger.acquire_lease(
            process=_process(202, "worker-b"),
            process_alive=lambda process: process.pid == 101,
        )


def test_stale_worker_recovery_is_append_only_and_resumes_first_incomplete(
    ledger: WorkflowLedger,
) -> None:
    old_lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    _complete_stage(ledger, old_lease, "PREFLIGHT")
    interrupted = ledger.start_attempt(old_lease, "ACQUIRE")
    ledger.record_artifact(
        old_lease,
        interrupted,
        _receipt(ledger, "acquisition_manifest"),
    )
    evidence_before = ledger.event_path.read_bytes()

    new_lease = ledger.acquire_lease(
        process=_process(202, "worker-b"), process_alive=lambda _: False
    )

    assert ledger.event_path.read_bytes().startswith(evidence_before)
    assert ledger.read_events()[-1]["event_type"] == "ATTEMPT_INTERRUPTED"
    assert ledger.next_incomplete_stage() == "ACQUIRE"
    assert ledger.stage_status("PREFLIGHT") == "VERIFIED"
    assert ledger.stage_status("ACQUIRE") == "INTERRUPTED"

    _complete_stage(ledger, new_lease, "ACQUIRE")
    assert ledger.next_incomplete_stage() == "CALIBRATE"


def test_worker_can_interrupt_attempt_explicitly(ledger: WorkflowLedger) -> None:
    lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    attempt = ledger.start_attempt(lease, "PREFLIGHT")

    ledger.interrupt_attempt(lease, attempt, reason="CONTROLLED_STOP")

    assert ledger.stage_status("PREFLIGHT") == "INTERRUPTED"
    assert ledger.read_events()[-1]["reason"] == "CONTROLLED_STOP"
    ledger.release_lease(lease)


def test_completed_stage_evidence_cannot_be_rewritten(ledger: WorkflowLedger) -> None:
    lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    _complete_stage(ledger, lease, "PREFLIGHT")

    with pytest.raises(InvalidTransitionError, match="already verified"):
        ledger.start_attempt(lease, "PREFLIGHT")


def test_native_calibration_can_use_early_digested_index_manifest(
    ledger: WorkflowLedger,
) -> None:
    lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    _complete_through(ledger, lease, "COHORT")

    index_attempt = ledger.start_attempt(lease, "INDEX")
    ledger.record_artifact(
        lease,
        index_attempt,
        _receipt(ledger, "index_window_manifest"),
    )
    native_attempt = ledger.start_attempt(lease, "NATIVE_CALIBRATION")
    for output in ledger.spec.stage("NATIVE_CALIBRATION").expected_outputs:
        ledger.record_artifact(lease, native_attempt, _receipt(ledger, output))
    ledger.finish_attempt(
        lease,
        native_attempt,
        exit_status=0,
        verifier_verdict="PASS",
    )

    with pytest.raises(InvalidTransitionError, match="verified INDEX"):
        ledger.start_attempt(lease, "RESCORE")

    for output in ledger.spec.stage("INDEX").expected_outputs:
        if output != "index_window_manifest":
            ledger.record_artifact(lease, index_attempt, _receipt(ledger, output))
    ledger.finish_attempt(
        lease,
        index_attempt,
        exit_status=0,
        verifier_verdict="PASS",
    )
    assert ledger.start_attempt(lease, "RESCORE").stage == "RESCORE"


def test_native_calibration_rejects_tampered_index_manifest(
    ledger: WorkflowLedger,
) -> None:
    lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    _complete_through(ledger, lease, "COHORT")
    index_attempt = ledger.start_attempt(lease, "INDEX")
    receipt = _receipt(ledger, "index_window_manifest")
    ledger.record_artifact(lease, index_attempt, receipt)
    (ledger.run_dir / receipt.path).write_text("changed", encoding="utf-8")

    with pytest.raises(ContractMismatchError, match="artifact digest mismatch"):
        ledger.start_attempt(lease, "NATIVE_CALIBRATION")


def test_latest_verified_artifact_excludes_unverified_attempt(
    ledger: WorkflowLedger,
) -> None:
    lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    attempt = ledger.start_attempt(lease, "PREFLIGHT")
    receipt = _receipt(ledger, "preflight_receipt")
    ledger.record_artifact(lease, attempt, receipt)
    with pytest.raises(InvalidTransitionError, match="unavailable"):
        ledger.latest_verified_artifact("PREFLIGHT", "preflight_receipt")

    ledger.finish_attempt(
        lease, attempt, exit_status=0, verifier_verdict="PASS"
    )
    assert ledger.latest_verified_artifact(
        "PREFLIGHT", "preflight_receipt"
    ) == receipt


def test_artifact_and_verifier_records_fail_closed(ledger: WorkflowLedger) -> None:
    lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    attempt = ledger.start_attempt(lease, "PREFLIGHT")

    with pytest.raises(ValueError, match="SHA-256"):
        ledger.record_artifact(
            lease,
            attempt,
            ArtifactReceipt("preflight_receipt", "receipt.json", "bad"),
        )
    with pytest.raises(InvalidTransitionError, match="missing expected artifacts"):
        ledger.finish_attempt(
            lease,
            attempt,
            exit_status=0,
            verifier_verdict="PASS",
        )
    with pytest.raises(InvalidTransitionError, match="successful exit"):
        ledger.finish_attempt(
            lease,
            attempt,
            exit_status=1,
            verifier_verdict="PASS",
        )


def test_worker_lease_cannot_be_released_with_active_attempt(
    ledger: WorkflowLedger,
) -> None:
    lease = ledger.acquire_lease(
        process=_process(101, "worker-a"), process_alive=lambda _: True
    )
    attempt = ledger.start_attempt(lease, "PREFLIGHT")

    with pytest.raises(InvalidTransitionError, match="active attempts"):
        ledger.release_lease(lease)

    ledger.record_artifact(lease, attempt, _receipt(ledger, "preflight_receipt"))
    ledger.finish_attempt(
        lease,
        attempt,
        exit_status=0,
        verifier_verdict="PASS",
    )
    ledger.release_lease(lease)
    assert not ledger.lease_path.exists()


def test_event_ledger_rejects_corrupt_lines(ledger: WorkflowLedger) -> None:
    ledger.event_path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(ContractMismatchError, match="corrupt event ledger"):
        ledger.read_events()
