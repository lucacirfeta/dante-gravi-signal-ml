"""Real mixed-origin names: preserve prior bytes, never normalize or skip guards."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_workflow import expanded_context_provider as consumer
from src.dante_workflow import expanded_context_replay as replay
from src.dante_workflow.calibration_contexts import AdmittedContextProvider
from tests.test_dante_workflow_expanded_context_provider import (
    bind,
    prepare_ready,
    put,
    raw_case,  # noqa: F401 - shared input fixture
)


@pytest.fixture
def mixed(request, monkeypatch):
    from gwpy.timeseries import TimeSeries

    c = request.getfixturevalue("raw_case")
    c.prior.directory = c.args["prior_receipt"].parent
    c.prior.receipt_path = c.args["prior_receipt"]
    c.prior.receipt_sha = replay._hash(c.prior.receipt_path)
    path = c.prior.directory / "prior.hdf5"
    values = np.arange(50, 66, dtype=np.float64)
    TimeSeries(values, t0=110, sample_rate=4, name="H1:STRAIN").write(
        path, format="hdf5"
    )
    sha = hashlib.sha256(values.tobytes()).hexdigest()
    c.prior.rows["H1", 110, 114] = dict(
        file_sha256=replay._hash(path),
        relative_path=path.name,
        sample_count=len(values),
        sample_rate_hz=4,
        dtype=values.dtype.str,
        strain_values_sha256=sha,
        historical_strain_values_sha256=sha,
    )
    c.prior.read = lambda **kw: AdmittedContextProvider.read(c.prior, **kw)
    c = prepare_ready(c, monkeypatch, version=2)
    c.prior_path = path
    return c


def test_mixed_names_retained_numeric_parity_and_sealed_binding(mixed):
    before = mixed.prior_path.read_bytes()
    p = bind(mixed)
    old = p.read(detector="H1", start=110, end=114)
    new = p.read(detector="H1", start=100.25, end=104.25)
    assert old.series.name == "H1:STRAIN"
    assert new.series.name == "H1:GWOSC-16KHZ_R1_STRAIN"
    np.testing.assert_array_equal(old.series.value, np.arange(50, 66))
    np.testing.assert_array_equal(new.series.value, np.arange(1, 17))
    report = consumer.preflight(**mixed.kwargs)
    assert report["prior_series_names"] == [
        {"key": ["H1", 110, 114], "name": "H1:STRAIN"}
    ]
    assert report["series_name_rule"] == consumer.NAME_RULE
    assert mixed.prior_path.read_bytes() == before


@pytest.mark.parametrize("name", ["OTHER", "L1:STRAIN", "H1:GWOSC-16KHZ_R1_STRAIN"])
def test_prior_in_memory_name_drift_or_normalization_rejected(mixed, name):
    p = bind(mixed)
    original = p.prior.read

    def renamed(**kw):
        result = original(**kw)
        result.series.name = name
        return result

    p.prior.read = renamed
    with pytest.raises(ValueError, match="native/name"):
        p.read(detector="H1", start=110, end=114)


@pytest.mark.parametrize("fault", ["name", "values"])
def test_prior_container_drift_rejected_by_existing_file_pin(mixed, fault):
    p = bind(mixed)
    with h5py.File(mixed.prior_path, "r+") as h:
        ds = next(iter(h.values()))
        if fault == "name":
            ds.attrs["name"] = "H1:RENAMED"
        else:
            ds[0] += 1
    with pytest.raises(ValueError, match="pin"):
        p.read(detector="H1", start=110, end=114)


@pytest.mark.parametrize("detector", ["H1", "L1"])
def test_prior_metadata_binds_detector_specific_name(mixed, tmp_path, detector):
    from gwpy.timeseries import TimeSeries

    path = tmp_path / f"{detector}.hdf5"
    TimeSeries(np.arange(4), t0=0, sample_rate=1, name=f"{detector}:STRAIN").write(
        path, format="hdf5"
    )
    prior = deepcopy(mixed.prior)
    prior.directory = tmp_path
    key = detector, 0, 4
    prior.rows = {key: {"relative_path": path.name, "file_sha256": replay._hash(path)}}
    assert consumer.prior_name(prior, key) == detector + ":STRAIN"
    other = "L1" if detector == "H1" else "H1"
    prior.rows[other, 0, 4] = prior.rows[key]
    with pytest.raises(ValueError, match="detector"):
        consumer.prior_name(prior, (other, 0, 4))


def test_v1_keeps_old_rule_and_does_not_reinterpret_history(mixed):
    mixed.contract["schema_version"] = 1
    mixed.contract["status"] = "OPT_IN_EXPANDED_CALIBRATION_CONTEXT_CONSUMER_V1"
    mixed.contract.pop("series_name_rule")
    mixed.kwargs["contract_sha"] = put(mixed.contract_path, mixed.contract)
    with pytest.raises(ValueError, match="native/name"):
        bind(mixed).read(detector="H1", start=110, end=114)
    assert "prior_series_names" not in consumer.preflight(**mixed.kwargs)


def test_v2_rule_cannot_accept_arbitrary_names(mixed):
    mixed.contract["series_name_rule"] = "any name"
    mixed.kwargs["contract_sha"] = put(mixed.contract_path, mixed.contract)
    with pytest.raises(ValueError, match="authority"):
        bind(mixed)


@pytest.mark.parametrize("fault", ["missing", "empty", "ambiguous"])
def test_prior_name_binding_rejects_incomplete_metadata(mixed, fault):
    with h5py.File(mixed.prior_path, "r+") as h:
        ds = next(iter(h.values()))
        if fault == "missing":
            del ds.attrs["name"]
        elif fault == "empty":
            ds.attrs["name"] = "H1:"
        else:
            h.create_dataset("extra", data=[0])
    mixed.prior.rows["H1", 110, 114]["file_sha256"] = replay._hash(mixed.prior_path)
    with pytest.raises(ValueError, match="prior name"):
        consumer.prior_name(mixed.prior, ("H1", 110, 114))


def test_new_context_name_guard_is_not_weakened(mixed, monkeypatch):
    p = bind(mixed)
    original = AdmittedContextProvider.read

    def wrong_name(owner, **kw):
        context = original(owner, **kw)
        context.series.name = "H1:STRAIN"
        return context

    monkeypatch.setattr(AdmittedContextProvider, "read", wrong_name)
    with pytest.raises(ValueError, match="native/name"):
        p.read(detector="H1", start=100.25, end=104.25)


def test_full_mixed_run_and_independent_replay(mixed, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "config/dante_workflow_expanded_context_replay_v2.json").read_text()
    )
    contract["consumer_contract"] = {
        "path": mixed.contract_path.relative_to(mixed.root).as_posix(),
        "sha256": mixed.kwargs["contract_sha"],
    }
    path = mixed.root / "replay.json"
    put(path, contract)
    parent = mixed.run_dir.parent / "binding_v2.json"
    replay.write_json(parent, consumer.preflight(**mixed.kwargs))
    monkeypatch.setattr(replay, "source_audit", lambda *a: {"test": "pin"})
    kwargs = dict(
        root=mixed.root,
        contract_path=path,
        contract_sha=replay._hash(path),
        recovery_dir=mixed.run_dir,
        binding_path=parent,
        binding_sha=replay._hash(parent),
        freeze="a" * 40,
    )
    run_dir = mixed.root.parent / "fresh_replay_v2"
    result = replay.execute(stage="run", run_dir=run_dir, binding_kwargs=kwargs)
    assert result["record_count"] == 2
    p = bind(mixed)
    with pytest.raises(ValueError, match="differs"):
        p.expected_names["H1", 110, 114] = "H1:OTHER"
        replay.independent_values(p, ("H1", 110, 114))
    monkeypatch.setattr(
        consumer.ExpandedCalibrationContextProvider,
        "read",
        lambda *a, **kw: pytest.fail("independent verifier must not call consumer"),
    )
    result = replay.execute(
        stage="verify",
        run_dir=run_dir,
        binding_kwargs=kwargs,
        summary_sha=replay._hash(run_dir / "summary.json"),
    )
    assert result["status"] == "PASS_VERIFIED_EXPANDED_NATIVE_CONSUMER_ONLY"
    assert result["record_count"] == 2
