"""Native orchestration control-plane fixtures; no real calibration or scores."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import pytest

from src.dante_workflow import native_calibration as native
from src.dante_workflow.calibration_recovery import read_sealed, sealed, write_json


def test_policy_keeps_explicit_authority_and_o4b_boundary(tmp_path):
    path = tmp_path / "policy"
    policy = dict(
        status="PRIVATE_IMMUTABLE_NATIVE_CALIBRATION_V1",
        source_paths=list(native.SOURCE_PATHS),
        scan_policy="INITIAL_FINAL_IMMUTABLE_PARENT_SCANS",
        o4b_launch_allowed=False,
    )
    path.write_text(json.dumps(policy))
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert native.load_policy(path, sha) == policy
    with pytest.raises(ValueError, match="hash"):
        native.load_policy(path, "0" * 64)
    policy["o4b_launch_allowed"] = True
    path.write_text(json.dumps(policy))
    with pytest.raises(ValueError, match="policy"):
        native.load_policy(path, hashlib.sha256(path.read_bytes()).hexdigest())


@pytest.mark.parametrize("wrong", [dict(status="other"), dict(identity_count=1)])
def test_complete_gate_rejects_wrong_status_or_population(wrong):
    payload = dict(status="pass", identity_count=7)
    payload.update(wrong)
    with pytest.raises(ValueError, match="population"):
        native.require_complete(payload, dict(identity_count=7), "pass")


def test_scientific_stage_rejects_root(monkeypatch):
    monkeypatch.setattr(native.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError, match="without root"):
        native.inside_stage({}, Path("/unused"), "pin", "run")


def test_snapshot_protection_rejects_nonroot_and_historical_paths(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(native.os, "geteuid", lambda: 1000)
    with pytest.raises(ValueError, match="root"):
        native.protect_snapshot(tmp_path)
    monkeypatch.setattr(native.os, "geteuid", lambda: 0)
    with pytest.raises(ValueError, match="isolated"):
        native.protect_snapshot(tmp_path)


@pytest.fixture
def orchestration(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    for name in native.SOURCE_PATHS:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    receipt = tmp_path / "snapshot.json"
    write_json(
        receipt,
        sealed(
            dict(
                status="BYTE_IDENTICAL_NATIVE_REQUIRED_INPUT_SNAPSHOT_ONLY",
                source_freeze="prep",
                configuration_sha256="prep-pin",
                scientific_run_started=False,
            )
        ),
    )
    log = tmp_path / "launcher.log"
    log.write_text("PREPARATION_EXIT_CODE=0 SMOKE_ONLY=False")
    config = tmp_path / "config"
    config.write_bytes(b"policy")
    policy = dict(
        repository_root=str(root),
        execution_directory=str(tmp_path / "execution"),
        snapshot_receipt=str(receipt),
        preparation_freeze="prep",
        preparation_config_sha256="prep-pin",
        preparation_launcher_log=str(log),
        run_directory=str(tmp_path / "run"),
        scan_policy="fixture",
        expected_population=dict(
            identity_count=7, context_count=6, session_detector_count=2
        ),
    )
    # Confine production normally; fixture maps its validated external directory.
    monkeypatch.setattr(native, "checked", lambda p: Path(p))
    original = native.Path

    def scoped(value):
        return tmp_path if str(value) == "/home/atafe/dante_bench" else original(value)

    monkeypatch.setattr(native, "Path", scoped)
    monkeypatch.setattr(native.os, "geteuid", lambda: 0)
    monkeypatch.setattr(native.os, "chown", lambda *args: None)
    monkeypatch.setattr(native, "protect_snapshot", lambda p: 20)
    return policy, config, tmp_path


def test_root_supervisor_records_both_actual_exits(orchestration, monkeypatch):
    policy, config, root = orchestration
    stages = []

    def run(command, **kwargs):
        if command[0] == "git":
            assert command[1:3] == ["-c", f"safe.directory={policy['repository_root']}"]
            return SimpleNamespace(stdout=b"fixture")
        stage = command[command.index("--mount-stage") + 1]
        stages.append(stage)
        output = root / "run"
        output.mkdir(exist_ok=True)
        write_json(
            output / ("summary.json" if stage == "run" else "verification.json"),
            sealed(
                dict(
                    status="PASS_COMPLETE_ISOLATED_EXPANDED_CALIBRATION_ONLY"
                    if stage == "run"
                    else "PASS_VERIFIED_ISOLATED_EXPANDED_CALIBRATION_ONLY",
                    **policy["expected_population"],
                )
            ),
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(native.subprocess, "run", run)
    assert (
        native.orchestrate(
            policy, config, hashlib.sha256(b"policy").hexdigest(), "freeze"
        )
        == 0
    )
    assert stages == ["run", "verify"]
    assert read_sealed(root / "execution/exits.json")["exits"] == dict(run=0, verify=0)
    assert (
        read_sealed(root / "execution/verification.json")["o4b_launch_allowed"] is False
    )
    with pytest.raises(ValueError, match="resumed"):
        native.orchestrate(
            policy, config, hashlib.sha256(b"policy").hexdigest(), "freeze"
        )


def test_failed_run_preserved_no_verifier(orchestration, monkeypatch):
    policy, config, root = orchestration
    calls = []

    def run(command, **kwargs):
        if command[0] == "git":
            return SimpleNamespace(stdout=b"fixture")
        calls.append(command)
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(native.subprocess, "run", run)
    with pytest.raises(ValueError, match="no retry"):
        native.orchestrate(
            policy, config, hashlib.sha256(b"policy").hexdigest(), "freeze"
        )
    assert len(calls) == 1
    assert read_sealed(root / "execution/exits.json")["exits"] == dict(run=2)
    assert (root / "execution/failure.json").exists()


def test_mount_stage_drops_privileges_and_uses_private_input_views(
    tmp_path, monkeypatch
):
    commands = []
    monkeypatch.setattr(native.os, "geteuid", lambda: 0)
    monkeypatch.setattr(native.os, "readlink", lambda p: str(p))

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(native.subprocess, "run", run)
    policy = dict(
        snapshot_receipt=str(tmp_path / "prep/snapshot.json"),
        execution_directory=str(tmp_path / "execution"),
        repository_root="/mnt/c/repo",
    )
    assert native.mount_stage(policy, tmp_path / "policy", "pin", "freeze", "run") == 0
    assert [c[0][0] for c in commands] == [
        "mount",
        "mount",
        "mount",
        "mount",
        "setpriv",
    ]
    command, opts = commands[-1]
    assert "--no-new-privs" in command and "--reuid=1000" in command
    assert "--inside-stage" in command
    assert opts["env"]["GIT_CONFIG_VALUE_0"] == "/mnt/c/repo"
    assert opts["env"]["HOME"] == "/home/atafe"
    assert opts["cwd"] == str(tmp_path / "execution")


def test_mount_refuses_global_namespace(monkeypatch):
    monkeypatch.setattr(native.os, "geteuid", lambda: 0)
    monkeypatch.setattr(native.os, "readlink", lambda p: "same")
    with pytest.raises(ValueError, match="private mount namespace"):
        native.mount_stage({}, Path("/unused"), "pin", "freeze", "run")


def test_spawn_import_does_not_execute_orchestrator():
    entry = (
        Path(__file__).resolve().parents[1] / "scripts/execute_dante_workflow_native.py"
    )
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import runpy,sys; runpy.run_path(sys.argv[1],run_name='__mp_main__')",
            str(entry),
        ],
        check=True,
    )


@pytest.mark.skipif(
    os.geteuid() != 0, reason="real namespace and privilege fixture requires root"
)
def test_actual_private_mount_and_privilege_drop():
    # Fresh tiny fixture only; never protect or modify historical/native inputs.
    fixture = Path(
        tempfile.mkdtemp(prefix="native-mount-fixture-", dir="/home/atafe/dante_bench")
    )
    fixture.chmod(0o755)
    for drive in ("c", "e"):
        source = fixture / "prep/snapshot/mnt" / drive
        source.mkdir(parents=True)
        (source / "opaque").write_bytes(b"fixture")
        (source / "opaque").chmod(0o444)
        source.chmod(0o555)
    entry = fixture / "execution/code/scripts/execute_dante_workflow_native.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("""import os,pathlib,errno,multiprocessing,signal
