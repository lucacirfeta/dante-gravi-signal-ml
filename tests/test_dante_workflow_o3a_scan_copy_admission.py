"""Explicit isolated SQL admission; defaults and productive contracts stay strict."""

from contextlib import ExitStack
import ast
import copy
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from src.dante_workflow import o3a_scan_copy as copies
from src.dante_workflow import o3a_scan_copy_admission as admit
from src.dante_workflow import o3a_native_verification as native
from src.dante_workflow import o3a_retained_runtime as runtime
from src.dante_workflow.o3a_initial_verification import _Evidence
from src.dante_workflow.o3a_locking import hold_native_lock

ROOT = Path(__file__).resolve().parents[1]


def fixture_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tests" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sample = fixture_module("test_dante_workflow_o3a_scan_copy").sample
native_evidence = fixture_module("test_dante_workflow_o3a_native_verification").evidence


def setup_admission(sample, *, pin=None):
    origin, kwargs = sample
    receipt = copies.capture_copy(**kwargs)
    evidence = runtime.new_evidence(
        ROOT,
        scan_copy_dir=kwargs["output"],
        expected_scan_copy_receipt_sha256=pin or receipt["receipt_sha256"],
    )
    summary = json.loads((origin / "primary_scan_summary.json").read_bytes())
    return origin, kwargs["output"], evidence, summary


def select(origin, evidence, summary, stack):
    hold_native_lock(origin, evidence=evidence, stack=stack, name="scan")
    return admit.select_scan_database(
        evidence, path=origin / "primary_scan.sqlite", summary=summary, stack=stack
    )


def test_default_factory_has_no_copy_and_original_sidecar_guard_is_strict(sample):
    origin, _ = sample
    evidence = runtime.new_evidence(ROOT)
    assert type(evidence) is _Evidence
    path = origin / "primary_scan.sqlite"
    with ExitStack() as stack:
        assert (
            admit.select_scan_database(evidence, path=path, summary={}, stack=stack)
            == path
        )
    assert runtime.receipt_fields(evidence) == {}
    with pytest.raises(ValueError, match="transaction sidecar"):
        with native.immutable_database(path):
            pass


@pytest.mark.parametrize(
    "arguments",
    [
        {"scan_copy_dir": Path("unused")},
        {"expected_scan_copy_receipt_sha256": "a" * 64},
        {"scan_copy_dir": Path("unused"), "expected_scan_copy_receipt_sha256": "bad"},
        {
            "scan_copy_dir": Path("unused"),
            "expected_scan_copy_receipt_sha256": "A" * 64,
        },
        {"scan_copy_dir": Path("unused"), "expected_scan_copy_receipt_sha256": True},
    ],
)
def test_invalid_partial_opt_in_refused_before_inputs(arguments):
    with pytest.raises(ValueError, match="supplied together|SHA256"):
        runtime.new_evidence(ROOT, **arguments)


def test_admission_holds_original_lock_and_receipt_qualifies_only_bytes(sample):
    import fcntl

    origin, output, evidence, summary = setup_admission(sample)
    before = {
        p.name: (p.read_bytes(), copies._signature(p.stat())) for p in origin.iterdir()
    }
    with ExitStack() as stack:
        path = select(origin, evidence, summary, stack)
        assert path == output / "scan.sqlite"
        assert admit.scan_database_filename(evidence, path) == "primary_scan.sqlite"
        with (origin / "run.lock").open("rb") as handle:
            with pytest.raises(BlockingIOError):
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with native.immutable_database(path) as connection:
            assert connection.execute("SELECT value FROM evidence").fetchall() == [
                ("unchanged",)
            ]
        evidence.unchanged()
        fields = runtime.receipt_fields(evidence)
        assert set(fields) == {"isolated_scan_input_qualification"}
        qualification = fields["isolated_scan_input_qualification"]
        assert qualification["database_sha256"] == summary["database"]["sha256"]
        assert not any(qualification["transport_boundary"].values())
        assert qualification["original_sidecar_pins"]["-journal"] is None
    assert {
        p.name: (p.read_bytes(), copies._signature(p.stat())) for p in origin.iterdir()
    } == before
    with pytest.raises(ValueError, match="held SCAN lock"):
        evidence.unchanged()


def test_no_stack_registration_refuses(sample):
    origin, _, evidence, summary = setup_admission(sample)
    with ExitStack() as stack:
        with pytest.raises(ValueError, match="held SCAN lock"):
            admit.select_scan_database(
                evidence,
                path=origin / "primary_scan.sqlite",
                summary=summary,
                stack=stack,
            )


