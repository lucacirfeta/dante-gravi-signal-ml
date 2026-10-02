"""Explicit stack ownership; historical locks are never created or repaired."""

from contextlib import ExitStack

import pytest

from src.dante_workflow import o3a_locking as locks
from src.dante_workflow.o3a_initial_verification import _Evidence


@pytest.fixture
def directory(tmp_path):
    pytest.importorskip("fcntl", reason="existing read-only flock requires POSIX/WSL")
    (tmp_path / "run.lock").write_bytes(b"existing PID")
    return tmp_path


def test_registry_does_not_survive_stack_release(directory):
    evidence = _Evidence()
    with ExitStack() as stack:
        locks.hold_native_lock(directory, evidence=evidence, stack=stack, name="scan")
        locks.clean_native_parent(directory, stack=stack)
        assert "scan_lock" in evidence.inputs
    with pytest.raises(locks.InitialEvidenceError, match="failure/lock"):
        locks.clean_native_parent(directory, stack=stack)


def test_duplicate_acquisition_refuses_without_losing_first_lock(directory):
    import fcntl

    with ExitStack() as stack:
        evidence = _Evidence()
        locks.hold_native_lock(directory, evidence=evidence, stack=stack, name="scan")
        with pytest.raises(locks.InitialEvidenceError, match="acquired twice"):
            locks.hold_native_lock(
                directory, evidence=evidence, stack=stack, name="alias"
            )
        with (directory / "run.lock").open("rb") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize(
    "marker", ["failure.json", "failures.json", "controller.lock", "bad.partial"]
)
def test_final_marker_refused_with_held_lock(directory, marker):
    with ExitStack() as stack:
        locks.hold_native_lock(
            directory, evidence=_Evidence(), stack=stack, name="scan"
        )
        path = directory / marker
        path.write_bytes(b"evidence")
        with pytest.raises(locks.InitialEvidenceError, match="failure/active|partial"):
            locks.clean_native_parent(directory, stack=stack)
        # Synthetic test cleanup only; historical evidence is never modified.
        path.unlink()


def test_locked_directory_does_not_waive_another_run(directory, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    (other / "run.lock").write_bytes(b"not held")
    with ExitStack() as stack:
        locks.hold_native_lock(
            directory, evidence=_Evidence(), stack=stack, name="scan"
        )
        with pytest.raises(locks.InitialEvidenceError, match="failure/lock"):
            locks.clean_native_parent(other, stack=stack)


def test_unlocked_directory_remains_strict_without_posix(tmp_path):
    (tmp_path / "run.lock").write_bytes(b"not held")
    with ExitStack() as stack:
        with pytest.raises(locks.InitialEvidenceError, match="failure/lock"):
            locks.clean_native_parent(tmp_path, stack=stack)
