"""Shared retained-only O_RDONLY flock, never lock repair or producer execution."""

from contextlib import contextmanager
import os
import stat

from .o3a_initial_verification import InitialEvidenceError, _clean


def _fcntl():
    try:
        import fcntl
    except ImportError as error:
        raise InitialEvidenceError(
            "read-only persistent locks require POSIX/WSL"
        ) from error
    return fcntl


def _signature(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _stage_clean(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise InitialEvidenceError("missing or unsafe decision run directory")
    for name in ("failure.json", "failures.json", "controller.lock"):
        if (directory / name).exists() or (directory / name).is_symlink():
            raise InitialEvidenceError(f"failure/active evidence present: {name}")
    if any(
        p.name.endswith((".part", ".partial", ".tmp")) for p in directory.rglob("*")
    ):
        raise InitialEvidenceError("partial decision evidence present")


@contextmanager
def _persistent_lock(directory):
    """Hold the original flock protocol on an existing O_RDONLY regular inode."""
    fcntl = _fcntl()
    _stage_clean(directory)
    path = directory / "run.lock"
    descriptor, held = None, False
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise InitialEvidenceError("unsafe persistent lock file")
        descriptor = os.open(
            path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        )
        opened = os.fstat(descriptor)
        if _signature(opened) != _signature(before) or opened.st_nlink != 1:
            raise InitialEvidenceError("persistent lock replaced during open")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held = True
        if _signature(path.lstat()) != _signature(opened):
            raise InitialEvidenceError("persistent lock replaced during acquisition")
        yield
        _stage_clean(directory)
        if (
            _signature(path.lstat()) != _signature(opened)
            or _signature(os.fstat(descriptor)) != _signature(opened)
            or os.fstat(descriptor).st_nlink != 1
        ):
            raise InitialEvidenceError("persistent lock changed during verification")
    except OSError as error:
        raise InitialEvidenceError(
            "persistent lock missing, busy or unsupported"
        ) from error
    finally:
        try:
            if held:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            if descriptor is not None:
                os.close(descriptor)


def hold_native_lock(directory, *, evidence, stack, name):
    """Hold a cooperative native producer's existing inode to outer stack exit."""
    held = getattr(stack, "_dante_native_locks", None)
    if held is None:
        held = stack._dante_native_locks = {}
    key = directory.resolve()
    if key in held:
        raise InitialEvidenceError("native parent lock acquired twice")
    stack.enter_context(_persistent_lock(directory))
    held[key] = directory
    stack.callback(held.pop, key)
    # Record only after acquisition, so producer PID writes cannot race this read.
    evidence.read(name + "_lock", directory / "run.lock")


def clean_native_parent(directory, *, stack):
    """Ignore presence only when this exact directory has a held native flock."""
    if directory.resolve() in getattr(stack, "_dante_native_locks", {}):
        _stage_clean(directory)
    else:
        # Non-cooperative calibration / mocked or initial ancestry stays strict.
        _clean(directory)
