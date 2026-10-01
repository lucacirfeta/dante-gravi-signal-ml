"""Temporary-only diagnosis of the existing persistent threshold lock."""

from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    import fcntl
    from src.dante_light import o3a_native_thresholds as nt
    from src.dante_workflow.o3a_initial_verification import InitialEvidenceError, _clean

    with tempfile.TemporaryDirectory(prefix="dante-lock-audit-") as temporary:
        directory = Path(temporary) / "run"
        with nt._lock(directory):
            pass
        lock = directory / "run.lock"
        initial = lock.stat()
        sha = hashlib.sha256(lock.read_bytes()).hexdigest()
        try:
            _clean(directory)
        except InitialEvidenceError as error:
            refusal = str(error)
        else:
            raise AssertionError("existing clean guard did not refuse run.lock")
        # This is a diagnostic probe, not an adopted verification lock policy.
        with lock.open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            child = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "from pathlib import Path; "
                    "from src.dante_light.o3a_native_thresholds import _lock; "
                    "import sys; "
                    "context = _lock(Path(sys.argv[1])); context.__enter__()",
                    str(directory),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            assert child.returncode != 0
            assert "native threshold run already active" in child.stderr
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        # The original producer can acquire again after the read-only probe.
        with nt._lock(directory):
            pass
        final = lock.stat()
        assert hashlib.sha256(lock.read_bytes()).hexdigest() == sha
        assert initial.st_size == final.st_size
        assert initial.st_mtime_ns == final.st_mtime_ns
        assert initial.st_ino == final.st_ino
        assert list(directory.iterdir()) == [lock]
        print(
            json.dumps(
                {
                    "scope": "TEMPORARY_LOCK_DIAGNOSIS_ONLY",
                    "legacy_lock_persists_after_release": lock.exists(),
                    "existing_clean_guard_refusal": refusal,
                    "read_only_open_exclusive_flock_supported": True,
                    "legacy_producer_conflict_exit": child.returncode,
                    "legacy_producer_reacquires_after_release": True,
                    "lock_bytes_mtime_inode_unchanged": True,
                    "historical_evidence_accessed": False,
                    "verification_policy_adopted": False,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
