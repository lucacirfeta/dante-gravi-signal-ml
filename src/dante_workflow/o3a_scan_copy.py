"""Isolated sealed SCAN bytes, not SQLite repair or scientific verification."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path

from .evidence_snapshot import publish_snapshot, read_capture_file, _signature
from .o3a_initial_verification import InitialEvidenceError, _Evidence
from .o3a_locking import hold_native_lock

POLICY_REL = "config/dante_workflow_o3a_scan_copy_v1.json"
STATUS = "SEALED_ISOLATED_SCAN_DATABASE_BYTES_ONLY_V1"
FILES = {"database": "scan.sqlite", "-wal": "origin_wal.bin", "-shm": "origin_shm.bin"}


def _encoded(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


def _read(path, maximum):
    info = path.lstat()
    if info.st_size > maximum:
        raise InitialEvidenceError("isolated copy input exceeds byte limit")
    payload = read_capture_file(path, size=info.st_size)
    if _signature(path.lstat()) != _signature(info):
        raise InitialEvidenceError("isolated copy origin metadata changed")
    return payload, {
        "sha256": _sha(payload),
        "size_bytes": len(payload),
        "signature": list(_signature(info)),
    }


def _policy(root):
    value, _ = _read(root / POLICY_REL, 8388608)
    policy = json.loads(value)
    expected = {
        "schema_version": 1,
        "status": "FROZEN_RETAINED_SCAN_ISOLATED_BYTE_COPY_V1",
        "database_bytes": "exact_sealed_primary_scan_summary_sha256_and_size",
        "wal": "absent_or_zero_bytes_only",
        "shm": "absent_or_exact_32768_bytes_preserved_as_inert_provenance",
        "journal": "absent_only",
        "lock": "existing_read_only_nonblocking_exclusive_flock",
        "publication": "exclusive_new_directory_receipt_last_no_overwrite_no_resume",
        "platform": "posix_descriptor_relative_nofollow",
        "limits": {"database_bytes": 536870912, "metadata_bytes": 8388608},
        "boundary": {
            name: False
            for name in (
                "historical_artifacts_modified",
                "historical_sqlite_opened",
                "transactions_replayed_or_checkpointed",
                "global_writer_quiescence_proved",
                "scientific_parent_closure_verified",
                "runtime_equivalence_proved",
                "full_workflow_verified",
            )
        },
    }
    if _encoded(policy) != _encoded(expected):
        raise InitialEvidenceError("isolated SCAN copy policy changed")
    return policy, _sha(value)


def _origin(root, primary_external_root):
    from src.dante_light import o3a_primary_scan as scan

    contract = scan.load_scan_contract(root=root)
    runtime = scan.load_runtime_contract(root=root, require_current=False)
    key = scan._run_key(
        contract,
        environment_digest=runtime["runtime_environment"]["environment_digest"],
    )
    return (
        primary_external_root / ("primary_scan_" + key),
        key,
        contract["contract_digest"],
    )


def _sources(root):
    import importlib

    value = {}
    # Bind the transport's executed closure, not future downstream reader edits.
    for name in (
        "contracts",
        "o3a_initial_calibration",
        "o3a_initial_thresholds",
        "o3a_initial_calibration_acceptance",
        "o3a_raw_acquisition",
        "o3a_raw_download",
        "o3a_native_contract",
        "o4a_corrected_runtime",
        "o3a_population_geometry",
        "o3a_scale_adequacy",
        "o3a_primary_scan",
    ):
        module = importlib.import_module("src.dante_light." + name)
        relative = module.__name__.replace(".", "/") + ".py"
        digest = _sha(Path(module.__file__).read_bytes())
        if _sha((root / relative).read_bytes()) != digest:
            raise InitialEvidenceError(
                "isolated copy executed source differs from repository"
            )
        value[relative] = digest
    for relative in (
        POLICY_REL,
        "src/dante_workflow/o3a_scan_copy.py",
        "src/dante_workflow/evidence_snapshot.py",
        "src/dante_workflow/o3a_initial_verification.py",
        "src/dante_workflow/o3a_locking.py",
        "scripts/copy_dante_o3a_scan_evidence.py",
    ):
        value[relative] = _sha((root / relative).read_bytes())
    # Bind the actual executed transport helpers, not an arbitrary other checkout.
    executed = Path(__file__).resolve().parents[2]
    for relative, digest in value.items():
        if _sha((executed / relative).read_bytes()) != digest:
            raise InitialEvidenceError(
                "isolated copy executed source differs from repository"
            )
    return value


def _observe(directory, policy):
    from src.dante_light.contracts import canonical_json_sha256

    summary_bytes, summary_pin = _read(
        directory / "primary_scan_summary.json", policy["limits"]["metadata_bytes"]
    )
    summary = json.loads(summary_bytes)
    body = dict(summary)
    seal = body.pop("artifact_digest", None)
    if (
        seal != canonical_json_sha256(body)
        or summary["status"] != "PASS_COMPLETE_O3A_PRIMARY_SCAN"
    ):
        raise InitialEvidenceError("isolated copy SCAN summary seal/status changed")
    if summary["database"]["filename"] != "primary_scan.sqlite":
        raise InitialEvidenceError("isolated copy database filename changed")
    database, pin = _read(
        directory / "primary_scan.sqlite", policy["limits"]["database_bytes"]
    )
    if (
        pin["sha256"] != summary["database"]["sha256"]
        or pin["size_bytes"] != summary["database"]["size_bytes"]
    ):
        raise InitialEvidenceError(
            "isolated copy database differs from sealed SCAN summary"
        )
    if not database.startswith(b"SQLite format 3\x00"):
        raise InitialEvidenceError("isolated copy is not a SQLite container")
    payloads, pins = {"database": database}, {"summary": summary_pin, "database": pin}
    for suffix in ("-wal", "-shm", "-journal"):
        path = directory / ("primary_scan.sqlite" + suffix)
        present = path.exists() or path.is_symlink()
        if suffix == "-journal" and present:
            raise InitialEvidenceError("rollback journal present; no repair attempted")
        if not present:
            pins[suffix] = None
            continue
        payload, side_pin = _read(path, policy["limits"]["metadata_bytes"])
        if (suffix == "-wal" and payload) or (
            suffix == "-shm" and len(payload) != 32768
        ):
            raise InitialEvidenceError(
                "unsupported transaction sidecar; no repair attempted"
            )
        payloads[suffix], pins[suffix] = payload, side_pin
    return summary, payloads, pins


def _safe_output(output, origin, root):
    if os.name != "posix" or not output.is_absolute() or ".." in output.parts:
        raise InitialEvidenceError(
            "isolated copy publication requires absolute POSIX output"
        )
    if output.parent.resolve(strict=True) != output.parent:
        raise InitialEvidenceError("isolated copy output traverses links")
    if (
        output.is_relative_to(origin)
        or origin.is_relative_to(output)
        or output.is_relative_to(root)
    ):
        raise InitialEvidenceError(
            "isolated copy output overlaps historical/repository inputs"
        )


def _new_directory(output, origin, root):
    _safe_output(output, origin, root)
    with ExitStack() as stack:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, descriptor)
        for part in output.parent.parts[1:]:
            descriptor = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            stack.callback(os.close, descriptor)
        os.mkdir(output.name, mode=0o700, dir_fd=descriptor)


def _directory_identity(output):
    if output.is_symlink() or not output.is_dir():
        raise InitialEvidenceError("isolated copy directory replaced or unsafe")
    info = output.stat()
    return info.st_dev, info.st_ino


def _verify_files(output, files, policy, *, receipt_present):
    names = set(files) | ({"receipt.json"} if receipt_present else set())
    if {p.name for p in output.iterdir()} != names:
        raise InitialEvidenceError(
            "isolated copy output has extra/partial/transaction files"
        )
    pins = {}
    for name, expected in files.items():
        _, actual = _read(output / name, policy["limits"]["database_bytes"])
        if (
            actual["sha256"] != expected["sha256"]
            or actual["size_bytes"] != expected["size_bytes"]
        ):
            raise InitialEvidenceError("isolated copy file hash/size changed")
        pins[name] = actual
    return pins


def capture_copy(*, root, primary_external_root, output):
    """New isolated files only; no historical SQL connection, update or unlink."""
    from src.dante_light.contracts import canonical_json_sha256

    root, primary_external_root, output = map(
        Path, (root, primary_external_root, output)
    )
    policy, policy_sha = _policy(root)
    sources = _sources(root)
    origin, key, contract_digest = _origin(root, primary_external_root)
    evidence = _Evidence()
    with ExitStack() as stack:
        hold_native_lock(origin, evidence=evidence, stack=stack, name="scan")
        summary, payloads, pins = _observe(origin, policy)
        if summary["run_key"] != key or summary["contract_digest"] != contract_digest:
            raise InitialEvidenceError("isolated copy SCAN identity changed")
        _new_directory(output, origin, root)
        output_identity = _directory_identity(output)
        for name, payload in payloads.items():
            publish_snapshot(
                output / FILES[name],
                payload,
                roots={"scan": origin, "repository": root},
            )
        if _observe(origin, policy)[2] != pins or _sources(root) != sources:
            raise InitialEvidenceError(
                "isolated copy origin/source changed; preserve incomplete output"
            )
        evidence.unchanged()
        body = {
            "schema_version": 1,
            "status": STATUS,
            "run_key": key,
            "contract_digest": contract_digest,
            "source_run_dir": str(origin),
            "summary_artifact_digest": summary["artifact_digest"],
            "policy_sha256": policy_sha,
            "source_bindings": sources,
            "origin_pins": pins,
            "lock_input": evidence.inputs["scan_lock"],
            "files": {
                FILES[name]: {
                    "sha256": pins[name]["sha256"],
                    "size_bytes": pins[name]["size_bytes"],
                }
                for name in payloads
            },
            "boundary": policy["boundary"],
        }
        receipt = {**body, "receipt_digest": canonical_json_sha256(body)}
        _verify_files(output, body["files"], policy, receipt_present=False)
        if _directory_identity(output) != output_identity:
            raise InitialEvidenceError("isolated copy directory changed during capture")
    # The lock exit must succeed before a successful receipt can be published.
    publish_snapshot(
        output / "receipt.json",
        _encoded(receipt),
        roots={"scan": origin, "repository": root},
    )
    if _directory_identity(output) != output_identity:
        raise InitialEvidenceError("isolated copy directory changed during publication")
    return {
        "status": STATUS,
        "output": str(output),
        "receipt_sha256": _sha(_encoded(receipt)),
        "receipt_digest": receipt["receipt_digest"],
        "database_sha256": pins["database"]["sha256"],
        "database_size_bytes": pins["database"]["size_bytes"],
        "boundary": policy["boundary"],
    }


def verify_copy(*, root, primary_external_root, output, expected_receipt_sha256):
    """Standalone externally pinned byte verifier; not a second source fetch."""
    from src.dante_light.contracts import canonical_json_sha256

    root, primary_external_root, output = map(
        Path, (root, primary_external_root, output)
    )
    policy, policy_sha = _policy(root)
    sources = _sources(root)
    origin, key, contract_digest = _origin(root, primary_external_root)
    _safe_output(output, origin, root)
    output_identity = _directory_identity(output)
    payload, _ = _read(output / "receipt.json", policy["limits"]["metadata_bytes"])
    if _sha(payload) != expected_receipt_sha256:
        raise InitialEvidenceError("isolated copy external receipt hash mismatch")
    receipt = json.loads(payload)
    body = dict(receipt)
    seal = body.pop("receipt_digest", None)
    if seal != canonical_json_sha256(body):
        raise InitialEvidenceError("isolated copy receipt seal changed")
    evidence = _Evidence()
    with ExitStack() as stack:
        hold_native_lock(origin, evidence=evidence, stack=stack, name="scan")
        summary, payloads, pins = _observe(origin, policy)
        expected = {
            "schema_version": 1,
            "status": STATUS,
            "run_key": key,
            "contract_digest": contract_digest,
            "source_run_dir": str(origin),
            "summary_artifact_digest": summary["artifact_digest"],
            "policy_sha256": policy_sha,
            "source_bindings": sources,
            "origin_pins": pins,
            "lock_input": evidence.inputs["scan_lock"],
            "files": {
                FILES[name]: {
                    "sha256": pins[name]["sha256"],
                    "size_bytes": pins[name]["size_bytes"],
                }
                for name in payloads
            },
            "boundary": policy["boundary"],
        }
        if (
            _encoded(body) != _encoded(expected)
            or summary["run_key"] != key
            or summary["contract_digest"] != contract_digest
        ):
            raise InitialEvidenceError(
                "isolated copy receipt origin/policy/source identity changed"
            )
        output_pins = _verify_files(
            output, receipt["files"], policy, receipt_present=True
        )
        if _observe(origin, policy)[2] != pins or _sources(root) != sources:
            raise InitialEvidenceError(
                "isolated copy origin/source changed during verification"
            )
        if (
            _read(output / "receipt.json", policy["limits"]["metadata_bytes"])[0]
            != payload
        ):
            raise InitialEvidenceError(
                "isolated copy receipt changed during verification"
            )
        evidence.unchanged()
        if (
            _verify_files(output, receipt["files"], policy, receipt_present=True)
            != output_pins
            or _directory_identity(output) != output_identity
        ):
            raise InitialEvidenceError(
                "isolated copy output changed during verification"
            )
    return {
        "status": "PASS_VERIFIED_ISOLATED_SCAN_DATABASE_BYTES_ONLY_V1",
        "receipt_sha256": expected_receipt_sha256,
        "receipt_digest": seal,
        "database_sha256": pins["database"]["sha256"],
        "database_size_bytes": pins["database"]["size_bytes"],
        "source_binding_count": len(sources),
        "boundary": policy["boundary"],
    }
