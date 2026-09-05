"""Administrative controller for the local workflow UI.

This module launches the existing workflow CLI in an independent process and
reads only durable, verified orchestration state. It never imports a scientific
stage implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import threading
from typing import Any

from ..adapters import AdapterError, WorkflowPaths
from ..orchestrator import OrchestrationError, WorkflowOrchestrator
from ..schema import WorkflowSchemaError, load_workflow_spec
from ..state import WorkflowStateError
from ..processes import process_alive
from ..reporting import WorkflowReportingError, verify_report_file


def spawn_worker(command, **options):
    """Separate injectable launch boundary; never patch the global subprocess module."""
    return subprocess.Popen(command, **options)


class UIControlError(RuntimeError):
    """Raised when a UI control cannot preserve the workflow contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False


@dataclass(frozen=True, slots=True)
class UISelection:
    repository_root: Path
    config_path: Path
    raw_root: Path
    cache_root: Path
    workflow_root: Path | None

    def __post_init__(self) -> None:
        for name in ("repository_root", "config_path", "raw_root", "cache_root"):
            object.__setattr__(self, name, getattr(self, name).resolve())
        if self.workflow_root is not None:
            object.__setattr__(self, "workflow_root", self.workflow_root.resolve())


@dataclass(frozen=True, slots=True)
class LocalPathPolicy:
    repository_root: Path
    raw_roots: tuple[Path, ...]
    cache_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_root", self.repository_root.resolve())
        object.__setattr__(
            self, "raw_roots", tuple(path.resolve() for path in self.raw_roots)
        )
        object.__setattr__(
            self, "cache_roots", tuple(path.resolve() for path in self.cache_roots)
        )
        if not self.raw_roots or not self.cache_roots:
            raise ValueError("path policy requires raw and cache roots")

    def validate(self, selection: UISelection) -> None:
        if selection.repository_root != self.repository_root:
            raise UIControlError("the repository selector is outside the approved project")
        try:
            selection.config_path.relative_to(self.repository_root)
        except ValueError as exc:
            raise UIControlError("the workflow config escapes the approved project") from exc
        if not _inside(selection.raw_root, self.raw_roots):
            raise UIControlError("the raw-data selector is outside the allowlist")
        if not _inside(selection.cache_root, self.cache_roots):
            raise UIControlError("the cache selector is outside the allowlist")
        if selection.workflow_root is not None and not _inside(
            selection.workflow_root, self.cache_roots
        ):
            raise UIControlError("the workflow selector is outside the cache allowlist")


