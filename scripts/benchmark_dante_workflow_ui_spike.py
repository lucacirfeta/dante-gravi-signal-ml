#!/usr/bin/env python3
"""Measure UI startup, reconnect, and worker-lease independence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.adapters import WorkflowPaths  # noqa: E402
from src.dante_workflow.orchestrator import WorkflowOrchestrator  # noqa: E402
from src.dante_workflow.schema import load_workflow_spec  # noqa: E402


DEFAULT_CONFIG = ROOT / "config/dante_workflow_productization_v1.json"
SPIKE_SCRIPT = ROOT / "scripts/spike_dante_workflow_ui.py"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _get_json(
    url: str,
    *,
    timeout_s: float = 10.0,
    process: subprocess.Popen[str] | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with urlopen(url, timeout=0.5) as response:  # noqa: S310 - localhost
                value = json.loads(response.read().decode("utf-8"))
                if not isinstance(value, dict):
                    raise RuntimeError("UI spike returned a non-object JSON value")
                return value
        except (OSError, URLError):
            if process is not None and process.poll() is not None:
                stderr = process.stderr.read() if process.stderr is not None else ""
                raise RuntimeError(
                    f"UI spike exited before health check: {stderr.strip()}"
                )
            if time.monotonic() >= deadline:
                raise RuntimeError("UI spike did not become healthy before timeout")
            time.sleep(0.02)


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _launch_once(args: argparse.Namespace) -> dict[str, Any]:
    port = _free_port()
    command = [
        sys.executable,
        str(SPIKE_SCRIPT),
        "--config",
        str(args.config),
        "--repository-root",
        str(args.repository_root),
        "--raw-root",
        str(args.raw_root),
        "--cache-root",
        str(args.cache_root),
        "--workflow-root",
        str(args.workflow_root),
        "--port",
        str(port),
    ]
    started = time.perf_counter()
    process = subprocess.Popen(  # noqa: S603 - fixed local command
        command,
        cwd=args.repository_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        health = _get_json(
            f"http://127.0.0.1:{port}/health", process=process
        )
        startup_ms = (time.perf_counter() - started) * 1000.0
        status = _get_json(f"http://127.0.0.1:{port}/api/status")
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:  # noqa: S310
            page_status = int(response.status)
            page_bytes = len(response.read())
        return {
            "startup_ms": round(startup_ms, 1),
            "health": health,
            "status": status,
            "page_status": page_status,
            "page_bytes": page_bytes,
        }
    finally:
        _stop(process)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--workflow-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.repository_root = args.repository_root.resolve()
    args.config = args.config.resolve()
    args.raw_root = args.raw_root.resolve()
    args.cache_root = args.cache_root.resolve()
    args.workflow_root = args.workflow_root.resolve()
    spec = load_workflow_spec(args.config, root=args.repository_root)
    orchestrator = WorkflowOrchestrator.corrected_o4a(
        spec=spec,
        paths=WorkflowPaths(
            repository_root=args.repository_root,
            raw_root=args.raw_root,
            cache_root=args.cache_root,
        ),
        workflow_root=args.workflow_root,
    )
    lease = orchestrator.ledger.acquire_lease()
    try:
        first = _launch_once(args)
        lease_after_first_exit = orchestrator.ledger.lease_path.is_file()
        reconnect = _launch_once(args)
        lease_after_reconnect_exit = orchestrator.ledger.lease_path.is_file()
    finally:
        orchestrator.ledger.release_lease(lease)
    first_status = first["status"]
    reconnect_status = reconnect["status"]
    result = {
        "schema_version": 1,
        "status": "PASS_UI_SPIKE_BENCHMARK",
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "first_startup_ms": first["startup_ms"],
        "reconnect_startup_ms": reconnect["startup_ms"],
        "same_run_key": first_status["run_key"] == reconnect_status["run_key"],
        "same_run_dir": first_status["run_dir"] == reconnect_status["run_dir"],
        "stage_count": len(first_status["stages"]),
        "next_incomplete_stage": first_status["next_incomplete_stage"],
        "page_status": first["page_status"],
        "page_bytes": first["page_bytes"],
        "worker_lease_survived_first_ui_exit": lease_after_first_exit,
        "worker_lease_survived_reconnect_exit": lease_after_reconnect_exit,
    }
    if not all(
        (
            result["same_run_key"],
            result["same_run_dir"],
            result["stage_count"] == 15,
            result["page_status"] == 200,
            result["worker_lease_survived_first_ui_exit"],
            result["worker_lease_survived_reconnect_exit"],
        )
    ):
        raise RuntimeError("UI spike benchmark did not preserve workflow identity")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
