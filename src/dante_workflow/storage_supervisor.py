"""One-shot I/O supervision with durable observed exits; never runs science."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

from .calibration_admission import _pinned
from .calibration_recovery import read_sealed
from .storage_probe import BOUNDARY, confined, load_policy, new_report, separate


def event(stream, **body):
    body["utc"] = datetime.now(timezone.utc).isoformat()
    stream.write(json.dumps(body, sort_keys=True, allow_nan=False) + "\n")
    stream.flush()
    os.fsync(stream.fileno())


def run_stage(command, directory, stage, stream):
    with (
        (directory / f"{stage}.stdout.log").open("xb") as stdout,
        (directory / f"{stage}.stderr.log").open("xb") as stderr,
    ):
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        event(stream, stage=stage, pid=process.pid, state="STARTED")
        code = process.wait()
        event(stream, stage=stage, exit_code=code, state="EXIT_OBSERVED")
    return code


def admit_mirror(policy):
    source, workspace = separate(policy["source_directory"], policy["workspace"])
    if (workspace / "failure.json").exists() or (
        workspace / "measurement.json"
    ).exists():
        raise ValueError("failed/already measured workspace")
    receipt = read_sealed(workspace / "mirror.json")
    if (
        receipt.get("status") != "BYTE_IDENTICAL_IO_MIRROR_ONLY"
        or receipt.get("boundary") != BOUNDARY
        or receipt.get("source") != str(source)
        or receipt.get("target") != str(workspace / "parent")
        or not receipt.get("rows")
        or len({r["path"] for r in receipt["rows"]}) != len(receipt["rows"])
        or sum(r["size_bytes"] for r in receipt["rows"]) != receipt["total_bytes"]
    ):
        raise ValueError("mirror admission differs")
    return receipt


def supervise(root, config, config_sha, pins, directory, executor=run_stage):
    root, config, directory = map(confined, (root, config, directory))
    # Reject overlap before creating any evidence; new-only supervisor namespace.
    policy = load_policy(root, config, config_sha)
    source, workspace = separate(policy["source_directory"], policy["workspace"])
    separate(source, directory)
    separate(workspace, directory)
    directory.mkdir(parents=True, exist_ok=False)

    def guard():
        for relative, sha in pins.items():
            _pinned(root / relative, sha)
        return load_policy(root, config, config_sha)

    with (directory / "events.jsonl").open("x", encoding="utf-8") as stream:
        try:
            event(
                stream, state="SUPERVISOR_STARTED", pid=os.getpid(), boundary=BOUNDARY
            )
            base = [
                sys.executable,
                "-B",
                str(root / "scripts/benchmark_dante_workflow_storage.py"),
                "--repository-root",
                str(root),
                "--config",
                str(config),
                "--config-sha256",
                config_sha,
            ]
            for stage in ("mirror", "measure"):
                guard()
                if stage == "measure":
                    receipt = admit_mirror(policy)
                    event(
                        stream,
                        state="MIRROR_ADMITTED_IO_ONLY",
                        digest=receipt["digest"],
                        files=len(receipt["rows"]),
                        total_bytes=receipt["total_bytes"],
                    )
                code = executor([*base, "--stage", stage], directory, stage, stream)
                if code != 0:
                    raise RuntimeError(f"{stage} observed OS exit {code}; no retry")
            guard()
            result = read_sealed(workspace / "measurement.json")
            if (
                result.get("status") != "MEASURED_IO_ONLY_NOT_SCIENTIFIC_QUALIFICATION"
                or result.get("boundary") != BOUNDARY
                or result.get("mirror_digest") != receipt["digest"]
                or len(result.get("samples", [])) != 2 * policy["repetitions"]
                or (workspace / "failure.json").exists()
            ):
                raise ValueError("measurement binding differs")
            new_report(
                directory / "summary.json",
                {
                    "status": "COMPLETE_SUPERVISED_IO_ONLY",
                    "mirror_exit_code": 0,
                    "measure_exit_code": 0,
                    "mirror_digest": receipt["digest"],
                    "measurement_digest": result["digest"],
                    "boundary": BOUNDARY,
                },
            )
            event(stream, state="COMPLETE_IO_ONLY", boundary=BOUNDARY)
        except BaseException as exc:
            new_report(
                directory / "failure.json",
                {
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "boundary": BOUNDARY,
                },
            )
            event(stream, state="FAILED_NO_RETRY", error=type(exc).__name__)
            raise
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repository-root", "config", "log-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    for name in ("config-sha256", "probe-sha256", "runner-sha256", "supervisor-sha256"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args(argv)
    pins = {
        "src/dante_workflow/storage_probe.py": args.probe_sha256,
        "scripts/benchmark_dante_workflow_storage.py": args.runner_sha256,
        "src/dante_workflow/storage_supervisor.py": args.supervisor_sha256,
    }
    return supervise(
        args.repository_root,
        args.config,
        args.config_sha256,
        pins,
        args.log_directory,
    )
