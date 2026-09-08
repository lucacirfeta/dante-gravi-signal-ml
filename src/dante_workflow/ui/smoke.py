"""Detached controller for the bounded public technical smoke."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any
from uuid import uuid4

from ..processes import process_alive
from .controller import UIControlError, spawn_worker


_DEVICES = {"cpu", "cuda"}
_ACTIONS = {"run": "local", "verify": "verify"}
_LOG_NAMES = {"stdout.log", "stderr.log", "failure.json"}
_LOG_SUFFIXES = (".stdout.txt", ".stderr.txt")
_LOG_TAIL_BYTES = 8192


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_object(output: str) -> dict[str, Any]:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise UIControlError("technical smoke returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise UIControlError("technical smoke returned non-object JSON")
    return value


@dataclass(frozen=True, slots=True)
class PublicSmokeUISettings:
    repository_root: Path
    worker_python: str = sys.executable
    secret_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_root", self.repository_root.resolve())


class PublicSmokeUIController:
    """Launch the public-smoke CLI without importing its scientific code."""

    def __init__(self, settings: PublicSmokeUISettings) -> None:
        if not settings.worker_python.strip():
            raise ValueError("worker Python must be non-empty")
        self.settings = settings
        self.runner = (
            settings.repository_root / "scripts/run_dante_workflow_clean_clone.py"
        )
        if not self.runner.is_file():
            raise UIControlError("public technical smoke runner is absent")
        self._hardware_cache: dict[str, Any] | None = None

    def _worker_executable(self) -> str:
        candidate = Path(self.settings.worker_python)
        if candidate.is_absolute():
            if not candidate.is_file():
                raise UIControlError(f"worker Python is absent: {candidate}")
            return str(candidate)
        resolved = shutil.which(self.settings.worker_python)
        if resolved is None:
            raise UIControlError(
                f"worker Python is not executable: {self.settings.worker_python}"
            )
        return resolved

    def _command(self, mode: str, device: str) -> list[str]:
        if device not in _DEVICES:
            raise UIControlError("unsupported technical smoke device")
        return [
            self._worker_executable(),
            str(self.runner),
            "--mode",
            mode,
            "--device",
            device,
        ]

    def hardware_status(self) -> dict[str, Any]:
        """Recommend a device from the worker environment, never from outcomes."""
        if self._hardware_cache is not None:
            return dict(self._hardware_cache)
        value: dict[str, Any] = {
            "cuda_available": False,
            "gpu_name": None,
            "recommended_device": "cpu",
            "reason": "CPU is the compatible default; no CUDA GPU was detected.",
        }
        if shutil.which("nvidia-smi") is not None:
            probe = (
                "import json, torch; "
                "ok=bool(torch.cuda.is_available()); "
                "print(json.dumps({'cuda_available':ok,'gpu_name':"
                "torch.cuda.get_device_name(0) if ok else None}))"
            )
            try:
                result = subprocess.run(
                    [self._worker_executable(), "-c", probe],
                    cwd=self.settings.repository_root,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    check=False,
                )
                detected = _json_object(result.stdout) if result.returncode == 0 else {}
            except (OSError, subprocess.SubprocessError, UIControlError):
                detected = {}
            if detected.get("cuda_available") is True:
                gpu_name = detected.get("gpu_name")
                value = {
                    "cuda_available": True,
                    "gpu_name": gpu_name if isinstance(gpu_name, str) else None,
                    "recommended_device": "cuda",
                    "reason": "CUDA is recommended because a compatible GPU is available.",
                }
        self._hardware_cache = value
        return dict(value)

    def _invoke(self, mode: str, device: str) -> dict[str, Any]:
        result = subprocess.run(  # noqa: S603 - fixed repository runner
            self._command(mode, device),
            cwd=self.settings.repository_root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        value = _json_object(result.stdout)
        if result.returncode != 0:
            message = str(value.get("error", "technical smoke command failed"))
            if message == "clean-clone evidence requires a tracked-clean checkout":
                message = (
                    "This technical smoke requires a tracked-clean checkout. "
                    "When using WSL, clone the repository inside the WSL home "
                    "filesystem; do not launch it from the shared /mnt/c checkout."
                )
            raise UIControlError(
                message
            )
        return value

    def plan(self, device: str) -> dict[str, Any]:
        value = self._invoke("plan", device)
        if value.get("status") != "SMOKE_PLAN":
            raise UIControlError("technical smoke plan has an unexpected status")
        run_key = value.get("run_key")
        if not isinstance(run_key, str) or len(run_key) != 64:
            raise UIControlError("technical smoke plan has an invalid identity")
        return value

    def _run_dir(self, run_key: str) -> Path:
        return (
            self.settings.repository_root
            / "artifacts/dante_workflow/public_smoke_v1"
            / run_key
        )

    @staticmethod
    def _is_log_file(path: Path) -> bool:
        return path.name in _LOG_NAMES or path.name.endswith(_LOG_SUFFIXES)

    def _log_path(self, run_key: str, relative_path: str) -> Path:
        root = self._run_dir(run_key).resolve()
        candidate = (root / relative_path).resolve()
        if (
            not candidate.is_relative_to(root)
            or not candidate.is_file()
            or candidate.is_symlink()
            or not self._is_log_file(candidate)
        ):
            raise UIControlError("technical smoke log is unavailable")
        return candidate

    def read_log(self, run_key: str, relative_path: str) -> Path:
        return self._log_path(run_key, relative_path)

    @staticmethod
    def _tail(path: Path) -> str:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - _LOG_TAIL_BYTES))
            return stream.read().decode("utf-8", errors="replace")

    def log_status(self, run_key: str) -> dict[str, Any]:
        root = self._run_dir(run_key)
        if not root.is_dir():
            return {"files": [], "active_tail": "", "active_name": None}
        entries: list[tuple[float, dict[str, Any], Path]] = []
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink() or not self._is_log_file(path):
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root.resolve()):
                continue
            stat = resolved.stat()
            relative = resolved.relative_to(root.resolve()).as_posix()
            entries.append(
                (
                    stat.st_mtime,
                    {
                        "path": relative,
                        "name": relative,
                        "size_bytes": stat.st_size,
                    },
                    resolved,
                )
            )
        entries.sort(key=lambda item: (item[0], item[1]["path"]), reverse=True)
        visible = entries[:20]
        active = next((item for item in visible if item[1]["size_bytes"]), None)
        return {
            "files": [item[1] for item in visible],
            "active_tail": self._tail(active[2]) if active else "",
            "active_name": active[1]["name"] if active else None,
        }

    def progress_status(
        self, run_key: str, *, worker: dict[str, Any], receipt_ready: bool
    ) -> dict[str, Any]:
        path = self._run_dir(run_key) / "progress.json"
        value: dict[str, Any] = {}
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = {}
            if isinstance(loaded, dict) and loaded.get("schema_version") == 1:
                value = loaded
        if receipt_ready and not value:
            value = {
                "status": "COMPLETE",
                "phase": "complete",
                "label": "Technical smoke verified",
                "detail": "The receipt and report are ready.",
                "completed_steps": 4,
                "total_steps": 4,
            }
        elif not value:
            running = worker.get("state") == "ACTIVE"
            value = {
                "status": "STARTING" if running else "NOT_STARTED",
                "phase": "launch" if running else "not_started",
                "label": "Starting worker" if running else "Ready to start",
                "detail": (
                    "The detached worker is preparing its first progress update."
                    if running
                    else "Choose a device and start the bounded two-window test."
                ),
                "completed_steps": 0,
                "total_steps": 4,
            }
        completed = value.get("completed_steps", 0)
        total = value.get("total_steps", 4)
        if isinstance(completed, bool) or not isinstance(completed, int):
            completed = 0
        if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
            total = 4
        completed = min(max(completed, 0), total)
        status = value.get("status")
        if worker.get("state") == "EXITED" and not receipt_ready and status == "RUNNING":
            status = "INTERRUPTED"
            value["label"] = "Worker stopped before verification"
            value["detail"] = "Use Resume test to continue from verified checkpoints."
        percent = round(100 * completed / total)
        eta_seconds = None
        started = value.get("started_at_unix")
        if (
            status == "RUNNING"
            and isinstance(started, (int, float))
            and not isinstance(started, bool)
            and completed > 0
            and completed < total
        ):
            elapsed = max(0.0, time.time() - float(started))
            eta_seconds = round((elapsed / completed) * (total - completed))
        return {
            "status": status,
            "phase": value.get("phase", "unknown"),
            "label": value.get("label", "Status unavailable"),
            "detail": value.get("detail", ""),
            "completed_steps": completed,
            "total_steps": total,
            "percent": percent,
            "eta_seconds": eta_seconds,
            "eta_is_approximate": eta_seconds is not None,
        }

    def _launch_path(self, run_key: str) -> Path:
        return self._run_dir(run_key) / "ui/launch.json"

    @staticmethod
    def _read_launch(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UIControlError("technical smoke launch record is corrupt") from exc
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise UIControlError("technical smoke launch record is malformed")
        return value

    def worker_state(self, run_key: str) -> dict[str, Any]:
        path = self._launch_path(run_key)
        if not path.is_file():
            return {"state": "IDLE"}
        launch = self._read_launch(path)
        if launch.get("run_key") != run_key:
            return {"state": "CORRUPT_LAUNCH"}
        pid = launch.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return {"state": "CORRUPT_LAUNCH"}
        state = "ACTIVE" if process_alive(pid) else "EXITED"
        return {
            "state": state,
            "pid": pid,
            "action": launch.get("action"),
            "stdout_path": launch.get("stdout_path"),
            "stderr_path": launch.get("stderr_path"),
        }

    def public_status(self, device: str) -> dict[str, Any]:
        plan = self.plan(device)
        run_key = plan["run_key"]
        receipt = self._run_dir(run_key) / "technical_receipt.json"
        worker = self.worker_state(run_key)
        state: dict[str, Any] = {
            "status": "PENDING_TECHNICAL_SMOKE",
            "scope": plan.get("scope"),
            "device": device,
            "run_key": run_key,
            "worker": worker,
            "receipt_sha256": None,
        }
        if receipt.is_file():
            try:
                verified = self._invoke("verify", device)
            except UIControlError:
                state["status"] = "INTEGRITY_ERROR"
            else:
                if verified.get("run_key") != run_key:
                    raise UIControlError("verified smoke identity changed")
                state["status"] = "VERIFIED_TECHNICAL_SMOKE"
                state["receipt_sha256"] = _sha256_file(receipt)
        state["progress"] = self.progress_status(
            run_key,
            worker=worker,
            receipt_ready=state["status"] == "VERIFIED_TECHNICAL_SMOKE",
        )
        state["logs"] = self.log_status(run_key)
        state["hardware"] = self.hardware_status()
        return state

    def launch(self, action: str, device: str, expected_run_key: str) -> dict[str, Any]:
        mode = _ACTIONS.get(action)
        if mode is None:
            raise UIControlError("unsupported technical smoke action")
        plan = self.plan(device)
        run_key = plan["run_key"]
        if expected_run_key != run_key:
            raise UIControlError("this page refers to a different smoke run; reload")
        launch_path = self._launch_path(run_key)
        launch_path.parent.mkdir(parents=True, exist_ok=True)
        if launch_path.is_file():
            worker = self.worker_state(run_key)
            if worker["state"] == "ACTIVE":
                raise UIControlError("technical smoke worker is already active")
            if worker["state"] != "EXITED":
                raise UIControlError(
                    "technical smoke launch record requires inspection"
                )
            launch_path.unlink()

        launch_id = uuid4().hex
        log_dir = launch_path.parent / "worker"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / f"{launch_id}.stdout.txt"
        stderr_path = log_dir / f"{launch_id}.stderr.txt"
        reservation = {
            "schema_version": 1,
            "status": "LAUNCH_RESERVED",
            "run_key": run_key,
            "device": device,
            "action": action,
            "launch_id": launch_id,
        }
        descriptor = os.open(launch_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        failed = False
        try:
            payload = (json.dumps(reservation, sort_keys=True) + "\n").encode()
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short write to technical smoke launch reservation")
            os.fsync(descriptor)
        except Exception:
            failed = True
            raise
        finally:
            os.close(descriptor)
            if failed:
                launch_path.unlink(missing_ok=True)

        options: dict[str, Any] = {
            "cwd": str(self.settings.repository_root),
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            options["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            options["start_new_session"] = True
        try:
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = spawn_worker(
                    self._command(mode, device),
                    stdout=stdout,
                    stderr=stderr,
                    **options,
                )
        except OSError as exc:
            launch_path.unlink(missing_ok=True)
            raise UIControlError("technical smoke worker could not be started") from exc

        reservation.update(
            {
                "status": "WORKER_LAUNCHED",
                "pid": process.pid,
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
        )
        temporary = launch_path.with_name(f".{launch_path.name}.{launch_id}.tmp")
        try:
            temporary.write_text(
                json.dumps(reservation, sort_keys=True) + "\n", encoding="utf-8"
            )
            temporary.replace(launch_path)
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "status": "WORKER_LAUNCHED",
            "pid": process.pid,
            "run_key": run_key,
            "device": device,
            "action": action,
        }