def test_wrong_receipt_pin_refuses_even_with_original_lock(sample):
    origin, _, evidence, summary = setup_admission(sample, pin="0" * 64)
    with ExitStack() as stack:
        with pytest.raises(ValueError, match="external receipt hash"):
            select(origin, evidence, summary, stack)


def test_gate_summary_identity_cannot_be_substituted(sample):
    origin, _, evidence, summary = setup_admission(sample)
    summary["run_key"] = "other"
    with ExitStack() as stack:
        with pytest.raises(ValueError, match="summary differs"):
            select(origin, evidence, summary, stack)


@pytest.mark.parametrize(
    "location", ["origin_shm", "origin_wal", "copy", "receipt", "copy_sidecar"]
)
def test_final_check_refuses_changed_origin_or_copy(sample, location):
    origin, output, evidence, summary = setup_admission(sample)
    with ExitStack() as stack:
        select(origin, evidence, summary, stack)
        path = {
            "origin_shm": origin / "primary_scan.sqlite-shm",
            "origin_wal": origin / "primary_scan.sqlite-wal",
            "copy": output / "scan.sqlite",
            "receipt": output / "receipt.json",
            "copy_sidecar": output / "scan.sqlite-wal",
        }[location]
        if path.exists():
            path.chmod(0o600)
        path.write_bytes(b"changed")
        with pytest.raises(ValueError, match="changed|sidecar|extra"):
            evidence.unchanged()


def test_copy_sql_path_cannot_be_substituted(sample):
    origin, output, evidence, summary = setup_admission(sample)
    with ExitStack() as stack:
        select(origin, evidence, summary, stack)
        with pytest.raises(ValueError, match="differs from admitted"):
            admit.scan_database_filename(evidence, output / "other.sqlite")


def test_driver_qualification_is_separate_and_composable(sample):
    _, kwargs = sample
    evidence = runtime.new_evidence(
        ROOT,
        allow_retained_driver_drift=True,
        scan_copy_dir=kwargs["output"],
        expected_scan_copy_receipt_sha256="a" * 64,
    )
    assert isinstance(evidence, runtime.RetainedRuntimeEvidence)
    assert isinstance(evidence, admit.RuntimeScanCopyEvidence)
    assert not isinstance(
        runtime.new_evidence(ROOT, allow_retained_driver_drift=True),
        admit.RuntimeScanCopyEvidence,
    )


@pytest.mark.parametrize("stage", ["scan", "cohort"])
def test_real_parent_gates_use_copy_sql_without_opening_historical_database(
    native_evidence, monkeypatch, stage
):
    f = native_evidence
    policy = copies._policy(ROOT)
    sources = copies._sources(ROOT)
    policy_path = f.root / copies.POLICY_REL
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / copies.POLICY_REL, policy_path)
    monkeypatch.setattr(copies, "_policy", lambda root: policy)
    monkeypatch.setattr(copies, "_sources", lambda root: sources)
    saved = json.loads((f.scan_dir / "primary_scan_summary.json").read_bytes())
    monkeypatch.setattr(
        copies,
        "_origin",
        lambda *args: (f.scan_dir, saved["run_key"], saved["contract_digest"]),
    )
    (f.scan_dir / "primary_scan.sqlite-wal").write_bytes(b"")
    (f.scan_dir / "primary_scan.sqlite-shm").write_bytes(bytes(32768))
    output = f.root.parent / ("isolated_" + stage)
    captured = copies.capture_copy(
        root=f.root, primary_external_root=f.primary, output=output
    )
    evidence = runtime.new_evidence(
        f.root,
        scan_copy_dir=output,
        expected_scan_copy_receipt_sha256=captured["receipt_sha256"],
    )
    sql_paths = []
    sql_reader = native.immutable_database

    def isolated_only(path):
        assert path == output / "scan.sqlite"
        sql_paths.append(path)
        return sql_reader(path)

    monkeypatch.setattr(native, "immutable_database", isolated_only)
    before = {
        p.name: (p.read_bytes(), copies._signature(p.stat()))
        for p in f.scan_dir.iterdir()
        if p.is_file()
    }
    with ExitStack() as stack:
        if stage == "scan":
            result, _ = native._scan_gate(
                root=f.root, external_root=f.primary, evidence=evidence, stack=stack
            )
            assert result == saved
        else:
            result, _ = native._cohort_gate(
                root=f.root,
                external_root=f.external,
                primary_external_root=f.primary,
                evidence=evidence,
                stack=stack,
            )
            assert result["status"] == "PASS_FROZEN_O3A_NATIVE_COHORT"
        assert Path(evidence.inputs["scan_database"]["path"]) == output / "scan.sqlite"
        evidence.unchanged()
    assert len(sql_paths) == (1 if stage == "scan" else 3)
    assert {
        p.name: (p.read_bytes(), copies._signature(p.stat()))
        for p in f.scan_dir.iterdir()
        if p.is_file()
    } == before