class WorkflowUIController:
    """Own UI configuration while leaving worker ownership to the ledger."""

    def __init__(
        self,
        *,
        selection: UISelection,
        path_policy: LocalPathPolicy,
        worker_python: str = sys.executable,
    ) -> None:
        if not worker_python.strip():
            raise ValueError("worker Python must be non-empty")
        self.path_policy = path_policy
        self.worker_python = worker_python
        self._lock = threading.RLock()
        self._selection = selection
        self.path_policy.validate(selection)
        self._orchestrator = self._build_orchestrator(selection)

    @property
    def selection(self) -> UISelection:
        return self._selection

    @property
    def orchestrator(self) -> WorkflowOrchestrator:
        return self._orchestrator

    def _build_orchestrator(self, selection: UISelection) -> WorkflowOrchestrator:
        spec = load_workflow_spec(
            selection.config_path, root=selection.repository_root
        )
        return WorkflowOrchestrator.corrected_o4a(
            spec=spec,
            paths=WorkflowPaths(
                repository_root=selection.repository_root,
                raw_root=selection.raw_root,
                cache_root=selection.cache_root,
            ),
            workflow_root=selection.workflow_root,
        )

    def select(
        self,
        *,
        repository_root: str,
        raw_root: str,
        cache_root: str,
        workflow_root: str,
    ) -> dict[str, Any]:
        with self._lock:
            if self.worker_state()["state"] != "IDLE":
                raise UIControlError("paths cannot change while a worker lease is active")
            candidate = UISelection(
                repository_root=Path(repository_root),
                config_path=self.selection.config_path,
                raw_root=Path(raw_root),
                cache_root=Path(cache_root),
                workflow_root=Path(workflow_root) if workflow_root.strip() else None,
            )
            self.path_policy.validate(candidate)
            try:
                replacement = self._build_orchestrator(candidate)
            except (
                AdapterError,
                OrchestrationError,
                WorkflowSchemaError,
                WorkflowStateError,
            ) as exc:
                raise UIControlError(str(exc)) from exc
            self._selection = candidate
            self._orchestrator = replacement
            return self.public_status()

    def _worker_executable(self) -> str:
        candidate = Path(self.worker_python)
        if candidate.is_absolute():
            if not candidate.is_file():
                raise UIControlError(f"worker Python is absent: {candidate}")
            return str(candidate)
        resolved = shutil.which(self.worker_python)
        if resolved is None:
            raise UIControlError(f"worker Python is not executable: {self.worker_python}")
        return resolved

    @property
    def _event_path(self) -> Path:
        return self.orchestrator.run_dir / "ui" / "controller_events.jsonl"

    @property
    def _launch_path(self) -> Path:
        return self.orchestrator.run_dir / "ui" / "launch.lock"

    def _record_event(self, event: str, **details: Any) -> None:
        allowed = {"WORKER_LAUNCHED", "STOP_REQUESTED"}
        if event not in allowed:
            raise ValueError("unknown UI controller event")
        payload = {
            "schema_version": 1,
            "timestamp": _utc_now(),
            "event": event,
            "run_key": self.orchestrator.run_key,
            **details,
        }
        self._event_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        descriptor = os.open(
            self._event_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
        )
        try:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise OSError("short append to UI controller log")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def administrative_logs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self._event_path.is_file():
            return []
        try:
            lines = self._event_path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in lines[-limit:]]
        except (OSError, json.JSONDecodeError) as exc:
            raise UIControlError("the UI controller log is corrupt") from exc
        if any(not isinstance(event, dict) for event in events):
            raise UIControlError("the UI controller log is malformed")
        # Never reflect arbitrary fields from a locally modified log into HTTP.
        return [
            {key: event[key] for key in ("timestamp", "event", "pid", "action", "mode")
             if key in event}
            for event in events
            if event.get("run_key") == self.orchestrator.run_key
            and event.get("event") in {"WORKER_LAUNCHED", "STOP_REQUESTED"}
        ]

    @staticmethod
    def _process_alive(pid: int) -> bool:
        return process_alive(pid)

    def worker_state(self) -> dict[str, Any]:
        with self._lock:
            return self._worker_state()

    def _read_launch(self) -> dict[str, Any]:
        launch = json.loads(self._launch_path.read_text(encoding="utf-8"))
        if (
            not isinstance(launch, dict)
            or launch.get("run_key") != self.orchestrator.run_key
            or launch.get("schema_version") != 1
        ):
            raise ValueError("launch reservation identity differs")
        for key in ("launcher_pid", "pid"):
            if key == "pid" and key not in launch:
                continue
            pid = launch.get(key)
            if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                raise ValueError("launch reservation process identity is invalid")
        return launch

    def _worker_state(self) -> dict[str, Any]:
        lease_path = self.orchestrator.ledger.lease_path
        if lease_path.is_file():
            try:
                lease = json.loads(lease_path.read_text(encoding="utf-8"))
                process = lease["process"]
                pid = process["pid"]
                hostname = process["hostname"]
                if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
                    raise ValueError
                alive = (
                    self._process_alive(pid)
                    if hostname == socket.gethostname()
                    else None
                )
                if alive is False and self._launch_path.is_file():
                    launch = self._read_launch()
                    if launch.get("pid") == pid:
                        self._launch_path.unlink(missing_ok=True)
                return {
                    "state": "ACTIVE" if alive is not False else "STALE_LEASE",
                    "pid": pid,
                    "hostname": hostname,
                    "stop_requested": self.orchestrator.stop_request_path.is_file(),
                }
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                return {"state": "CORRUPT_LEASE", "stop_requested": False}
        if self._launch_path.is_file():
            try:
                launch = self._read_launch()
                pid = launch.get("pid")
                if pid is None:
                    owner = launch.get("launcher_pid")
                    if not isinstance(owner, int) or self._process_alive(owner):
                        return {"state": "LAUNCHING", "stop_requested": False}
                    # Parent may have died after spawning but before recording the
                    # child PID. Do not infer that no child exists or launch twice.
                    return {"state": "STALE_LAUNCH", "stop_requested": False}
                elif (
                    isinstance(pid, int)
                    and not isinstance(pid, bool)
                    and self._process_alive(pid)
                ):
                    return {
                        "state": "ACTIVE" if self.orchestrator.ledger.read_events() else "LAUNCHING",
                        "pid": pid,
                        "stop_requested": False,
                    }
                self._launch_path.unlink(missing_ok=True)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                return {"state": "CORRUPT_LAUNCH", "stop_requested": False}
        return {
            "state": "IDLE",
            "stop_requested": self.orchestrator.stop_request_path.is_file(),
        }

    def public_status(self) -> dict[str, Any]:
        with self._lock:
            value = self.orchestrator.status()
            value["worker"] = self.worker_state()
            return value

    def require_run_key(self, expected: str) -> None:
        if expected != self.orchestrator.run_key:
            raise UIControlError("this page refers to a different run; reload before acting")

    @contextmanager
    def control(self, expected_run_key: str):
        """Keep run selection stable from form validation through mutation."""
        with self._lock:
            self.require_run_key(expected_run_key)
            yield

    def plan(self) -> dict[str, Any]:
        return self.orchestrator.plan()

    def scientific_configs(self) -> list[dict[str, str]]:
        return [
            {
                "name": name,
                "path": reference.path,
                "sha256": reference.sha256,
            }
            for name, reference in sorted(
                self.orchestrator.spec.scientific_configs.items()
            )
        ]

    def local_preflight(self) -> dict[str, Any]:
        selection = self.selection
        python_ok = True
        try:
            worker_python = self._worker_executable()
        except UIControlError:
            python_ok = False
            worker_python = self.worker_python
        checks = [
            {
                "name": "Repository",
                "verdict": "PASS" if selection.repository_root.is_dir() else "FAIL",
                "detail": str(selection.repository_root),
            },
            {
                "name": "Workflow config",
                "verdict": "PASS" if selection.config_path.is_file() else "FAIL",
                "detail": str(selection.config_path),
            },
            {
                "name": "Raw data",
                "verdict": "PASS" if selection.raw_root.is_dir() else "FAIL",
                "detail": str(selection.raw_root),
            },
            {
                "name": "Cache write access",
                "verdict": (
                    "PASS"
                    if selection.cache_root.is_dir()
                    and os.access(selection.cache_root, os.W_OK)
                    else "FAIL"
                ),
                "detail": str(selection.cache_root),
            },
            {
                "name": "Worker Python",
                "verdict": "PASS" if python_ok else "FAIL",
                "detail": worker_python,
            },
            {
                "name": "Git",
                "verdict": "PASS" if shutil.which("git") else "FAIL",
                "detail": shutil.which("git") or "not found",
            },
            {
                "name": "CUDA command",
                "verdict": "PASS" if shutil.which("nvidia-smi") else "CHECK",
                "detail": shutil.which("nvidia-smi") or "scientific PREFLIGHT required",
            },
        ]
        return {
            "status": (
                "READY"
                if all(check["verdict"] != "FAIL" for check in checks)
                else "BLOCKED"
            ),
            "platform": platform.platform(),
            "checks": checks,
            "note": "The workflow PREFLIGHT stage remains the authoritative hardware and dependency gate.",
        }

    def launch(self, action: str) -> dict[str, Any]:
        if action not in {"start", "resume", "preflight", "verify"}:
            raise UIControlError("unsupported worker action")
        with self._lock:
            worker = self.worker_state()
            if worker["state"] != "IDLE" and not (
                action == "resume" and worker["state"] == "STALE_LEASE"
            ):
                raise UIControlError("a worker lease is already present for this run")
            events_exist = bool(self.orchestrator.ledger.read_events())
            if action == "start" and events_exist:
                raise UIControlError("existing evidence requires Resume, not Start")
            if action == "resume" and not events_exist:
                raise UIControlError("no prior evidence exists; use Start")
            if action == "verify" and self.orchestrator.ledger.next_incomplete_stage() is not None:
                raise UIControlError("complete the workflow before final verification")
            if self.local_preflight()["status"] != "READY":
                raise UIControlError("local launcher preflight is blocked")
            self.orchestrator.clear_stop_request()
            executable = self._worker_executable()
            self._launch_path.parent.mkdir(parents=True, exist_ok=True)
            reservation = {
                "schema_version": 1,
                "status": "WORKER_LAUNCH_RESERVED",
                "run_key": self.orchestrator.run_key,
                "created_at": _utc_now(),
                "launcher_pid": os.getpid(),
            }
            try:
                descriptor = os.open(
                    self._launch_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError as exc:
                raise UIControlError("a worker launch is already reserved") from exc
            try:
                payload = (json.dumps(reservation, sort_keys=True) + "\n").encode(
                    "utf-8"
                )
                written = os.write(descriptor, payload)
                if written != len(payload):
                    raise OSError("short write to worker launch reservation")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            selection = self.selection
            command = [
                executable,
                str(selection.repository_root / "scripts/run_dante_workflow.py"),
                "preflight" if action == "preflight" else "report",
                "--config",
                str(selection.config_path),
                "--repository-root",
                str(selection.repository_root),
                "--raw-root",
                str(selection.raw_root),
                "--cache-root",
                str(selection.cache_root),
                "--expected-run-key",
                self.orchestrator.run_key,
            ]
            if selection.workflow_root is not None:
                command.extend(("--workflow-root", str(selection.workflow_root)))
            log_dir = self.orchestrator.run_dir / "ui" / "worker"
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout_path = log_dir / "worker.stdout.sealed.txt"
            stderr_path = log_dir / "worker.stderr.sealed.txt"
            environment = os.environ.copy()
            executable_parent = str(Path(executable).resolve().parent)
            environment["PATH"] = executable_parent + os.pathsep + environment.get(
                "PATH", ""
            )
            popen_options: dict[str, Any] = {
                "cwd": str(selection.repository_root),
                "stdin": subprocess.DEVNULL,
                "env": environment,
                "close_fds": True,
            }
            if os.name == "nt":
                popen_options["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                )
            else:
                popen_options["start_new_session"] = True
            try:
                with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
                    process = spawn_worker(
                        command,
                        stdout=stdout,
                        stderr=stderr,
                        **popen_options,
                    )
            except OSError as exc:
                self._launch_path.unlink(missing_ok=True)
                raise UIControlError("the independent worker could not be started") from exc
            reservation["status"] = "WORKER_LAUNCHING"
            reservation["pid"] = process.pid
            temporary = self._launch_path.with_name(
                f".{self._launch_path.name}.{os.getpid()}.tmp"
            )
            try:
                temporary.write_text(
                    json.dumps(reservation, sort_keys=True) + "\n", encoding="utf-8"
                )
                temporary.replace(self._launch_path)
            finally:
                temporary.unlink(missing_ok=True)
            self._record_event("WORKER_LAUNCHED", action=action, pid=process.pid)
            return {
                "status": "WORKER_LAUNCHED",
                "action": action,
                "pid": process.pid,
                "run_key": self.orchestrator.run_key,
            }

    def request_stop(self) -> dict[str, Any]:
        with self._lock:
            try:
                request = self.orchestrator.request_stop()
            except OrchestrationError as exc:
                raise UIControlError(str(exc)) from exc
            self._record_event("STOP_REQUESTED", mode="AFTER_CURRENT_STAGE")
            return request

    def verified_artifact(self, stage: str, name: str) -> Path:
        try:
            receipt = self.orchestrator.ledger.latest_verified_artifact(stage, name)
            path = Path(receipt.path)
            if not path.is_absolute():
                path = self.orchestrator.run_dir / path
            return path.resolve(strict=True)
        except (KeyError, OSError, ValueError, WorkflowStateError) as exc:
            raise UIControlError("verified artifact is unavailable") from exc

    def _verified_stage_receipt(self, stage: str) -> dict[str, Any]:
        if stage not in self.orchestrator.spec.topological_stage_names():
            raise UIControlError("unknown stage")
        for name in self.orchestrator.spec.stage(stage).expected_outputs:
            try:
                path = self.verified_artifact(stage, name)
                value = json.loads(path.read_text(encoding="utf-8"))
            except (UIControlError, OSError, json.JSONDecodeError):
                continue
            if (
                isinstance(value, dict)
                and value.get("status") == "VERIFIED_STAGE_RECEIPT"
                and value.get("stage") == stage
                and value.get("run_key") == self.orchestrator.run_key
            ):
                return value
        raise UIControlError("verified stage receipt is unavailable")

    def verified_log(self, stage: str, name: str, *, max_bytes: int = 200_000) -> str:
        allowed = {
            "run.stdout.txt",
            "run.stderr.txt",
            "verify.stdout.txt",
            "verify.stderr.txt",
        }
        if name not in allowed:
            raise UIControlError("unknown verified log")
        receipt = self._verified_stage_receipt(stage)
        try:
            record = receipt["logs"][name]
            path = Path(record["path"]).resolve(strict=True)
            expected = record["sha256"]
        except (KeyError, OSError, TypeError) as exc:
            raise UIControlError("verified log record is malformed") from exc
        if _sha256_file(path) != expected:
            raise UIControlError("verified log digest mismatch")
        payload = path.read_bytes()
        prefix = b""
        if len(payload) > max_bytes:
            payload = payload[-max_bytes:]
            prefix = b"[earlier verified log content omitted]\n"
        return (prefix + payload).decode("utf-8", errors="replace")

    def report_path(self) -> Path:
        try:
            return verify_report_file(self.orchestrator)
        except WorkflowReportingError as exc:
            raise UIControlError(str(exc)) from exc