def verify(name):
    assert os.geteuid()==1000
    assert os.environ['HOME']=='/home/atafe'
    assert 'CapEff:\\t0000000000000000' in pathlib.Path('/proc/self/status').read_text()
    assert 'NoNewPrivs:\\t1' in pathlib.Path('/proc/self/status').read_text()
    p=pathlib.Path('/mnt')/name/'opaque'
    assert p.read_bytes()==b'fixture'
    assert os.statvfs(p.parent).f_flag & os.ST_RDONLY
    try: p.write_bytes(b'bad')
    except OSError as exc: assert exc.errno==errno.EROFS
    else: raise AssertionError('read-only mount accepted write')
    backing=pathlib.Path(__file__).parents[3]/'prep/snapshot/mnt'/name/'opaque'
    try: backing.write_bytes(b'bad')
    except OSError as exc: assert exc.errno==errno.EACCES
    else: raise AssertionError('backing accepted write')
    return name
if __name__=='__main__':
    def timeout(*args): raise TimeoutError('fixture spawn timeout')
    signal.signal(signal.SIGALRM,timeout)
    signal.alarm(10)
    with multiprocessing.get_context('spawn').Pool(2) as pool:
        assert pool.map(verify,['c','e'])==['c','e']
    print('ACTUAL_PRIVATE_RO_UID1000_CAP0_SPAWN_PASS')
""")
    policy = dict(
        snapshot_receipt=str(fixture / "prep/snapshot.json"),
        execution_directory=str(fixture / "execution"),
        repository_root="/mnt/c/repo",
    )
    repo = Path(__file__).resolve().parents[1]
    before = [(Path("/mnt") / d).stat().st_ino for d in ("c", "e")]
    code = "import json,sys;sys.path.insert(0,sys.argv[1]);from src.dante_workflow.native_calibration import mount_stage;raise SystemExit(mount_stage(json.loads(sys.argv[2]),sys.argv[3],'pin','freeze','run'))"
    result = subprocess.run(
        [
            "unshare",
            "--mount",
            "--propagation",
            "private",
            "--",
            sys.executable,
            "-B",
            "-c",
            code,
            str(repo),
            json.dumps(policy),
            str(fixture / "policy"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "ACTUAL_PRIVATE_RO_UID1000_CAP0_SPAWN_PASS" in result.stdout
    assert before == [(Path("/mnt") / d).stat().st_ino for d in ("c", "e")]
    assert all(
        (fixture / "prep/snapshot/mnt" / d / "opaque").read_bytes() == b"fixture"
        for d in ("c", "e")
    )
