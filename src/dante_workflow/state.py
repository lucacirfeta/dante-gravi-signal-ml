"""Durable append-only execution state for DANTE workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
from typing import Any
from uuid import uuid4

from .schema import WorkflowSpec


STATE_SCHEMA_VERSION = 1
_SHA256_LENGTH = 64
_EVENT_TYPES = {
    "ATTEMPT_STARTED",
    "ARTIFACT_RECORDED",
    "ATTEMPT_FINISHED",
    "ATTEMPT_INTERRUPTED",
}
_VERIFIER_VERDICTS = {"PASS", "FAIL", "NOT_RUN"}


class WorkflowStateError(RuntimeError):
    """Base error for durable workflow state."""


class ContractMismatchError(WorkflowStateError):
    """Raised when persisted evidence does not match the requested run."""


class ConcurrentExecutionError(WorkflowStateError):
    """Raised when another live worker owns the workflow run."""


class InvalidTransitionError(WorkflowStateError):
    """Raised when an attempt would bypass a dependency or overwrite evidence."""


def _valid_sha256(value: str) -> bool:
    return len(value) == _SHA256_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_create_json(path: Path, value: Mapping[str, Any]) -> bool:
    """Create a complete JSON file without replacing an existing identity."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    hostname: str
    started_at: str
    token: str

    def __post_init__(self) -> None:
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise ValueError("process pid must be a positive integer")
        for label, value in (
            ("hostname", self.hostname),
            ("started_at", self.started_at),
            ("token", self.token),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"process {label} must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "hostname": self.hostname,
            "started_at": self.started_at,
            "token": self.token,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProcessIdentity":
        if set(value) != {"pid", "hostname", "started_at", "token"}:
            raise ContractMismatchError("persisted process identity is malformed")
        try:
            return cls(
                pid=value["pid"],
                hostname=value["hostname"],
                started_at=value["started_at"],
                token=value["token"],
            )
        except (TypeError, ValueError) as exc:
            raise ContractMismatchError("persisted process identity is malformed") from exc


@dataclass(frozen=True, slots=True)
class ArtifactReceipt:
    name: str
    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("artifact name must be non-empty")
        if not isinstance(self.path, str) or not self.path.strip():
            raise ValueError("artifact path must be non-empty")
        if not isinstance(self.sha256, str) or not _valid_sha256(self.sha256):
            raise ValueError("artifact digest must be a lowercase SHA-256")

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "path": self.path, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ExecutionLease:
    process: ProcessIdentity
    acquired_at: str


@dataclass(frozen=True, slots=True)
class AttemptHandle:
    stage: str
    attempt_id: str
    process_token: str


class WorkflowLedger:
    """Append-only workflow evidence plus a single durable worker lease.

    One worker owns a run key at a time. That worker may execute independent
    stages concurrently, including an artifact-gated stage while its producer
    is still active. The UI never owns this lease.
    """

    def __init__(
        self,
        run_dir: Path,
        *,
        spec: WorkflowSpec,
        run_key: str,
        run_identity: Mapping[str, Any],
        clock: Callable[[], datetime],
    ) -> None:
        self.run_dir = run_dir
        self.spec = spec
        self.run_key = run_key
        self.run_identity = dict(run_identity)
        self._clock = clock
        self.identity_path = run_dir / "run_identity.json"
        self.event_path = run_dir / "attempts.jsonl"
        self.lease_path = run_dir / "worker.lock"

    @classmethod
    def open(
        cls,
        run_dir: Path,
        *,
        spec: WorkflowSpec,
        run_key: str,
        clock: Callable[[], datetime] | None = None,
    ) -> "WorkflowLedger":
        if not isinstance(run_key, str) or not run_key.strip():
            raise ValueError("run_key must be non-empty")
        run_dir = run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        clock_function = clock or (lambda: datetime.now(timezone.utc))
        identity_path = run_dir / "run_identity.json"
        if identity_path.is_file():
            identity = cls._read_json(identity_path, "run identity")
        else:
            proposed_identity = {
                "schema_version": STATE_SCHEMA_VERSION,
                "status": "WORKFLOW_RUN_IDENTITY",
                "workflow_id": spec.workflow_id,
                "run_key": run_key,
                "contract_digest": spec.contract_digest,
                "created_at": cls._timestamp(clock_function),
            }
            if _atomic_create_json(identity_path, proposed_identity):
                identity = proposed_identity
            else:
                identity = cls._read_json(identity_path, "run identity")
        expected = {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "WORKFLOW_RUN_IDENTITY",
            "workflow_id": spec.workflow_id,
            "run_key": run_key,
            "contract_digest": spec.contract_digest,
        }
        if set(identity) != {*expected, "created_at"} or any(
            identity.get(key) != value for key, value in expected.items()
        ):
            raise ContractMismatchError(
                "persisted run identity does not match workflow contract or run key"
            )
        if not isinstance(identity.get("created_at"), str):
            raise ContractMismatchError("persisted run identity timestamp is malformed")
        ledger = cls(
            run_dir,
            spec=spec,
            run_key=run_key,
            run_identity=identity,
            clock=clock_function,
        )
        ledger.read_events()
        return ledger

    @staticmethod
    def _timestamp(clock: Callable[[], datetime]) -> str:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("workflow clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _read_json(path: Path, label: str) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractMismatchError(f"persisted {label} is corrupt") from exc
        if not isinstance(value, dict):
            raise ContractMismatchError(f"persisted {label} is malformed")
        return value

    def _event(
        self,
        event_type: str,
        *,
        process: ProcessIdentity,
        stage: str,
        attempt_id: str,
        **details: Any,
    ) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "event_id": uuid4().hex,
            "event_type": event_type,
            "timestamp": self._timestamp(self._clock),
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "contract_digest": self.spec.contract_digest,
            "stage": stage,
            "attempt_id": attempt_id,
            "process": process.to_dict(),
            **details,
        }

    def _append_event(self, event: Mapping[str, Any]) -> None:
        payload = _json_bytes(event)
        descriptor = os.open(
            self.event_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise OSError("short append to workflow event ledger")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def read_events(self) -> list[dict[str, Any]]:
        if not self.event_path.exists():
            return []
        events: list[dict[str, Any]] = []
        event_ids: set[str] = set()
        active_attempts: dict[str, dict[str, Any]] = {}
        seen_attempts: set[str] = set()
        try:
            lines = self.event_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError("event is not an object")
                common_keys = {
                    "schema_version",
                    "event_id",
                    "event_type",
                    "timestamp",
                    "workflow_id",
                    "run_key",
                    "contract_digest",
                    "stage",
                    "attempt_id",
                    "process",
                }
                event_type = event.get("event_type")
                detail_keys = {
                    "ATTEMPT_STARTED": set(),
                    "ARTIFACT_RECORDED": {"artifact"},
                    "ATTEMPT_FINISHED": {"exit_status", "verifier_verdict"},
                    "ATTEMPT_INTERRUPTED": {"reason"},
                }.get(event_type, set())
                if (
                    event.get("schema_version") != STATE_SCHEMA_VERSION
                    or event.get("workflow_id") != self.spec.workflow_id
                    or event.get("run_key") != self.run_key
                    or event.get("contract_digest") != self.spec.contract_digest
                    or event.get("event_type") not in _EVENT_TYPES
                    or event.get("stage") not in {
                        stage.name for stage in self.spec.stages
                    }
                    or not isinstance(event.get("attempt_id"), str)
                    or not isinstance(event.get("event_id"), str)
                    or not isinstance(event.get("timestamp"), str)
                    or event["event_id"] in event_ids
                    or set(event) != common_keys | detail_keys
                ):
                    raise ValueError("event identity is invalid")
                process = ProcessIdentity.from_dict(event.get("process", {}))
                attempt_id = event["attempt_id"]
                if event_type == "ATTEMPT_STARTED":
                    if attempt_id in seen_attempts:
                        raise ValueError("attempt identity is reused")
                    seen_attempts.add(attempt_id)
                    active_attempts[attempt_id] = event
                else:
                    started = active_attempts.get(attempt_id)
                    if (
                        started is None
                        or started["stage"] != event["stage"]
                        or started["process"]["token"] != process.token
                    ):
                        raise ValueError("event does not belong to an active attempt")
                    if event_type == "ARTIFACT_RECORDED":
                        artifact = event.get("artifact")
                        if not isinstance(artifact, Mapping):
                            raise ValueError("artifact receipt is malformed")
                        ArtifactReceipt(
                            name=artifact.get("name"),
                            path=artifact.get("path"),
                            sha256=artifact.get("sha256"),
                        )
                    elif event_type == "ATTEMPT_FINISHED":
                        exit_status = event.get("exit_status")
                        verdict = event.get("verifier_verdict")
                        if (
                            isinstance(exit_status, bool)
                            or not isinstance(exit_status, int)
                            or verdict not in _VERIFIER_VERDICTS
                            or (verdict == "PASS" and exit_status != 0)
                        ):
                            raise ValueError("attempt finish is malformed")
                        active_attempts.pop(attempt_id)
                    else:
                        if not isinstance(event.get("reason"), str):
                            raise ValueError("attempt interruption is malformed")
                        active_attempts.pop(attempt_id)
                event_ids.add(event["event_id"])
                events.append(event)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ContractMismatchError(
                f"corrupt event ledger: {self.event_path}"
            ) from exc
        return events

    @staticmethod
    def current_process(clock: Callable[[], datetime] | None = None) -> ProcessIdentity:
        clock_function = clock or (lambda: datetime.now(timezone.utc))
        return ProcessIdentity(
            pid=os.getpid(),
            hostname=socket.gethostname(),
            started_at=WorkflowLedger._timestamp(clock_function),
            token=uuid4().hex,
        )

    @staticmethod
    def _default_process_alive(process: ProcessIdentity) -> bool:
        if process.hostname != socket.gethostname():
            return True
        try:
            os.kill(process.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
        return True

    def _lease_payload(self, lease: ExecutionLease) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "ACTIVE_WORKER_LEASE",
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "contract_digest": self.spec.contract_digest,
            "acquired_at": lease.acquired_at,
            "process": lease.process.to_dict(),
        }

    def _create_lease_file(self, lease: ExecutionLease) -> bool:
        try:
            descriptor = os.open(
                self.lease_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
        except FileExistsError:
            return False
        try:
            payload = _json_bytes(self._lease_payload(lease))
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return True

    def _read_lease(self) -> ExecutionLease:
        value = self._read_json(self.lease_path, "worker lease")
        expected = {
            "schema_version": STATE_SCHEMA_VERSION,
            "status": "ACTIVE_WORKER_LEASE",
            "workflow_id": self.spec.workflow_id,
            "run_key": self.run_key,
            "contract_digest": self.spec.contract_digest,
        }
        if set(value) != {*expected, "acquired_at", "process"} or any(
            value.get(key) != expected_value for key, expected_value in expected.items()
        ):
            raise ContractMismatchError("persisted worker lease does not match this run")
        if not isinstance(value.get("acquired_at"), str):
            raise ContractMismatchError("persisted worker lease timestamp is malformed")
        return ExecutionLease(
            process=ProcessIdentity.from_dict(value["process"]),
            acquired_at=value["acquired_at"],
        )

    def acquire_lease(
        self,
        *,
        process: ProcessIdentity | None = None,
        process_alive: Callable[[ProcessIdentity], bool] | None = None,
    ) -> ExecutionLease:
        owner = process or self.current_process(self._clock)
        is_alive = process_alive or self._default_process_alive
        lease = ExecutionLease(
            process=owner,
            acquired_at=self._timestamp(self._clock),
        )
        for _ in range(3):
            if self._create_lease_file(lease):
                return lease
            persisted = self._read_lease()
            if is_alive(persisted.process):
                raise ConcurrentExecutionError(
                    "workflow run key is already active in another worker"
                )
            for attempt in self._active_attempts().values():
                old_process = ProcessIdentity.from_dict(attempt["process"])
                self._append_event(
                    self._event(
                        "ATTEMPT_INTERRUPTED",
                        process=old_process,
                        stage=attempt["stage"],
                        attempt_id=attempt["attempt_id"],
                        reason="STALE_WORKER_LEASE",
                    )
                )
            try:
                self.lease_path.unlink()
            except FileNotFoundError:
                continue
        raise ConcurrentExecutionError("could not acquire workflow worker lease")

    def _assert_lease(self, lease: ExecutionLease) -> None:
        if not self.lease_path.is_file():
            raise ConcurrentExecutionError("workflow worker lease is absent")
        persisted = self._read_lease()
        if persisted != lease:
            raise ConcurrentExecutionError("workflow worker lease belongs to another process")

    def _active_attempts(self) -> dict[str, dict[str, Any]]:
        active: dict[str, dict[str, Any]] = {}
        for event in self.read_events():
            event_type = event["event_type"]
            attempt_id = event["attempt_id"]
            if event_type == "ATTEMPT_STARTED":
                active[attempt_id] = event
            elif event_type in {"ATTEMPT_FINISHED", "ATTEMPT_INTERRUPTED"}:
                active.pop(attempt_id, None)
        return active

    def _assert_active_attempt(
        self, lease: ExecutionLease, attempt: AttemptHandle
    ) -> dict[str, Any]:
        self._assert_lease(lease)
        if attempt.process_token != lease.process.token:
            raise ConcurrentExecutionError("attempt belongs to another worker lease")
        active = self._active_attempts().get(attempt.attempt_id)
        if active is None or active["stage"] != attempt.stage:
            raise InvalidTransitionError("attempt is not active")
        return active

    def _attempt_terminal_events(self) -> dict[str, dict[str, Any]]:
        terminal: dict[str, dict[str, Any]] = {}
        for event in self.read_events():
            if event["event_type"] in {"ATTEMPT_FINISHED", "ATTEMPT_INTERRUPTED"}:
                terminal[event["attempt_id"]] = event
        return terminal

    def _artifact_events(self, attempt_id: str | None = None) -> list[dict[str, Any]]:
        return [
            event
            for event in self.read_events()
            if event["event_type"] == "ARTIFACT_RECORDED"
            and (attempt_id is None or event["attempt_id"] == attempt_id)
        ]

    def _available_digested_artifact(self, stage: str, name: str) -> bool:
        terminal = self._attempt_terminal_events()
        active = self._active_attempts()
        for event in reversed(self._artifact_events()):
            if event["stage"] != stage or event["artifact"].get("name") != name:
                continue
            attempt_id = event["attempt_id"]
            if attempt_id in active:
                self._verify_recorded_artifact(event["artifact"])
                return True
            finished = terminal.get(attempt_id)
            if (
                finished is not None
                and finished["event_type"] == "ATTEMPT_FINISHED"
                and finished.get("exit_status") == 0
                and finished.get("verifier_verdict") == "PASS"
            ):
                self._verify_recorded_artifact(event["artifact"])
                return True
        return False

    def start_attempt(self, lease: ExecutionLease, stage: str) -> AttemptHandle:
        self._assert_lease(lease)
        try:
            stage_spec = self.spec.stage(stage)
        except KeyError as exc:
            raise InvalidTransitionError(f"unknown workflow stage: {stage}") from exc
        if self.stage_status(stage) == "VERIFIED":
            raise InvalidTransitionError(f"stage {stage} is already verified")
        if any(event["stage"] == stage for event in self._active_attempts().values()):
            raise InvalidTransitionError(f"stage {stage} already has an active attempt")
        for dependency in stage_spec.dependencies:
            if dependency.gate == "VERIFIED_STAGE":
                if self.stage_status(dependency.stage) != "VERIFIED":
                    raise InvalidTransitionError(
                        f"stage {stage} requires verified {dependency.stage}"
                    )
            elif not self._available_digested_artifact(
                dependency.stage, str(dependency.artifact)
            ):
                raise InvalidTransitionError(
                    f"stage {stage} requires content-digested "
                    f"{dependency.stage} artifact {dependency.artifact}"
                )
        attempt = AttemptHandle(
            stage=stage,
            attempt_id=uuid4().hex,
            process_token=lease.process.token,
        )
        self._append_event(
            self._event(
                "ATTEMPT_STARTED",
                process=lease.process,
                stage=stage,
                attempt_id=attempt.attempt_id,
            )
        )
        return attempt

    def _resolve_artifact_path(self, receipt: ArtifactReceipt) -> Path:
        path = Path(receipt.path)
        if path.is_absolute():
            return path.resolve()
        resolved = (self.run_dir / path).resolve()
        try:
            resolved.relative_to(self.run_dir)
        except ValueError as exc:
            raise ContractMismatchError("relative artifact path escapes the run directory") from exc
        return resolved

    def _verify_recorded_artifact(self, value: Mapping[str, Any]) -> Path:
        try:
            receipt = ArtifactReceipt(
                name=value["name"],
                path=value["path"],
                sha256=value["sha256"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractMismatchError("persisted artifact receipt is malformed") from exc
        path = self._resolve_artifact_path(receipt)
        if not path.is_file():
            raise ContractMismatchError(f"artifact file is absent: {path}")
        actual = _file_sha256(path)
        if actual != receipt.sha256:
            raise ContractMismatchError(
                f"artifact digest mismatch for {receipt.name}: {actual} != {receipt.sha256}"
            )
        return path

    def record_artifact(
        self,
        lease: ExecutionLease,
        attempt: AttemptHandle,
        receipt: ArtifactReceipt,
    ) -> None:
        self._assert_active_attempt(lease, attempt)
        expected = set(self.spec.stage(attempt.stage).expected_outputs)
        if receipt.name not in expected:
            raise InvalidTransitionError(
                f"artifact {receipt.name!r} is not declared by stage {attempt.stage}"
            )
        if any(
            event["artifact"].get("name") == receipt.name
            for event in self._artifact_events(attempt.attempt_id)
        ):
            raise InvalidTransitionError(
                f"artifact {receipt.name!r} is already recorded for this attempt"
            )
        self._verify_recorded_artifact(receipt.to_dict())
        normalized_path = str(self._resolve_artifact_path(receipt))
        for event in self._artifact_events():
            previous = event["artifact"]
            previous_path = str(
                self._resolve_artifact_path(
                    ArtifactReceipt(
                        name=previous["name"],
                        path=previous["path"],
                        sha256=previous["sha256"],
                    )
                )
            )
            if previous_path == normalized_path and previous["sha256"] != receipt.sha256:
                raise ContractMismatchError(
                    "artifact path would overwrite preserved attempt evidence"
                )
        self._append_event(
            self._event(
                "ARTIFACT_RECORDED",
                process=lease.process,
                stage=attempt.stage,
                attempt_id=attempt.attempt_id,
                artifact=receipt.to_dict(),
            )
        )

    def finish_attempt(
        self,
        lease: ExecutionLease,
        attempt: AttemptHandle,
        *,
        exit_status: int,
        verifier_verdict: str,
    ) -> None:
        self._assert_active_attempt(lease, attempt)
        if isinstance(exit_status, bool) or not isinstance(exit_status, int):
            raise ValueError("exit_status must be an integer")
        if verifier_verdict not in _VERIFIER_VERDICTS:
            raise ValueError("invalid verifier verdict")
        if verifier_verdict == "PASS" and exit_status != 0:
            raise InvalidTransitionError(
                "PASS verifier verdict requires a successful exit status"
            )
        if exit_status == 0 and verifier_verdict == "PASS":
            artifact_events = self._artifact_events(attempt.attempt_id)
            recorded = {event["artifact"]["name"] for event in artifact_events}
            expected = set(self.spec.stage(attempt.stage).expected_outputs)
            missing = sorted(expected - recorded)
            if missing:
                raise InvalidTransitionError(
                    f"stage {attempt.stage} is missing expected artifacts: {missing}"
                )
            for event in artifact_events:
                self._verify_recorded_artifact(event["artifact"])
        self._append_event(
            self._event(
                "ATTEMPT_FINISHED",
                process=lease.process,
                stage=attempt.stage,
                attempt_id=attempt.attempt_id,
                exit_status=exit_status,
                verifier_verdict=verifier_verdict,
            )
        )

    def interrupt_attempt(
        self,
        lease: ExecutionLease,
        attempt: AttemptHandle,
        *,
        reason: str,
    ) -> None:
        self._assert_active_attempt(lease, attempt)
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("interruption reason must be non-empty")
        self._append_event(
            self._event(
                "ATTEMPT_INTERRUPTED",
                process=lease.process,
                stage=attempt.stage,
                attempt_id=attempt.attempt_id,
                reason=reason,
            )
        )

    def latest_verified_artifact(self, stage: str, name: str) -> ArtifactReceipt:
        self.spec.stage(stage)
        terminal = self._attempt_terminal_events()
        for event in reversed(self._artifact_events()):
            if event["stage"] != stage or event["artifact"]["name"] != name:
                continue
            finished = terminal.get(event["attempt_id"])
            if (
                finished is not None
                and finished["event_type"] == "ATTEMPT_FINISHED"
                and finished.get("exit_status") == 0
                and finished.get("verifier_verdict") == "PASS"
            ):
                self._verify_recorded_artifact(event["artifact"])
                return ArtifactReceipt(**event["artifact"])
        raise InvalidTransitionError(
            f"verified artifact {name!r} is unavailable from stage {stage}"
        )

    def stage_status(self, stage: str) -> str:
        self.spec.stage(stage)
        status = "PENDING"
        for event in self.read_events():
            if event["stage"] != stage:
                continue
            if event["event_type"] == "ATTEMPT_STARTED":
                status = "RUNNING"
            elif event["event_type"] == "ATTEMPT_INTERRUPTED":
                status = "INTERRUPTED"
            elif event["event_type"] == "ATTEMPT_FINISHED":
                status = (
                    "VERIFIED"
                    if event.get("exit_status") == 0
                    and event.get("verifier_verdict") == "PASS"
                    else "FAILED"
                )
        return status

    def next_incomplete_stage(self) -> str | None:
        for stage in self.spec.topological_stage_names():
            if self.stage_status(stage) != "VERIFIED":
                return stage
        return None

    def release_lease(self, lease: ExecutionLease) -> None:
        self._assert_lease(lease)
        active = [
            event
            for event in self._active_attempts().values()
            if event["process"].get("token") == lease.process.token
        ]
        if active:
            raise InvalidTransitionError("worker lease has active attempts")
        persisted = self._read_lease()
        if persisted != lease:
            raise ConcurrentExecutionError("workflow worker lease changed before release")
        self.lease_path.unlink()
