"""Linux byte preparation fixtures only; no real data or scientific stages."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

from src.dante_workflow import linux_workspace as workspace
from src.dante_workflow.calibration_recovery import read_sealed


def test_byte_copy_preserves_mixed_line_endings(tmp_path):
    source = tmp_path / "source"
    data = b"LF\nCRLF\r\n\x00\xff"
    source.write_bytes(data)
    destination = tmp_path / "copy" / "file"
    result = workspace.copy_file(source, destination, hashlib.sha256(data).hexdigest())
    assert destination.read_bytes() == data
    assert result["size_bytes"] == len(data)
    assert source.read_bytes() == data


def test_copy_never_overwrites(tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"source")
    target.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        workspace.copy_file(source, target)
    assert target.read_bytes() == b"preserve"


def test_wrong_hash_preserves_failed_copy(tmp_path):
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_bytes(b"opaque")
    with pytest.raises(ValueError, match="hash mismatch"):
        workspace.copy_file(source, target, "0" * 64)
    assert target.read_bytes() == source.read_bytes()


def test_copy_rejects_symlink(tmp_path):
    source, link = tmp_path / "a", tmp_path / "link"
    source.write_bytes(b"data")
    link.symlink_to(source)
    with pytest.raises(OSError):
        workspace.copy_file(link, tmp_path / "b")


def test_tree_rejects_symlink(tmp_path):
    (tmp_path / "link").symlink_to("/etc/passwd")
    with pytest.raises(ValueError, match="symlink"):
        list(workspace.tree(tmp_path))


def test_exclude_archival_frames_not_contexts(tmp_path):
    for directory in ("contexts", "frames"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "file").write_bytes(b"x")
    assert list(workspace.tree(tmp_path, ["frames"])) == [("contexts/file", 1)]


@pytest.mark.parametrize("value", ["", "../x", "/etc/passwd", "a\\b"])
def test_relative_path_rejects_escape(value):
    with pytest.raises(ValueError):
        workspace.relative(value)


def test_checked_rejects_link_ancestor(tmp_path):
    (tmp_path / "dir").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "dir", target_is_directory=True)
    with pytest.raises(ValueError):
        workspace.checked(tmp_path / "link" / "file")


def test_checked_requires_absolute():
    with pytest.raises(ValueError):
        workspace.checked(Path("relative"))


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    source = tmp_path / "opaque"
    source.write_bytes(b"\r\nopaque\x00")
    output = tmp_path / "snapshot"
    config = tmp_path / "policy"
    config.write_bytes(b"policy")
    sha = hashlib.sha256(config.read_bytes()).hexdigest()
    monkeypatch.setattr(
        workspace,
        "read_policy",
        lambda *args: (
            {"excluded_unused_inputs": "fixture only", "maximum_snapshot_bytes": 1024},
            tmp_path,
            output,
            2,
        ),
    )
    monkeypatch.setattr(
        workspace,
        "recipe",
        lambda *args: {
            Path("/mnt/e/fixture/opaque"): dict(
                source=source, expected=None, size=source.stat().st_size
            )
        },
    )
    return source, output, config, sha


def test_full_parallel_prepare_fixture(prepared):
    source, output, config, sha = prepared
    assert workspace.prepare(config, sha) == 0
    receipt = read_sealed(output / "snapshot.json")
    assert receipt["files"] == 1
    assert receipt["scientific_run_started"] is False
    assert receipt["scientific_equivalence_verified"] is False
    assert (
        output / "snapshot/mnt/e/fixture/opaque"
    ).read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        workspace.prepare(config, sha)
    assert not (output / "failure.json").exists()


def test_failed_prepare_preserves_namespace(prepared, monkeypatch):
    _, output, config, sha = prepared
    monkeypatch.setattr(
        workspace,
        "recipe",
        lambda *args: (_ for _ in ()).throw(ValueError("required input missing")),
    )
    with pytest.raises(ValueError, match="required input"):
        workspace.prepare(config, sha)
    assert read_sealed(output / "failure.json")["scientific_run_started"] is False
    assert not (output / "snapshot.json").exists()


def test_host_backing_budget_stops_before_copy(prepared, monkeypatch):
    _, output, config, sha = prepared
    original = workspace.read_policy

    def limited(*args):
        policy, root, directory, workers = original(*args)
        policy["maximum_snapshot_bytes"] = 0
        return policy, root, directory, workers

    monkeypatch.setattr(workspace, "read_policy", limited)
    with pytest.raises(ValueError, match="host backing disk"):
        workspace.prepare(config, sha)
    assert not (output / "snapshot").exists()
    assert read_sealed(output / "failure.json")["scientific_run_started"] is False


def test_source_freeze_checks_both_executables(tmp_path, monkeypatch):
    for name in (
        "src/dante_workflow/linux_workspace.py",
        "scripts/prepare_dante_workflow_linux.py",
    ):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"frozen\r\n")
    monkeypatch.setattr(
        workspace.subprocess,
        "run",
        lambda *args, **kwargs: type("Result", (), {"stdout": b"frozen\r\n"})(),
    )
    workspace.source_audit(tmp_path, "freeze")
    (tmp_path / "scripts/prepare_dante_workflow_linux.py").write_bytes(b"drift")
    with pytest.raises(ValueError, match="source differs"):
        workspace.source_audit(tmp_path, "freeze")


@pytest.mark.skipif(os.geteuid() != 0, reason="private mount fixture requires root")
def test_private_readonly_mount_cannot_change_host(tmp_path):
    source, target = tmp_path / "native", tmp_path / "original"
    source.mkdir()
    target.mkdir()
    (source / "opaque").write_bytes(b"native\r\n")
    (target / "opaque").write_bytes(b"original\r\n")
    code = """
import pathlib,subprocess,sys
source,target=sys.argv[1:]
subprocess.run(['mount','--bind',source,target],check=True)
subprocess.run(['mount','-o','remount,bind,ro',target],check=True)
p=pathlib.Path(target)/'opaque'
assert p.read_bytes()==b'native\\r\\n'
try:
    p.write_bytes(b'forbidden')
except OSError:
    pass
else:
    raise AssertionError('read-only mount accepted a write')
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
            str(source),
            str(target),
        ],
        check=True,
    )
    assert (target / "opaque").read_bytes() == b"original\r\n"
    assert (source / "opaque").read_bytes() == b"native\r\n"
