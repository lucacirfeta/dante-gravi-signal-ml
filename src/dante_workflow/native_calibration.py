"""Private read-only Linux execution of the unchanged expanded calibration."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys

from src.dante_workflow.calibration_recovery import read_sealed, sealed, write_json
from src.dante_workflow.input_preflight import _hash
from src.dante_workflow.linux_workspace import checked, copy_file


SOURCE_PATHS = (
    "src/dante_workflow/native_calibration.py",
    "src/dante_workflow/immutable_scan_scope.py",
    "scripts/execute_dante_workflow_native.py",
)


def load_policy(config, sha):
    config = checked(config)
    if _hash(config) != sha:
        raise ValueError("native execution policy hash mismatch")
    policy = json.loads(config.read_text())
    if (
        policy.get("status") != "PRIVATE_IMMUTABLE_NATIVE_CALIBRATION_V1"
        or policy.get("source_paths") != list(SOURCE_PATHS)
        or policy.get("scan_policy") != "INITIAL_FINAL_IMMUTABLE_PARENT_SCANS"
        or policy.get("o4b_launch_allowed") is not False
    ):
        raise ValueError("unsupported native execution policy")
    return policy


def protect_snapshot(directory):
    """Protect only a declared newly copied tree, never historical input sources."""
    directory = checked(directory)
    if os.geteuid() != 0:
        raise ValueError("root is required to protect snapshot backing bytes")
    if (
        not directory.is_relative_to(Path("/home/atafe/dante_bench"))
        or directory.name != "snapshot"
    ):
        raise ValueError("only an isolated native snapshot may be protected")
    count = 0
    for base, dirs, files in os.walk(directory, topdown=False, followlinks=False):
        for path in (*(Path(base) / name for name in dirs + files), Path(base)):
            mode = path.lstat()
            if stat.S_ISLNK(mode.st_mode) or not (
                stat.S_ISDIR(mode.st_mode) or stat.S_ISREG(mode.st_mode)
            ):
                raise ValueError("snapshot contains indirect or special entries")
            os.chown(path, 0, 0)
            path.chmod(0o555 if stat.S_ISDIR(mode.st_mode) else 0o444)
            count += 1
    return count


def require_complete(payload, expected, status):
    if payload.get("status") != status or any(
        payload.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("native stage incomplete or wrong population")


def inside_stage(policy, config, sha, stage, summary_sha=None):
    if os.geteuid() == 0:
        raise ValueError("scientific stage must run without root privileges")
    module_path = Path(__file__).with_name("immutable_scan_scope.py")
    spec = importlib.util.spec_from_file_location("native_immutable_scans", module_path)
    scans = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scans)
    from src.dante_workflow.expanded_calibration import main as calibration_main

    root = Path(policy["snapshot_receipt"]).parent / "snapshot"
    for name in ("c", "e"):
        physical, virtual = root / "mnt" / name, Path("/mnt") / name
        a, b = physical.stat(), virtual.stat()
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino) or not (
            os.statvfs(virtual).f_flag & os.ST_RDONLY
        ):
            raise ValueError("scientific input is not the declared read-only snapshot")
    args = [
        *policy["calibration_arguments"],
        "--stage",
        stage,
        "--run-dir",
        policy["run_directory"],
    ]
    if summary_sha is not None:
        args += ["--summary-sha256", summary_sha]
    scope = None
    try:
        with scans.calibration_scan_scope(
            policy["protected_scan_directories"]
        ) as scope:
            code = calibration_main(args)
        if code != 0 or _hash(config) != sha:
            raise ValueError("native scientific execution or policy pin failed")
        write_json(
            Path(policy["execution_directory"]) / "logs" / f"scans.{stage}.json",
            sealed(
                dict(
                    status="PASS_EXPLICIT_IMMUTABLE_SCAN_SCOPE_ONLY", **scope.evidence()
                )
            ),
        )
        return 0
    except BaseException:
        if scope is not None:
            write_json(
                Path(policy["execution_directory"])
                / "logs"
                / f"scans.{stage}.failure.json",
                sealed(
                    dict(
                        status="FAILED_NATIVE_SCAN_STAGE_NO_RESUME", **scope.evidence()
                    )
                ),
            )
        raise


def mount_stage(policy, config, sha, freeze, stage, summary_sha=None):
    if os.geteuid() != 0:
        raise ValueError("private mount setup requires root")
    if os.readlink("/proc/self/ns/mnt") == os.readlink("/proc/1/ns/mnt"):
        raise ValueError("input mounts require a private mount namespace")
    snapshot = Path(policy["snapshot_receipt"]).parent / "snapshot"
    for name in ("c", "e"):
        source, target = snapshot / "mnt" / name, Path("/mnt") / name
        subprocess.run(["mount", "--bind", str(source), str(target)], check=True)
        subprocess.run(["mount", "-o", "remount,bind,ro", str(target)], check=True)
    entry = (
        Path(policy["execution_directory"])
        / "code/scripts/execute_dante_workflow_native.py"
    )
    command = [
        "setpriv",
        "--reuid=1000",
        "--regid=1000",
        "--clear-groups",
        "--no-new-privs",
        sys.executable,
        "-B",
        str(entry),
        "--config",
        str(config),
        "--config-sha256",
        sha,
        "--source-freeze",
        freeze,
        "--inside-stage",
        stage,
    ]
    if summary_sha is not None:
        command += ["--summary-sha256", summary_sha]
    env = dict(os.environ)
    account = pwd.getpwuid(1000)
    env.update(
        HOME=account.pw_dir,
        USER=account.pw_name,
        LOGNAME=account.pw_name,
        SHELL=account.pw_shell,
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="safe.directory",
        GIT_CONFIG_VALUE_0=policy["repository_root"],
    )
    return subprocess.run(
        command, env=env, cwd=policy["execution_directory"]
    ).returncode


def orchestrate(policy, config, sha, freeze):
    if os.geteuid() != 0:
        raise ValueError("native orchestration requires root for scoped mounts")
    root, execution = (
        checked(policy["repository_root"]),
        checked(policy["execution_directory"]),
    )
    if not execution.is_relative_to(Path("/home/atafe/dante_bench")):
        raise ValueError("native execution evidence must be isolated")
    snapshot = read_sealed(checked(policy["snapshot_receipt"]))
    require_complete(
        snapshot,
        dict(
            source_freeze=policy["preparation_freeze"],
            configuration_sha256=policy["preparation_config_sha256"],
            scientific_run_started=False,
        ),
        "BYTE_IDENTICAL_NATIVE_REQUIRED_INPUT_SNAPSHOT_ONLY",
    )
    launcher = checked(policy["preparation_launcher_log"])
    if "PREPARATION_EXIT_CODE=0 SMOKE_ONLY=False" not in launcher.read_text():
        raise ValueError("no actual successful preparation exit observed")
    if Path(policy["run_directory"]).exists():
        raise ValueError("historical/existing scientific run is never resumed")
    execution.mkdir(exist_ok=False)
    try:
        pins = {}
        for name in SOURCE_PATHS:
            raw = subprocess.run(
                ["git", "show", f"{freeze}:{name}"],
                cwd=root,
                capture_output=True,
                check=True,
            ).stdout
            pin = hashlib.sha256(raw).hexdigest()
            pins[name] = pin
            copy_file(root / name, execution / "code" / name, pin)
        native_config = execution / "policy.json"
        copy_file(config, native_config, sha)
        for path in (execution / "code").rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        (execution / "logs").mkdir()
        os.chown(execution / "logs", 1000, 1000)
        protected = protect_snapshot(
            Path(policy["snapshot_receipt"]).parent / "snapshot"
        )
        write_json(
            execution / "binding.json",
            sealed(
                dict(
                    status="BOUND_PRIVATE_NATIVE_EXECUTION_ONLY",
                    source_freeze=freeze,
                    source_pins=pins,
                    snapshot_digest=snapshot["digest"],
                    policy_sha256=sha,
                    protected_backing_entries=protected,
                    scan_policy=policy["scan_policy"],
                    scientific_equivalence_verified=False,
                )
            ),
        )
        entry = execution / "code/scripts/execute_dante_workflow_native.py"
        summary_sha = None
        exits = {}
        for stage in ("run", "verify"):
            command = [
                "unshare",
                "--mount",
                "--propagation",
                "private",
                "--",
                sys.executable,
                "-B",
                str(entry),
                "--config",
                str(native_config),
                "--config-sha256",
                sha,
                "--source-freeze",
                freeze,
                "--mount-stage",
                stage,
            ]
            if summary_sha is not None:
                command += ["--summary-sha256", summary_sha]
            with (
                (execution / "logs" / f"{stage}.stdout.log").open("xb") as out,
                (execution / "logs" / f"{stage}.stderr.log").open("xb") as err,
            ):
                code = subprocess.run(command, stdout=out, stderr=err).returncode
            exits[stage] = code
            write_json(
                execution / "exits.json",
                sealed(dict(exits=exits, automatic_resume=False)),
            )
            print(f"NATIVE_{stage.upper()}_EXIT_CODE={code}", flush=True)
            if code != 0:
                raise ValueError(f"native {stage} OS exit {code}; no retry")
            directory = Path(policy["run_directory"])
            result = read_sealed(
                directory / ("summary.json" if stage == "run" else "verification.json")
            )
            require_complete(
                result,
                policy["expected_population"],
                "PASS_COMPLETE_ISOLATED_EXPANDED_CALIBRATION_ONLY"
                if stage == "run"
                else "PASS_VERIFIED_ISOLATED_EXPANDED_CALIBRATION_ONLY",
            )
            if (
                any(
                    (directory / p).exists()
                    for p in ("failure.json", "controller.lock")
                )
                or any(directory.rglob("*.partial"))
                or any(directory.rglob("*.tmp"))
            ):
                raise ValueError("native stage has incomplete evidence")
            summary_sha = _hash(directory / "summary.json")
        write_json(
            execution / "verification.json",
            sealed(
                dict(
                    status="PASS_VERIFIED_PRIVATE_NATIVE_CALIBRATION_EXECUTION_ONLY",
                    source_freeze=freeze,
                    exits=exits,
                    policy_sha256=sha,
                    snapshot_digest=snapshot["digest"],
                    scientific_verification_sha256=_hash(
                        Path(policy["run_directory"]) / "verification.json"
                    ),
                    default_provider_replaced=False,
                    o4b_launch_allowed=False,
                )
            ),
        )
        return 0
    except BaseException as exc:
        write_json(
            execution / "failure.json",
            sealed(
                dict(
                    status="FAILED_PRIVATE_NATIVE_EXECUTION_NO_RESUME",
                    error=type(exc).__name__,
                    message=str(exc),
                    automatic_resume=False,
                )
            ),
        )
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--source-freeze", required=True)
    parser.add_argument("--mount-stage", choices=("run", "verify"))
    parser.add_argument("--inside-stage", choices=("run", "verify"))
    parser.add_argument("--summary-sha256")
    args = parser.parse_args(argv)
    policy = load_policy(args.config, args.config_sha256)
    if args.mount_stage:
        return mount_stage(
            policy,
            args.config,
            args.config_sha256,
            args.source_freeze,
            args.mount_stage,
            args.summary_sha256,
        )
    if args.inside_stage:
        return inside_stage(
            policy,
            args.config,
            args.config_sha256,
            args.inside_stage,
            args.summary_sha256,
        )
    return orchestrate(policy, args.config, args.config_sha256, args.source_freeze)
