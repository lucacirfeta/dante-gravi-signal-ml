"""Operational guard scheduling fixtures; no score/population changes."""

import os
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.dante_workflow import immutable_scan_scope as scans


@pytest.fixture
def scope(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    calls = []
    monkeypatch.setattr(scans, "verify_immutable_directory", lambda directory: 3)
    return scans.ImmutableScanScope(lambda p: calls.append(p), [parent]), parent, calls


def test_initial_final_full_scans_and_repeated_skip(scope):
    guard, parent, calls = scope
    guard(parent)  # Before activation nothing is skipped.
    guard.start()
    for _ in range(10):
        guard(parent)
    guard.finish()
    guard(parent)
    assert calls == [parent] * 4
    assert guard.evidence()["initial_full_scans"] == 1
    assert guard.evidence()["final_full_scans"] == 1
    assert guard.evidence()["repeated_full_scans_avoided"] == 10
    assert guard.evidence()["per_read_hashing_replaced"] is False


def test_writable_output_and_unlisted_children_always_scanned(scope):
    guard, parent, calls = scope
    guard.start()
    child, output = parent / "child", parent.parent / "output"
    child.mkdir()
    output.mkdir()
    guard(child)
    guard(output)
    assert calls == [parent, child, output]


@pytest.mark.parametrize("marker", ["failure.json", "controller.lock"])
def test_active_failure_marker_never_hidden(scope, marker):
    guard, parent, calls = scope
    guard.start()
    (parent / marker).write_text("fixture")
    guard(parent)
    assert calls == [parent, parent]
    assert guard.repeated_scans_avoided == 0


def test_scope_rejects_missing_or_duplicate_directories(tmp_path):
    with pytest.raises(ValueError, match="unique"):
        scans.ImmutableScanScope(lambda p: None, [])
    with pytest.raises(ValueError, match="unique"):
        scans.ImmutableScanScope(lambda p: None, [tmp_path, tmp_path])


def test_scope_rejects_writable_mount(tmp_path):
    with pytest.raises(ValueError, match="read-only"):
        scans.verify_immutable_directory(tmp_path)


def test_scope_rejects_mutable_backing_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(
        scans.os, "statvfs", lambda p: SimpleNamespace(f_flag=os.ST_RDONLY)
    )
    with pytest.raises(ValueError, match="mutable"):
        scans.verify_immutable_directory(tmp_path)


def test_explicit_dispatch_restores_after_failure(tmp_path, monkeypatch):
    from src.dante_workflow import expanded_calibration, expanded_production
    from src.dante_workflow.expanded_context_replay import quiet

    monkeypatch.setattr(scans, "verify_immutable_directory", lambda p: 1)
    with pytest.raises(RuntimeError, match="fixture failure"):
        with scans.calibration_scan_scope([tmp_path]) as guard:
            assert expanded_calibration.quiet is guard
            assert expanded_production.quiet is guard
            guard(tmp_path)
            raise RuntimeError("fixture failure")
    assert expanded_calibration.quiet is quiet
    assert expanded_production.quiet is quiet


def test_existing_dispatch_replacement_rejected(tmp_path, monkeypatch):
    from src.dante_workflow import expanded_calibration

    monkeypatch.setattr(expanded_calibration, "quiet", lambda p: None)
    with pytest.raises(ValueError, match="dispatch"):
        with scans.calibration_scan_scope([tmp_path]):
            pass


def test_per_read_parent_hash_checks_unchanged(tmp_path, monkeypatch):
    from src.dante_workflow import expanded_production

    monkeypatch.setattr(scans, "verify_immutable_directory", lambda p: 1)
    pins = {tmp_path / "a": "pin-a", tmp_path / "b": "pin-b"}
    reads = []
    monkeypatch.setattr(
        expanded_production, "_pinned", lambda p, sha: reads.append((p, sha))
    )
    provider = expanded_production.IsolatedExpandedProductionProvider(
        SimpleNamespace(allowed=()), pins, tmp_path
    )
    with scans.calibration_scan_scope([tmp_path]) as guard:
        for _ in range(3):
            provider.guard()
        assert reads == list(pins.items()) * 3
        assert guard.repeated_scans_avoided == 3


def test_final_scan_failure_still_restores_dispatch(tmp_path, monkeypatch):
    from src.dante_workflow import expanded_calibration, expanded_production
    from src.dante_workflow.expanded_context_replay import quiet

    monkeypatch.setattr(scans, "verify_immutable_directory", lambda p: 1)
    with pytest.raises(Exception, match="incomplete evidence"):
        with scans.calibration_scan_scope([tmp_path]):
            (tmp_path / "incomplete.partial").write_bytes(b"fixture")
    assert expanded_calibration.quiet is quiet
    assert expanded_production.quiet is quiet


@pytest.mark.skipif(os.geteuid() != 0, reason="real immutable namespace requires root")
def test_actual_immutable_backing_and_readonly_namespace(tmp_path):
    native, target = tmp_path / "native", tmp_path / "target"
    native.mkdir(mode=0o755)
    target.mkdir()
    (native / "data").write_bytes(b"immutable")
    (native / "data").chmod(0o444)
    native.chmod(0o555)
    code = """
import pathlib,subprocess,sys
from src.dante_workflow.immutable_scan_scope import verify_immutable_directory,ImmutableScanScope
source,target=sys.argv[1:]
subprocess.run(['mount','--bind',source,target],check=True)
subprocess.run(['mount','-o','remount,bind,ro',target],check=True)
assert verify_immutable_directory(pathlib.Path(target))>=2
calls=[]
s=ImmutableScanScope(lambda p:calls.append(p),[target])
s.start();s(target);s(target);s.finish()
assert len(calls)==2 and s.repeated_scans_avoided==2
try:(pathlib.Path(target)/'data').write_bytes(b'forbidden')
except OSError:pass
else:raise AssertionError('read-only view accepted write')
"""
    subprocess.run(
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
            str(native),
            str(target),
        ],
        check=True,
    )
    assert (native / "data").read_bytes() == b"immutable"
    # Confirm no global bind survived.
    assert list(target.iterdir()) == []
    assert stat.S_IMODE(native.stat().st_mode) == 0o555