@pytest.mark.parametrize("script", ["coincidence", "pem"])
def test_cli_paired_copy_arguments_explicit_default_none(monkeypatch, capsys, script):
    from src.dante_workflow import o3a_coincidence_verification as coin
    from src.dante_workflow import o3a_pem_verification as pem
    from src.dante_workflow import evidence_snapshot as snapshots

    spec = importlib.util.spec_from_file_location(
        "copy_input_cli", ROOT / f"scripts/verify_dante_o3a_{script}_evidence.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    seen = []

    def verify(**kwargs):
        seen.append(
            (kwargs["scan_copy_dir"], kwargs["expected_scan_copy_receipt_sha256"])
        )
        return {"status": "SYNTHETIC_COPY_ARGUMENT_WIRING_ONLY"}

    args = []
    names = [
        "taxonomy",
        "classification",
        "threshold",
        "rescore",
        "calibration",
        "index",
        "cohort",
        "primary",
    ]
    if script == "coincidence":
        monkeypatch.setattr(coin, "verify_coincidence_evidence", verify)
        flags = ["external-root"] + [n + "-external-root" for n in names]
    else:
        monkeypatch.setattr(pem, "verify_pem_evidence", verify)
        monkeypatch.setattr(
            snapshots, "read_snapshot_blob", lambda *a, **kw: b"synthetic"
        )
        args += [
            "--snapshot",
            "synthetic",
            "--expected-snapshot-sha256",
            "s",
            "--expected-plan-sha256",
            "p",
        ]
        flags = [n + "-external-root" for n in ["pem", "coincidence", *names]]
    for name in flags:
        args += ["--" + name, str(ROOT)]
    assert cli.main(args) == 0
    assert (
        cli.main(
            args
            + [
                "--scan-copy-dir",
                str(ROOT),
                "--expected-scan-copy-receipt-sha256",
                "a" * 64,
            ]
        )
        == 0
    )
    assert seen == [(None, None), (ROOT, "a" * 64)]
    capsys.readouterr()


@pytest.mark.parametrize("name", ["coincidence", "pem"])
def test_public_api_forwards_both_opt_in_arguments_to_shared_evidence(name):
    tree = ast.parse(
        (ROOT / "src/dante_workflow" / ("o3a_" + name + "_verification.py")).read_text()
    )
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "new_evidence"
    ]
    assert len(calls) == 1
    arguments = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    for key in ("scan_copy_dir", "expected_scan_copy_receipt_sha256"):
        assert isinstance(arguments[key], ast.Name) and arguments[key].id == key


def test_combined_final_guard_preserves_runtime_stability_and_copy_pins(
    sample, monkeypatch
):
    from src.dante_light import o3a_native_contract as nc
    from src.dante_light.contracts import canonical_json_sha256

    origin, kwargs = sample
    captured = copies.capture_copy(**kwargs)
    evidence = runtime.new_evidence(
        ROOT,
        allow_retained_driver_drift=True,
        scan_copy_dir=kwargs["output"],
        expected_scan_copy_receipt_sha256=captured["receipt_sha256"],
    )
    frozen = nc.load_runtime_contract(root=ROOT, require_current=False)
    observed = copy.deepcopy(frozen["runtime_environment"])
    observed.pop("environment_digest")
    observed["cuda_device"]["driver_version"] = "synthetic-only-driver-drift"
    observed["environment_digest"] = canonical_json_sha256(observed)
    monkeypatch.setattr(
        nc, "_capture_o3a_runtime", lambda device: copy.deepcopy(observed)
    )
    evidence.load_runtime(lambda **kwargs: frozen, root=ROOT)
    summary = json.loads((origin / "primary_scan_summary.json").read_bytes())
    with ExitStack() as stack:
        select(origin, evidence, summary, stack)
        evidence.unchanged()
        fields = runtime.receipt_fields(evidence)
        assert set(fields) == {
            "retained_runtime_qualification",
            "isolated_scan_input_qualification",
        }
        assert fields["retained_runtime_qualification"]["driver_version_changed"]
        observed["cuda_device"]["name"] = "runtime changed after admission"
        with pytest.raises(ValueError, match="runtime changed"):
            evidence.unchanged()


def test_transport_receipt_sources_do_not_depend_on_reader_edits():
    sources = copies._sources(ROOT)
    assert len(sources) == 17
    assert "src/dante_workflow/o3a_native_verification.py" not in sources
    assert "src/dante_workflow/o3a_retained_runtime.py" not in sources
    assert len(native._sources(ROOT)) == 22
