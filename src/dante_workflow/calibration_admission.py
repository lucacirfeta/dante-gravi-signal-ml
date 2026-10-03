"""Explicit numerical-parity admission; historical transport evidence is immutable."""

from pathlib import Path
import re

from .calibration_inputs import inspect_calibration_inputs
from .calibration_recovery import read_sealed, sealed, verify, write_json
from .calibration_transport import missing_intervals
from .input_coverage import InputCoverageError, _read
from .input_preflight import _file, _hash
from .schema_v2 import strict_json_object


SOURCES = (
    "src/dante_workflow/calibration_admission.py",
    "scripts/admit_dante_workflow_calibration_recovery.py",
    "src/dante_workflow/cli.py",
)


def _pinned(path, sha):
    path = Path(path)
    if (
        not path.is_absolute()
        or any(p.is_symlink() for p in (path, *path.parents))
        or not isinstance(sha, str)
        or not re.fullmatch(r"[0-9a-f]{64}", sha)
        or _hash(path) != sha
    ):
        raise InputCoverageError("admission path/SHA pin mismatch")
    return path


def _directory(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise InputCoverageError("absolute non-symlink recovery directory required")
    return path


def build_receipt(spec, adapter, *, root, policy_path, policy_sha, recovery_dir):
    """Replay locally before binding new containers to exact old numerical hashes."""
    root = Path(root).resolve()
    policy_path = _pinned(policy_path, policy_sha)
    policy = strict_json_object(_read(policy_path).decode(), label="admission policy")
    expected_fields = {
        "schema_version",
        "scope",
        "identity_rule",
        "historical_receipt_sha256",
        "parent",
        "plan_sha256",
        "summary_sha256",
        "verification_sha256",
        "interval_count",
        "scientific_execution_ready",
    }
    if (
        set(policy) != expected_fields
        or type(policy["schema_version"]) is not int
        or policy["schema_version"] != 1
        or policy["scope"] != "CALIBRATION_RECOVERED_INPUT_ADMISSION_ONLY"
        or policy["identity_rule"] != "EXACT_NATIVE_NUMERICAL_SHA_NEW_CONTAINER_RECEIPT"
        or policy["scientific_execution_ready"] is not False
        or type(policy["interval_count"]) is not int
        or policy["interval_count"] <= 0
    ):
        raise InputCoverageError("admission policy schema/scope mismatch")
    recovery_dir = _directory(recovery_dir)
    for name in ("plan", "summary", "verification"):
        _pinned(recovery_dir / (name + ".json"), policy[name + "_sha256"])
    plan = read_sealed(recovery_dir / "plan.json")
    summary = read_sealed(recovery_dir / "summary.json")
    previous = read_sealed(recovery_dir / "verification.json")
    diagnosis, _, missing = missing_intervals(spec, adapter, root)
    if (
        plan["parent"] != diagnosis["input_contract"]
        or plan["parent"] != policy["parent"]
        or plan["historical_receipt_sha256"] != policy["historical_receipt_sha256"]
        or len(missing) != policy["interval_count"]
        or {(r["detector"], r["gps_start"], r["gps_end"]) for r in summary["records"]}
        != set(missing)
        or len(summary["records"]) != len(missing)
    ):
        raise InputCoverageError("admission historical parent/population mismatch")
    # Unmodified frozen verifier checks every retained frame and direct HDF5 slice.
    replay = verify(recovery_dir, root=root)
    if replay != previous or replay["status"] != "PASS_VERIFIED_RAW_NUMERIC_MATCH_ONLY":
        raise InputCoverageError("admission independent replay differs")
    old = {
        (r["detector"], r["gps_start"], r["gps_end"]): r
        for r in plan["historical_receipt"]["records"]
    }
    records = []
    for row in summary["records"]:
        key = row["detector"], row["gps_start"], row["gps_end"]
        path = _file(recovery_dir, row["path"])
        records.append(
            {
                "detector": key[0],
                "gps_start": key[1],
                "gps_end": key[2],
                "relative_path": row["path"],
                "file_sha256": row["file_sha256"],
                "historical_file_sha256": old[key]["file_sha256"],
                "strain_values_sha256": row["strain_values_sha256"],
                "historical_strain_values_sha256": old[key]["strain_values_sha256"],
                "sample_rate_hz": plan["sample_rate_hz"],
                "sample_count": row["sample_count"],
                "dtype": row["dtype"],
                "size_bytes": path.stat().st_size,
                "container_bytes_match": row["container_bytes_match"],
            }
        )
    result = sealed(
        {
            "schema_version": 1,
            "status": "PASS_RECOVERED_CALIBRATION_INPUT_ADMISSION_ONLY",
            "policy": {"path": str(policy_path), "sha256": policy_sha},
            "parent": plan["parent"],
            "historical_receipt": {
                "path": plan["historical_receipt_path"],
                "sha256": plan["historical_receipt_sha256"],
                "seal": plan["historical_receipt"]["manifest_digest"],
            },
            "recovery_directory": str(recovery_dir),
            "recovery_plan_digest": plan["digest"],
            "recovery_summary_digest": summary["digest"],
            "recovery_verification_digest": replay["digest"],
            "record_count": len(records),
            "records": records,
            "source_hashes": {p: _hash(_file(root, p)) for p in SOURCES},
            "replacement_containers_admitted_for_declared_input_gate": True,
            "scientific_execution_ready": False,
            "verification_was_second_fetch": False,
        }
    )
    _pinned(policy_path, policy_sha)
    for name in ("plan", "summary", "verification"):
        _pinned(recovery_dir / (name + ".json"), policy[name + "_sha256"])
    if inspect_calibration_inputs(spec, adapter, root=root) != diagnosis:
        raise InputCoverageError("calibration metadata changed during admission")
    return result


def create_receipt(spec, adapter, *, output, root, **kwargs):
    output = Path(output)
    if (
        not output.is_absolute()
        or output.resolve().is_relative_to(Path(root).resolve())
        or any(p.is_symlink() for p in (output, *output.parents))
        or output.exists()
        or output.with_suffix(output.suffix + ".tmp").exists()
    ):
        raise InputCoverageError(
            "new external admission receipt required; no overwrite"
        )
    recovery_dir = _directory(kwargs["recovery_dir"])
    if output.resolve().is_relative_to(recovery_dir.resolve()):
        raise InputCoverageError("admission must not modify historical recovery run")
    result = build_receipt(spec, adapter, root=root, **kwargs)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the final path exclusively before writing; never overwrite old evidence.
    with output.open("x", encoding="utf-8"):
        pass
    write_json(output, result)
    return result


def inspect_admitted_inputs(spec, adapter, *, root, receipt_path, receipt_sha):
    path = _pinned(receipt_path, receipt_sha)
    actual = read_sealed(path)
    expected = build_receipt(
        spec,
        adapter,
        root=root,
        policy_path=actual["policy"]["path"],
        policy_sha=actual["policy"]["sha256"],
        recovery_dir=actual["recovery_directory"],
    )
    if actual != expected:
        raise InputCoverageError("admission receipt differs from independent replay")
    _pinned(path, receipt_sha)
    diagnosis = inspect_calibration_inputs(spec, adapter, root=root)
    return {
        **diagnosis,
        "status": "PASS_CALIBRATION_DECLARED_INPUTS_ONLY",
        "blockers": [],
        "calibration_declared_input_coverage_checked": True,
        "recovered_context_numerical_parity_checked": True,
        "acquisition_receipt": {
            "path": str(path),
            "sha256": receipt_sha,
            "seal": actual["digest"],
            "record_count": actual["record_count"],
            "schema": "RECOVERED_NUMERICAL_PARITY_ADMISSION_V1",
        },
    }
