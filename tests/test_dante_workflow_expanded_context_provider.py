"""Exact expanded consumer: real synthetic HDF5, no scoring or default mutation."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_workflow import expanded_context_provider as consumer
from src.dante_workflow import calibration_expanded_admission as admission
from tests.test_dante_workflow_calibration_expanded_admission import (
    case as raw_case,  # noqa: F401 - shared native transport fixture
    put,
    recover,
    replay,
)


@pytest.fixture
def ready(request, monkeypatch):
    from gwpy.timeseries import TimeSeries

    c = request.getfixturevalue("raw_case")
    recover(c)
    put(c.run_dir / "verification.json", replay(c))
    receipt = admission.admit(
        c.run_dir,
        root=c.root,
        plan_sha=admission._hash(c.run_dir / "plan.json"),
        summary_sha=admission._hash(c.run_dir / "summary.json"),
        verification_sha=admission._hash(c.run_dir / "verification.json"),
    )
    put(c.run_dir / "admission.json", receipt)
    contract = deepcopy(
        json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "config/dante_workflow_expanded_context_provider_v1.json"
            ).read_text()
        )
    )
    contract["admission_policy"] = {
        "path": "policy.json",
        "sha256": c.args["policy_sha"],
    }
    contract["evidence_sha256"] = {
        name: admission._hash(c.run_dir / name) for name in contract["evidence_sha256"]
    }
    for path in contract["source_paths"]:
        target = c.root / path
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((Path(__file__).resolve().parents[1] / path).read_bytes())
    c.prior.read = lambda **kw: SimpleNamespace(
        series=TimeSeries(
            np.arange(50, 66, dtype=np.float64),
            t0=110,
            sample_rate=4,
            name="H1:GWOSC-16KHZ_R1_STRAIN",
        )
    )
    monkeypatch.setattr(consumer, "population", lambda *a: (c.metadata, c.prior))
    c.contract, c.contract_path = contract, c.root / "consumer.json"
    c.contract_sha = put(c.contract_path, contract)
    c.kwargs = dict(
        root=c.root,
        contract_path=c.contract_path,
        contract_sha=c.contract_sha,
        run_dir=c.run_dir,
    )
    return c


def bind(c):
    return consumer.ExpandedCalibrationContextProvider(**c.kwargs)


def repin(c, name, value):
    put(c.run_dir / name, value)
    c.contract["evidence_sha256"][name] = admission._hash(c.run_dir / name)
    c.kwargs["contract_sha"] = put(c.contract_path, c.contract)


def test_new_prior_and_shared_identity_are_exact_without_network_or_scoring(
    ready, monkeypatch
):
    monkeypatch.setattr(
        admission, "verify", lambda *a, **kw: pytest.fail("no repeated08.34 verifier")
    )
    monkeypatch.setattr(admission, "download", lambda *a: pytest.fail("no transport"))
    p = bind(ready)
    assert p.identity_counts == {"H1": 3}
    assert len(p.allowed) == 2 and len(p.rows) == 1
    context = p.read(detector="H1", start=100.25, end=104.25)
    np.testing.assert_array_equal(context.series.value, np.arange(1, 17))
    assert context.sources[0].used_start == 100.25
    np.testing.assert_array_equal(
        p.read(detector="H1", start=110, end=114).series.value, np.arange(50, 66)
    )
    assert p.receipt["boundary"]["scientific_execution_ready"] is False


@pytest.mark.parametrize("field", list(consumer.BOUNDARY))
def test_boundary_cannot_be_promoted_or_numerically_spoofed(ready, field):
    ready.contract["boundary"][field] = int(ready.contract["boundary"][field])
    ready.kwargs["contract_sha"] = put(ready.contract_path, ready.contract)
    with pytest.raises(ValueError, match="authority"):
        bind(ready)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("status", "PASS"),
        ("reader_reference", "fallback"),
        ("input_rule", "all runs"),
        ("representation_rule", "resample"),
    ],
)
def test_consumer_contract_rules_fail_closed(ready, field, value):
    ready.contract[field] = value
    ready.kwargs["contract_sha"] = put(ready.contract_path, ready.contract)
    with pytest.raises(ValueError, match="authority"):
        bind(ready)


@pytest.mark.parametrize(
    "name", ["plan.json", "summary.json", "verification.json", "admission.json"]
)
def test_changed_evidence_bytes_rejected_before_context_read(ready, name):
    path = ready.run_dir / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="pin"):
        bind(ready)


@pytest.mark.parametrize("name", ["admission.json", "verification.json"])
def test_resealed_fake_pass_is_not_parent_evidence(ready, name):
    value = admission.read_sealed(ready.run_dir / name)
    value.pop("digest")
    value["identity_count"] += 1
    repin(ready, name, admission.sealed(value))
    with pytest.raises(ValueError, match="relationship"):
        bind(ready)


@pytest.mark.parametrize(
    "name", ["controller.lock", "failure.json", "contexts/x.partial", "contexts/x.tmp"]
)
def test_active_or_incomplete_recovery_refused(ready, name):
    (ready.run_dir / name).write_text("preserve")
    with pytest.raises(ValueError, match="incomplete"):
        bind(ready)
    assert (ready.run_dir / name).exists()


@pytest.mark.parametrize(
    "fault", ["duplicate", "geometry", "detector", "missing", "prior_container"]
)
def test_exact_population_and_prior_split_refused(ready, fault):
    if fault == "duplicate":
        ready.metadata.append(deepcopy(ready.metadata[0]))
    elif fault == "geometry":
        ready.metadata[0]["required_padded_interval"][0] += 0.25
    elif fault == "detector":
        ready.metadata[0]["detector"] = "L1"
    elif fault == "missing":
        ready.metadata.pop()
    else:
        ready.prior.rows["H1", 110, 114]["file_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="identity|population|container"):
        bind(ready)


@pytest.mark.parametrize(
    "detector,start,end",
    [
        ("L1", 100.25, 104.25),
        ("H1", 100.5, 104.5),
        ("H1", 100.25, 104),
        ("H1", True, 104.25),
        ("H1", float("nan"), 104.25),
        ("V1", 110, 114),
    ],
)
def test_no_detector_or_interval_fallback(ready, detector, start, end):
    with pytest.raises(ValueError, match="exact expanded"):
        bind(ready).read(detector=detector, start=start, end=end)


@pytest.mark.parametrize(
    "fault",
    [
        "file",
        "row_receipt",
        "admission",
        "source",
        "contract",
        "prior_values",
        "prior_name",
        "lock",
    ],
)
def test_drift_after_binding_stops_read_without_fallback(ready, fault):
    p = bind(ready)
    kwargs = dict(detector="H1", start=100.25, end=104.25)
    if fault in ("file", "row_receipt"):
        row = next(iter(p.rows.values()))
        path = ready.run_dir / row["relative_path"]
        if fault == "row_receipt":
            path = path.with_suffix(".json")
            path.write_text('{"invalid":true}')
        else:
            path.write_bytes(path.read_bytes() + b" ")
    elif fault == "admission":
        p.receipt_path.write_bytes(p.receipt_path.read_bytes() + b" ")
    elif fault == "source":
        (ready.root / "src/dante_workflow/expanded_context_provider.py").write_text(
            "drift"
        )
    elif fault == "contract":
        ready.contract_path.write_text("{}")
    elif fault == "lock":
        (ready.run_dir / "controller.lock").write_text("active")
    else:
        kwargs = dict(detector="H1", start=110, end=114)
        original = p.prior.read

        def changed(**kw):
            context = original(**kw)
            if fault == "prior_values":
                context.series.value[0] += 1
            else:
                context.series.name = "OTHER"
            return context

        p.prior.read = changed
    with pytest.raises(ValueError):
        p.read(**kwargs)


def test_source_inventory_cannot_drop_required_reader(ready):
    ready.contract["source_paths"].pop()
    ready.kwargs["contract_sha"] = put(ready.contract_path, ready.contract)
    with pytest.raises(ValueError, match="inventory"):
        bind(ready)


def cli_args(c):
    return [
        "--repository-root",
        str(c.root),
        "--contract",
        str(c.contract_path),
        "--contract-sha256",
        c.kwargs["contract_sha"],
        "--run-dir",
        str(c.run_dir),
    ]


def test_cli_preflight_and_standalone_binding_replay_do_not_claim_full_read(ready):
    output = ready.run_dir.parent.parent / "consumer_binding" / "preflight.json"
    assert (
        consumer.main(
            ["--stage", "preflight", *cli_args(ready), "--output", str(output)]
        )
        == 0
    )
    before = output.read_bytes()
    value = admission.read_sealed(output)
    assert value["identity_count"] == 3
    assert value["all_expanded_contexts_read_through_consumer"] is False
    assert value["boundary"] == consumer.BOUNDARY
    assert (
        consumer.main(
            [
                "--stage",
                "verify",
                *cli_args(ready),
                "--expected",
                str(output),
                "--expected-sha256",
                admission._hash(output),
            ]
        )
        == 0
    )
    assert output.read_bytes() == before
    with pytest.raises(SystemExit):
        consumer.main(
            ["--stage", "preflight", *cli_args(ready), "--output", str(output)]
        )


def test_cli_cannot_write_inside_preserved_recovery(ready):
    with pytest.raises(SystemExit):
        consumer.main(
            [
                "--stage",
                "preflight",
                *cli_args(ready),
                "--output",
                str(ready.run_dir / "new.json"),
            ]
        )
    assert not (ready.run_dir / "new.json").exists()


def test_cli_resealed_wrong_expected_cannot_authorize_provider(ready):
    value = consumer.preflight(**ready.kwargs)
    value.pop("digest")
    value["unique_context_count"] += 1
    expected = ready.run_dir.parent / "fake.json"
    put(expected, admission.sealed(value))
    with pytest.raises(ValueError, match="independent replay"):
        consumer.main(
            [
                "--stage",
                "verify",
                *cli_args(ready),
                "--expected",
                str(expected),
                "--expected-sha256",
                admission._hash(expected),
            ]
        )
