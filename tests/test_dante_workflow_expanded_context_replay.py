"""Full consumer traversal and independent native HDF5 replay, no score data."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from src.dante_workflow import expanded_context_replay as replay
from src.dante_workflow.calibration_contexts import AdmittedContextProvider
from src.dante_workflow.calibration_recovery import read_sealed, sealed, write_json
from tests.test_dante_workflow_expanded_context_provider import (
    raw_case,  # noqa: F401 - shared synthetic fixture
    ready,  # noqa: F401, F811 - shared complete parent evidence fixture
)

BIND = replay.bind


@pytest.fixture
def case(tmp_path, monkeypatch):
    from gwpy.timeseries import TimeSeries

    root = tmp_path / "checkout"
    recovery = tmp_path / "recovery"
    prior_dir = tmp_path / "prior"
    for directory in (root, recovery, prior_dir):
        directory.mkdir()
    prior = SimpleNamespace(
        directory=prior_dir, rows={}, receipt_path=prior_dir / "admission.json"
    )
    prior.receipt_path.write_text("old")
    prior.receipt_sha = replay._hash(prior.receipt_path)
    provider = SimpleNamespace(
        root=root,
        directory=recovery,
        rows={},
        prior=prior,
        planned={},
        identity_count=3,
        identity_counts={"H1": 2, "L1": 1},
    )
    provider.receipt_path = recovery / "admission.json"
    provider.receipt_path.write_text("new")
    provider.receipt_sha = replay._hash(provider.receipt_path)
    for detector, start, origin in (("H1", 100.25, provider), ("L1", 110, prior)):
        values = np.arange(16, dtype=np.float64)
        key = detector, start, start + 4
        path = origin.directory / f"{detector}.hdf5"
        TimeSeries(values, t0=start, sample_rate=4, name=detector).write(
            path, format="hdf5"
        )
        sha = hashlib.sha256(values.tobytes()).hexdigest()
        row = dict(
            detector=detector,
            gps_start=start,
            gps_end=start + 4,
            sample_rate_hz=4,
            sample_count=16,
            dtype=values.dtype.str,
            relative_path=path.name,
            file_sha256=replay._hash(path),
            strain_values_sha256=sha,
            historical_strain_values_sha256=sha,
        )
        origin.rows[key] = row
        provider.planned[key] = row
    provider.allowed = frozenset(provider.planned)
    read_calls = []

    def consumer_read(**kwargs):
        key = kwargs["detector"], kwargs["start"], kwargs["end"]
        read_calls.append(key)
        owner = provider if key in provider.rows else prior
        return AdmittedContextProvider.read(owner, **kwargs)

    provider.read = consumer_read
    binding = sealed(
        dict(
            identity_count=3,
            unique_context_count=2,
            boundary=replay.BOUNDARY,
            source_hashes={"test": "pin"},
        )
    )
    monkeypatch.setattr(replay, "bind", lambda **kw: (provider, binding))
    write_json(
        recovery / "plan.json",
        sealed(
            dict(
                historical_directory=str(tmp_path / "history"),
                metadata_directory=str(tmp_path / "metadata"),
            )
        ),
    )
    return SimpleNamespace(
        provider=provider,
        binding=binding,
        root=root,
        run_dir=tmp_path / "replay",
        calls=read_calls,
        args=dict(binding_kwargs={}),
    )


def run(c):
    return replay.execute(stage="run", run_dir=c.run_dir, **c.args)


def verify(c):
    return replay.execute(
        stage="verify",
        run_dir=c.run_dir,
        summary_sha=replay._hash(c.run_dir / "summary.json"),
        **c.args,
    )


def test_all_native_contexts_and_identity_multiplicity(case, monkeypatch):
    result = run(case)
    assert case.calls == sorted(case.provider.allowed)
    assert result["binding"]["identity_count"] == 3
    assert result["record_count"] == 2
    assert result["all_expanded_contexts_read_through_consumer"] is True
    assert result["boundary"] == replay.BOUNDARY
    monkeypatch.setattr(case.provider, "read", lambda **kw: pytest.fail("read path"))
    checked = verify(case)
    assert checked["status"] == "PASS_VERIFIED_EXPANDED_NATIVE_CONSUMER_ONLY"
    assert checked["verification_was_second_fetch"] is False
    assert not (case.run_dir / "controller.lock").exists()
    with pytest.raises(ValueError, match="already exists"):
        verify(case)


@pytest.mark.parametrize("fault", ["extra", "missing", "receipt", "summary"])
def test_independent_verifier_rejects_changed_replay(case, fault):
    run(case)
    files = sorted((case.run_dir / "contexts").iterdir())
    if fault == "extra":
        (case.run_dir / "contexts/extra.json").write_text("preserve")
    elif fault == "missing":
        files[0].unlink()
    elif fault == "receipt":
        value = read_sealed(files[0])
        value.pop("digest")
        value["sample_count"] += 1
        write_json(files[0], sealed(value))
    else:
        value = read_sealed(case.run_dir / "summary.json")
        value.pop("digest")
        value["record_count"] += 1
        write_json(case.run_dir / "summary.json", sealed(value))
    with pytest.raises((ValueError, FileNotFoundError)):
        verify(case)
    assert (case.run_dir / "failure.json").is_file()
    assert not (case.run_dir / "verification.json").exists()
    with pytest.raises(ValueError, match="failed"):
        verify(case)


@pytest.mark.parametrize("fault", ["bytes", "nonfinite", "start", "spacing", "extra"])
def test_direct_reader_checks_container_grid_and_values(case, fault):
    key = sorted(case.provider.allowed)[0]
    row = case.provider.rows[key]
    path = case.provider.directory / row["relative_path"]
    with h5py.File(path, "r+") as h:
        ds = h["H1"]
        if fault == "bytes":
            ds[0] += 1
        elif fault == "nonfinite":
            ds[0] = np.nan
        elif fault == "start":
            ds.attrs["x0"] += 0.25
        elif fault == "spacing":
            ds.attrs["dx"] *= 2
        else:
            h.create_dataset("other", data=[0])
    # A re-pinned changed container must still fail native/grid/ambiguity checks.
    row["file_sha256"] = replay._hash(path)
    with pytest.raises(ValueError, match="native|grid|ambiguous"):
        replay.record(case.provider, key, replay.independent_values(case.provider, key))


def test_mutated_consumer_native_values_preserve_failure(case):
    original = case.provider.read

    def mutated(**kwargs):
        context = original(**kwargs)
        context.series.value[0] += 1
        return context

    case.provider.read = mutated
    with pytest.raises(ValueError, match="native"):
        run(case)
    assert (case.run_dir / "failure.json").exists()
    assert not (case.run_dir / "summary.json").exists()
    assert not (case.run_dir / "controller.lock").exists()
    with pytest.raises(FileExistsError):
        run(case)


@pytest.mark.parametrize(
    "fault", ["controller.lock", "failure.json", "x.partial", "x.tmp"]
)
def test_existing_failed_or_active_run_is_not_restarted(case, fault):
    run(case)
    (case.run_dir / fault).write_text("preserve")
    with pytest.raises(ValueError, match="incomplete"):
        verify(case)
    assert (case.run_dir / fault).read_text() == "preserve"


@pytest.mark.parametrize("location", ["root", "directory", "prior", "ancestor"])
def test_output_cannot_touch_any_protected_parent(case, location):
    p = case.provider
    target = {
        "root": p.root / "new",
        "directory": p.directory / "new",
        "prior": p.prior.directory / "new",
        "ancestor": p.root.parent,
    }[location]
    with pytest.raises(ValueError, match="separate external"):
        replay.isolated(target, p)


def test_parent_change_during_run_refused(case, monkeypatch):
    count = 0

    def changing(**kwargs):
        nonlocal count
        count += 1
        binding = deepcopy(case.binding)
        if count > 1:
            binding["identity_count"] += 1
        return case.provider, binding

    monkeypatch.setattr(replay, "bind", changing)
    with pytest.raises(ValueError, match="changed during"):
        run(case)
    assert (case.run_dir / "failure.json").exists()


@pytest.mark.parametrize("argv", [[], ["--stage", "other"]])
def test_cli_requires_explicit_stage_and_pins(argv):
    with pytest.raises(SystemExit):
        replay.main(argv)


def test_source_freeze_requires_full_hash(case):
    with pytest.raises(ValueError, match="full source freeze"):
        replay.source_audit(case.root, "HEAD")


def test_source_audit_checks_git_bytes(case, monkeypatch):
    for name in replay.SOURCES:
        path = case.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(Path(replay.__file__).read_bytes())
    raw = Path(replay.__file__).read_bytes()
    monkeypatch.setattr(
        replay.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=raw)
    )
    assert len(replay.source_audit(case.root, "a" * 40)) == len(replay.SOURCES)
    (case.root / replay.SOURCES[-1]).write_bytes(raw + b" ")
    with pytest.raises(ValueError, match="pin"):
        replay.source_audit(case.root, "a" * 40)


@pytest.mark.parametrize(
    "fault", ["schema", "status", "rule", "resume", "sources", "boundary"]
)
def test_replay_contract_cannot_change_validation_authority(case, fault):
    contract = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "config/dante_workflow_expanded_context_replay_v1.json"
        ).read_text()
    )
    if fault == "schema":
        contract["schema_version"] = True
    elif fault == "status":
        contract["status"] = "PASS"
    elif fault == "rule":
        contract["replay_rule"] = "sample subset"
    elif fault == "resume":
        contract["automatic_resume"] = True
    elif fault == "sources":
        contract["source_paths"].pop()
    else:
        contract["boundary"]["o4b_launch_allowed"] = True
    path = case.root / "contract.json"
    path.write_text(json.dumps(contract))
    with pytest.raises(ValueError, match="authority"):
        BIND(
            root=case.root,
            contract_path=path,
            contract_sha=replay._hash(path),
            recovery_dir=case.provider.directory,
            binding_path=path,
            binding_sha=replay._hash(path),
            freeze="a" * 40,
        )


def test_actual_parent_binding_and_resealed_drift(request, monkeypatch):
    from src.dante_workflow.expanded_context_provider import preflight

    c = request.getfixturevalue("ready")

    contract = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "config/dante_workflow_expanded_context_replay_v1.json"
        ).read_text()
    )
    contract["consumer_contract"] = {
        "path": c.contract_path.relative_to(c.root).as_posix(),
        "sha256": c.kwargs["contract_sha"],
    }
    path = c.root / "replay_contract.json"
    path.write_text(json.dumps(contract))
    parent = c.root.parent / "binding.json"
    write_json(parent, preflight(**c.kwargs))
    monkeypatch.setattr(replay, "source_audit", lambda *a: {"test": "pin"})
    kwargs = dict(
        root=c.root,
        contract_path=path,
        contract_sha=replay._hash(path),
        recovery_dir=c.run_dir,
        binding_path=parent,
        binding_sha=replay._hash(parent),
        freeze="a" * 40,
    )
    provider, report = BIND(**kwargs)
    assert provider.identity_count == report["identity_count"] == 3
    assert report["unique_context_count"] == 2
    value = read_sealed(parent)
    value.pop("digest")
    value["identity_count"] += 1
    write_json(parent, sealed(value))
    kwargs["binding_sha"] = replay._hash(parent)
    with pytest.raises(ValueError, match="binding differs"):
        BIND(**kwargs)
