"""New-container admission never relabels immutable historical evidence."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.dante_workflow import calibration_admission as admission, cli
from src.dante_workflow import calibration_recovery as recovery
from src.dante_workflow.input_coverage import InputCoverageError
from tests.test_dante_workflow_calibration_recovery import case  # noqa: F401


@pytest.fixture
def admitted_case(case, tmp_path, monkeypatch):  # noqa: F811
    root, _, initial, checksums, download = case
    plan = deepcopy(initial)
    plan["parent"]["seal_field"] = "protocol_digest"
    plan["historical_receipt"]["manifest_digest"] = "synthetic historical seal"
    oldpath = Path(plan["historical_receipt_path"])
    oldpath.write_text(json.dumps(plan["historical_receipt"]))
    plan["historical_receipt_sha256"] = recovery._hash(oldpath)
    plan.pop("digest")
    plan = recovery.sealed(plan)
    for source in admission.SOURCES:
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic admission source")
    run = tmp_path / "recovered"
    recovery.acquire(
        plan, run, root=root, checksum_fetch=checksums, downloader=download
    )
    recovery.write_json(run / "verification.json", recovery.verify(run, root=root))
    policy = {
        "schema_version": 1,
        "scope": "CALIBRATION_RECOVERED_INPUT_ADMISSION_ONLY",
        "identity_rule": "EXACT_NATIVE_NUMERICAL_SHA_NEW_CONTAINER_RECEIPT",
        "historical_receipt_sha256": plan["historical_receipt_sha256"],
        "parent": plan["parent"],
        "plan_sha256": recovery._hash(run / "plan.json"),
        "summary_sha256": recovery._hash(run / "summary.json"),
        "verification_sha256": recovery._hash(run / "verification.json"),
        "interval_count": 1,
        "scientific_execution_ready": False,
    }
    policy_path = root / "policy.json"
    policy_path.write_text(json.dumps(policy))
    diagnosis = {
        "status": "BLOCKED_CALIBRATION_SUPPLEMENT_REQUIRED",
        "input_contract": plan["parent"],
        "blockers": ["PINNED_ACQUISITION_RECEIPT_REQUIRED"],
        "identity_count": 1,
        "counts": {"H1": 1},
        "scientific_execution_ready": False,
        "raw_samples_checked": False,
    }
    missing = [("H1", 103, 118)]
    monkeypatch.setattr(
        admission, "missing_intervals", lambda *a: (diagnosis, {}, missing)
    )
    monkeypatch.setattr(
        admission, "inspect_calibration_inputs", lambda *a, **k: diagnosis
    )
    return SimpleNamespace(
        root=root,
        run=run,
        policy=policy,
        policy_path=policy_path,
        oldpath=oldpath,
        output=tmp_path / "admission" / "receipt.json",
        kwargs=dict(
            root=root,
            policy_path=policy_path,
            policy_sha=recovery._hash(policy_path),
            recovery_dir=run,
        ),
    )


def create(c):
    return admission.create_receipt(None, None, output=c.output, **c.kwargs)


def inspect(c):
    return admission.inspect_admitted_inputs(
        None,
        None,
        root=c.root,
        receipt_path=c.output,
        receipt_sha=recovery._hash(c.output),
    )


def test_exact_receipt_and_independent_readiness(admitted_case, monkeypatch):
    c = admitted_case
    oldsha = recovery._hash(c.oldpath)
    before = {
        p.relative_to(c.run): recovery._hash(p) for p in c.run.rglob("*") if p.is_file()
    }
    monkeypatch.setattr(recovery, "download", lambda *a: pytest.fail("no fetch"))
    row = create(c)["records"][0]
    assert row["file_sha256"] != row["historical_file_sha256"]
    assert row["strain_values_sha256"] == row["historical_strain_values_sha256"]
    result = inspect(c)
    assert result["status"] == "PASS_CALIBRATION_DECLARED_INPUTS_ONLY"
    assert result["calibration_declared_input_coverage_checked"] is True
    assert result["recovered_context_numerical_parity_checked"] is True
    assert result["scientific_execution_ready"] is False
    assert result["raw_samples_checked"] is False
    assert result["identity_count"] == 1
    assert recovery._hash(c.oldpath) == oldsha
    assert before == {
        p.relative_to(c.run): recovery._hash(p) for p in c.run.rglob("*") if p.is_file()
    }


def test_no_overwrite_or_historical_write(admitted_case):
    c = admitted_case
    create(c)
    with pytest.raises(InputCoverageError, match="no overwrite"):
        create(c)
    for output in (c.run / "admission.json", c.root / "admission.json"):
        with pytest.raises(InputCoverageError):
            admission.create_receipt(None, None, output=output, **c.kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("interval_count", 2),
        ("schema_version", True),
        ("historical_receipt_sha256", "0" * 64),
        ("parent", {}),
        ("identity_rule", "TOLERANCE"),
        ("scientific_execution_ready", True),
        ("verification_sha256", "f" * 64),
    ],
)
def test_changed_policy_refused(admitted_case, field, value):
    c = admitted_case
    c.policy[field] = value
    c.policy_path.write_text(json.dumps(c.policy))
    c.kwargs["policy_sha"] = recovery._hash(c.policy_path)
    with pytest.raises((ValueError, recovery.RecoveryError)):
        create(c)
    assert not c.output.exists()


def test_parent_requires_exact_seal_field(admitted_case):
    c = admitted_case
    c.policy["parent"].pop("seal_field")
    c.policy_path.write_text(json.dumps(c.policy))
    c.kwargs["policy_sha"] = recovery._hash(c.policy_path)
    with pytest.raises(InputCoverageError, match="parent/population"):
        create(c)


@pytest.mark.parametrize(
    "field,value",
    [
        ("scientific_execution_ready", True),
        ("records", []),
        ("record_count", 2),
        ("parent", {}),
        ("source_hashes", {}),
    ],
)
def test_resealed_false_receipt_refused(admitted_case, field, value):
    c = admitted_case
    result = create(c)
    result.pop("digest")
    result[field] = value
    c.output.write_text(json.dumps(recovery.sealed(result)))
    with pytest.raises(InputCoverageError, match="independent replay"):
        inspect(c)


@pytest.mark.parametrize("target", ["old", "context", "source", "frame"])
def test_post_admission_bytes_drift_refused(admitted_case, target):
    c = admitted_case
    result = create(c)
    path = {
        "old": c.oldpath,
        "context": c.run / result["records"][0]["relative_path"],
        "source": c.root / admission.SOURCES[0],
        "frame": next((c.run / "frames").glob("*.hdf5")),
    }[target]
    path.write_bytes(b"corrupted")
    with pytest.raises(Exception):
        inspect(c)


@pytest.mark.parametrize("sha", [None, "0" * 64, "invalid"])
def test_unpinned_receipt_refused(admitted_case, sha):
    c = admitted_case
    create(c)
    with pytest.raises(InputCoverageError):
        admission.inspect_admitted_inputs(
            None, None, root=c.root, receipt_path=c.output, receipt_sha=sha
        )


def test_missing_recovery_file_refused(admitted_case):
    c = admitted_case
    (c.run / "verification.json").unlink()
    with pytest.raises(Exception):
        create(c)


@pytest.mark.parametrize("name", ["controller.lock", "failure.json", "bad.partial"])
def test_dirty_recovery_refused(admitted_case, name):
    c = admitted_case
    (c.run / name).write_text("preserve")
    with pytest.raises(recovery.RecoveryError):
        create(c)
    assert (c.run / name).exists()


def test_cli_explicit_admission_wired(admitted_case, monkeypatch, capsys):
    c = admitted_case
    create(c)
    monkeypatch.setattr(
        cli,
        "_registry",
        lambda a: SimpleNamespace(resolve_workflow=lambda *a: c.root / "cfg"),
    )
    monkeypatch.setattr(cli, "load_workflow_spec", lambda *a, **k: None)
    monkeypatch.setattr(cli, "build_adapter", lambda *a: None)
    monkeypatch.setattr(cli, "WorkflowOrchestrator", None)
    args = [
        "calibration-readiness",
        "--observing-run",
        "O4a",
        "--detectors",
        "H1",
        "--repository-root",
        str(c.root),
        "--recovery-admission",
        str(c.output),
    ]
    assert cli.main(args) == 1
    capsys.readouterr()
    args += ["--recovery-admission-sha256", recovery._hash(c.output)]
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["scientific_execution_ready"] is False
    assert cli.main(args + ["--acquisition-manifest", str(c.oldpath)]) == 1
