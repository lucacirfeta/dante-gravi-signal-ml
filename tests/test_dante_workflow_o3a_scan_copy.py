"""Transport-only synthetic fixtures; historical SQLite remains strict."""

import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from src.dante_workflow import o3a_scan_copy as copies
from src.dante_workflow.o3a_native_verification import immutable_database

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def sample(tmp_path, monkeypatch):
    pytest.importorskip("fcntl", reason="isolated copy requires POSIX nofollow/flock")
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "run.lock").write_bytes(b"old PID")
    database = origin / "primary_scan.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE evidence(value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('unchanged')")
    (origin / "primary_scan.sqlite-wal").write_bytes(b"")
    (origin / "primary_scan.sqlite-shm").write_bytes(bytes(32768))
    from src.dante_light.contracts import canonical_json_sha256

    body = {
        "status": "PASS_COMPLETE_O3A_PRIMARY_SCAN",
        "run_key": "fixture",
        "contract_digest": "frozen",
        "database": {
            "filename": database.name,
            "sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "size_bytes": database.stat().st_size,
        },
    }
    (origin / "primary_scan_summary.json").write_text(
        json.dumps({**body, "artifact_digest": canonical_json_sha256(body)})
    )
    monkeypatch.setattr(copies, "_origin", lambda *args: (origin, "fixture", "frozen"))
    monkeypatch.setattr(copies, "_sources", lambda *args: {"synthetic": "unchanged"})
    return origin, {
        "root": ROOT,
        "primary_external_root": tmp_path,
        "output": tmp_path / "isolated",
    }


def _capture(sample):
    _, kwargs = sample
    result = copies.capture_copy(**kwargs)
    return kwargs, result["receipt_sha256"]


def test_exact_copy_verified_independently_preserves_origins(sample):
    origin, kwargs = sample
    before = {
        p.name: (p.read_bytes(), copies._signature(p.stat())) for p in origin.iterdir()
    }
    kwargs, pin = _capture(sample)
    result = copies.verify_copy(**kwargs, expected_receipt_sha256=pin)
    assert result["status"] == "PASS_VERIFIED_ISOLATED_SCAN_DATABASE_BYTES_ONLY_V1"
    assert not any(result["boundary"].values())
    assert {
        p.name: (p.read_bytes(), copies._signature(p.stat())) for p in origin.iterdir()
    } == before
    with pytest.raises(ValueError, match="transaction sidecar"):
        with immutable_database(origin / "primary_scan.sqlite"):
            pass
    with immutable_database(kwargs["output"] / "scan.sqlite") as connection:
        assert connection.execute("SELECT value FROM evidence").fetchall() == [
            ("unchanged",)
        ]
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM evidence")


@pytest.mark.parametrize(
    "suffix,payload", [("-wal", b"pending"), ("-journal", b""), ("-shm", b"bad")]
)
def test_unsupported_transactions_refuse_before_publication(sample, suffix, payload):
    origin, kwargs = sample
    (origin / ("primary_scan.sqlite" + suffix)).write_bytes(payload)
    with pytest.raises(ValueError, match="sidecar|journal"):
        copies.capture_copy(**kwargs)
    assert not kwargs["output"].exists()


@pytest.mark.parametrize("suffix", ["-wal", "-shm"])
def test_absent_sidecars_are_explicitly_bound(sample, suffix):
    origin, _ = sample
    (origin / ("primary_scan.sqlite" + suffix)).unlink()
    kwargs, pin = _capture(sample)
    copies.verify_copy(**kwargs, expected_receipt_sha256=pin)
    assert (
        json.loads((kwargs["output"] / "receipt.json").read_bytes())["origin_pins"][
            suffix
        ]
        is None
    )


def test_wrong_external_receipt_pin_refuses(sample):
    kwargs, _ = _capture(sample)
    with pytest.raises(ValueError, match="external receipt hash"):
        copies.verify_copy(**kwargs, expected_receipt_sha256="0" * 64)


@pytest.mark.parametrize(
    "name", ["scan.sqlite", "origin_wal.bin", "origin_shm.bin", "receipt.json"]
)
def test_output_byte_tampering_refuses(sample, name):
    kwargs, pin = _capture(sample)
    path = kwargs["output"] / name
    path.chmod(0o600)
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash|size"):
        copies.verify_copy(**kwargs, expected_receipt_sha256=pin)


@pytest.mark.parametrize(
    "name", ["scan.sqlite-wal", "scan.sqlite-shm", "bad.partial", "extra"]
)
def test_extra_output_sidecar_or_partial_refuses(sample, name):
    kwargs, pin = _capture(sample)
    (kwargs["output"] / name).write_bytes(b"")
    with pytest.raises(ValueError, match="extra/partial/transaction"):
        copies.verify_copy(**kwargs, expected_receipt_sha256=pin)


def test_origin_shm_change_refuses_even_if_database_identical(sample):
    kwargs, pin = _capture(sample)
    origin, _ = sample
    (origin / "primary_scan.sqlite-shm").write_bytes(b"1" * 32768)
    with pytest.raises(ValueError, match="origin/policy/source"):
        copies.verify_copy(**kwargs, expected_receipt_sha256=pin)


def test_nonempty_wal_appearing_after_capture_refuses(sample):
    kwargs, pin = _capture(sample)
    origin, _ = sample
    (origin / "primary_scan.sqlite-wal").write_bytes(b"transaction")
    with pytest.raises(ValueError, match="sidecar"):
        copies.verify_copy(**kwargs, expected_receipt_sha256=pin)


def test_summary_database_mismatch_refuses(sample):
    origin, kwargs = sample
    with (origin / "primary_scan.sqlite").open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(ValueError, match="sealed SCAN summary"):
        copies.capture_copy(**kwargs)


def test_busy_cooperative_lock_refuses(sample):
    import fcntl

    origin, kwargs = sample
    with (origin / "run.lock").open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="busy"):
            copies.capture_copy(**kwargs)
    assert not kwargs["output"].exists()


def test_historical_failure_refuses(sample):
    origin, kwargs = sample
    (origin / "failure.json").write_bytes(b"failure")
    with pytest.raises(ValueError, match="failure"):
        copies.capture_copy(**kwargs)


def test_existing_output_never_overwritten(sample):
    kwargs, _ = _capture(sample)
    before = {p.name: p.read_bytes() for p in kwargs["output"].iterdir()}
    with pytest.raises(ValueError, match="unsupported"):
        copies.capture_copy(**kwargs)
    assert {p.name: p.read_bytes() for p in kwargs["output"].iterdir()} == before


def test_overlap_refused(sample):
    origin, kwargs = sample
    kwargs["output"] = origin / "copy"
    with pytest.raises(ValueError, match="overlaps"):
        copies.capture_copy(**kwargs)


@pytest.mark.parametrize(
    "name",
    ["primary_scan.sqlite", "primary_scan.sqlite-wal", "primary_scan.sqlite-shm"],
)
def test_symlink_origin_refused(sample, name):
    origin, kwargs = sample
    path = origin / name
    actual = origin / (name + ".actual")
    path.rename(actual)
    path.symlink_to(actual)
    with pytest.raises(ValueError, match="unsupported"):
        copies.capture_copy(**kwargs)


def test_source_drift_leaves_new_output_without_success_receipt(sample, monkeypatch):
    _, kwargs = sample
    calls = 0

    def changing_sources(root):
        nonlocal calls
        calls += 1
        return {"synthetic": str(calls)}

    monkeypatch.setattr(copies, "_sources", changing_sources)
    with pytest.raises(ValueError, match="source changed"):
        copies.capture_copy(**kwargs)
    assert (kwargs["output"] / "scan.sqlite").exists()
    assert not (kwargs["output"] / "receipt.json").exists()


def test_policy_is_frozen_and_portable():
    policy = json.loads((ROOT / copies.POLICY_REL).read_bytes())
    assert policy["wal"] == "absent_or_zero_bytes_only"
    assert policy["journal"] == "absent_only"
    assert not any(policy["boundary"].values())


def test_hardlinked_origin_refuses(sample):
    import os

    origin, kwargs = sample
    os.link(origin / "primary_scan.sqlite", origin / "duplicate")
    with pytest.raises(ValueError, match="unsafe"):
        copies.capture_copy(**kwargs)


def test_output_symlink_refused(sample):
    kwargs, pin = _capture(sample)
    actual = kwargs["output"].with_name("actual")
    kwargs["output"].rename(actual)
    kwargs["output"].symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="unsafe"):
        copies.verify_copy(**kwargs, expected_receipt_sha256=pin)


def test_appearing_sidecar_during_copy_refuses_without_receipt(sample, monkeypatch):
    origin, kwargs = sample
    publish = copies.publish_snapshot

    def changing_publication(path, payload, **arguments):
        publish(path, payload, **arguments)
        if path.name == "scan.sqlite":
            (origin / "primary_scan.sqlite-wal").write_bytes(b"pending transaction")

    monkeypatch.setattr(copies, "publish_snapshot", changing_publication)
    with pytest.raises(ValueError, match="sidecar"):
        copies.capture_copy(**kwargs)
    assert not (kwargs["output"] / "receipt.json").exists()


def test_resealed_receipt_wrong_boundary_refused(sample):
    from src.dante_light.contracts import canonical_json_sha256

    kwargs, _ = _capture(sample)
    path = kwargs["output"] / "receipt.json"
    value = json.loads(path.read_bytes())
    value.pop("receipt_digest")
    value["boundary"]["full_workflow_verified"] = True
    payload = copies._encoded({**value, "receipt_digest": canonical_json_sha256(value)})
    path.chmod(0o600)
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="origin/policy/source"):
        copies.verify_copy(**kwargs, expected_receipt_sha256=copies._sha(payload))


@pytest.mark.parametrize("stage", ["capture", "verify"])
def test_cli_wired_to_explicit_operation(monkeypatch, capsys, stage):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "scan_copy_cli", ROOT / "scripts/copy_dante_o3a_scan_evidence.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    calls = []

    def operation(**kwargs):
        calls.append(kwargs)
        return {"status": "synthetic_transport_only"}

    monkeypatch.setattr(
        copies, "capture_copy" if stage == "capture" else "verify_copy", operation
    )
    argv = [
        "--stage",
        stage,
        "--primary-external-root",
        str(ROOT),
        "--output",
        str(ROOT / "never_written"),
    ]
    if stage == "verify":
        argv += ["--expected-receipt-sha256", "1" * 64]
    assert cli.main(argv) == 0
    assert len(calls) == 1
    assert ("expected_receipt_sha256" in calls[0]) == (stage == "verify")
    assert json.loads(capsys.readouterr().out)["status"] == "synthetic_transport_only"


def test_real_sources_match_executed_transport_on_posix():
    pytest.importorskip("fcntl", reason="source policy uses POSIX capture")
    policy, digest = copies._policy(ROOT)
    assert len(digest) == 64
    assert policy["status"] == "FROZEN_RETAINED_SCAN_ISOLATED_BYTE_COPY_V1"
    sources = copies._sources(ROOT)
    assert "src/dante_workflow/o3a_scan_copy.py" in sources
    assert copies.POLICY_REL in sources
