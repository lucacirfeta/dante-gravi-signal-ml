"""Bounded provider wiring, exact grids and fail-closed numerical replay."""

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.dante_workflow import calibration_contexts as contexts
from src.dante_workflow import calibration_recovery as recovery
from src.dante_workflow.input_coverage import InputCoverageError
from tests.test_dante_workflow_calibration_admission import admitted_case, create  # noqa: F401
from tests.test_dante_workflow_calibration_recovery import case  # noqa: F401


@pytest.fixture
def provider(admitted_case):  # noqa: F811
    c = admitted_case
    create(c)
    return contexts.AdmittedContextProvider(
        None,
        None,
        root=c.root,
        receipt_path=c.output,
        receipt_sha=recovery._hash(c.output),
    )


def test_complete_context_and_exact_new_source(provider):
    from src.core.patch_producer import CompleteContext

    result = provider.read(detector="H1", start=103, end=118)
    assert isinstance(result, CompleteContext)
    assert result.series.value.tolist() == list(range(6, 36))
    source = result.sources[0]
    assert source.used_start == source.block_start == 103
    assert source.used_end == source.block_end == 118
    assert source.sha256 == provider.rows["H1", 103, 118]["file_sha256"]
    assert source.sha256 != "0" * 64


@pytest.mark.parametrize(
    "detector,start,end",
    [
        ("L1", 103, 118),
        ("V1", 103, 118),
        ("H1", 104, 118),
        ("H1", 103, 117),
        ("H1", True, 118),
        ("H1", "103", 118),
        ("H1", float("nan"), 118),
        ("H1", 103, float("inf")),
    ],
)
def test_no_detector_interval_or_type_fallback(provider, detector, start, end):
    with pytest.raises(InputCoverageError, match="exact admitted"):
        provider.read(detector=detector, start=start, end=end)


@pytest.mark.parametrize("target", ["receipt", "context"])
def test_drift_after_provider_init(provider, target):
    row = next(iter(provider.rows.values()))
    path = (
        provider.receipt_path
        if target == "receipt"
        else provider.directory / row["relative_path"]
    )
    path.write_bytes(b"changed")
    with pytest.raises(InputCoverageError):
        provider.read(detector="H1", start=103, end=118)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dtype", "<f4"),
        ("sample_rate_hz", 3),
        ("sample_count", 29),
        ("strain_values_sha256", "0" * 64),
        ("historical_strain_values_sha256", "0" * 64),
    ],
)
def test_read_rechecks_every_declared_grid_and_numeric_pin(provider, field, value):
    provider.rows["H1", 103, 118][field] = value
    with pytest.raises(InputCoverageError, match="numerical/grid"):
        provider.read(detector="H1", start=103, end=118)


@pytest.fixture
def replay_case(provider, monkeypatch):
    from src.core import utils

    # Synthetic geometry is deliberately separate from the production contract.
    rep = dict(
        sample_rate_hz=2,
        whitening_pad_s=2,
        analysis_duration_s=11,
        query_qrange=[4, 64],
        frequency_range_hz=[20, 2048],
        image_shape=[2, 2, 3],
        colormap="cividis",
    )
    parent = provider.root / provider.receipt["parent"]["path"]
    parent.write_text(json.dumps({"representation": rep}))
    provider.receipt["parent"]["sha256"] = recovery._hash(parent)
    pre = dict(
        qrange=[4, 64], frange=[20, 2048], output_size=[2, 2], colormap="cividis"
    )
    monkeypatch.setattr(utils, "load_config", lambda: {"preprocessing": pre})
    monkeypatch.setattr(contexts, "_sources", lambda root: {"synthetic": "unchanged"})
    calls = []

    def worker(raw, t0, dt, name, start, end, padded):
        calls.append((raw.copy(), t0, dt, start, end, padded))
        return start, np.full((2, 2, 3), 42, dtype=np.uint8)

    return SimpleNamespace(
        provider=provider, worker=worker, calls=calls, pre=pre, parent=parent
    )


def test_wiring_direct_samples_same_consumer_and_bounded_claim(replay_case):
    c = replay_case
    result = contexts.replay(c.provider, worker=c.worker)
    assert result["status"] == "PASS_ADMITTED_CONTEXT_PREPROCESSING_ONLY"
    assert result["record_count"] == 1
    assert len(c.calls) == 2
    assert np.array_equal(c.calls[0][0], c.calls[1][0])
    assert c.calls[0][1:] == c.calls[1][1:] == (103, 0.5, 105, 116, True)
    assert result["rows"][0]["analysis_start"] == 105
    for flag in (
        "scientific_execution_ready",
        "encoder_or_scorer_executed",
        "all_calibration_contexts_measured",
        "score_values_read",
        "verification_was_second_fetch",
    ):
        assert result[flag] is False


@pytest.mark.parametrize("fault", ["none", "gps", "shape", "dtype", "different"])
def test_consumer_failure_or_mismatch_refused(replay_case, fault):
    c = replay_case
    count = 0

    def worker(*args):
        nonlocal count
        count += 1
        gps, image = c.worker(*args)
        if fault == "none":
            image = None
        elif fault == "gps":
            gps += 1
        elif fault == "shape":
            image = image[:1]
        elif fault == "dtype":
            image = image.astype(float)
        elif count == 2:
            image[0, 0, 0] += 1
        return gps, image

    with pytest.raises(InputCoverageError, match="consumer|mismatch"):
        contexts.replay(c.provider, worker=worker)


@pytest.mark.parametrize(
    "field,value",
    [
        ("qrange", [4, 32]),
        ("frange", [20, 1000]),
        ("output_size", [3, 3]),
        ("colormap", "viridis"),
    ],
)
def test_parent_preprocessing_parity_required(replay_case, field, value):
    replay_case.pre[field] = value
    with pytest.raises(InputCoverageError, match="defaults differ"):
        contexts.replay(replay_case.provider, worker=replay_case.worker)
    assert replay_case.calls == []


def test_parent_hash_drift_refused(replay_case):
    replay_case.parent.write_text("changed")
    with pytest.raises(InputCoverageError):
        contexts.replay(replay_case.provider, worker=replay_case.worker)


def test_population_change_refused(replay_case):
    replay_case.provider.rows["L1", 103, 118] = deepcopy(
        next(iter(replay_case.provider.rows.values()))
    )
    with pytest.raises(InputCoverageError, match="population"):
        contexts.replay(replay_case.provider, worker=replay_case.worker)


def test_frame_change_refused(replay_case):
    next((replay_case.provider.directory / "frames").glob("*.hdf5")).write_bytes(
        b"changed"
    )
    with pytest.raises(InputCoverageError):
        contexts.replay(replay_case.provider, worker=replay_case.worker)


def test_executed_provider_must_match_declared_checkout(tmp_path):
    for relative in (
        "src/dante_workflow/calibration_contexts.py",
        "src/core/patch_producer.py",
        "src/core/preprocessor.py",
        "src/core/utils.py",
        "src/core/data_loader.py",
        "config.yaml",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("synthetic")
    with pytest.raises(InputCoverageError, match="executed provider"):
        contexts._sources(tmp_path)


def test_installed_flag_refuses_checkout_import(tmp_path):
    root = Path(contexts.__file__).resolve().parents[2]
    with pytest.raises(SystemExit) as exc:
        contexts.main(
            [
                "--repository-root",
                str(root),
                "--config",
                "unused",
                "--receipt",
                "unused",
                "--receipt-sha256",
                "0" * 64,
                "--output",
                str(tmp_path / "new.json"),
                "--require-installed",
            ]
        )
    assert exc.value.code == 2


@pytest.fixture
def cli_case(admitted_case, monkeypatch):  # noqa: F811
    from src.dante_workflow import adapters, schema

    c = admitted_case
    create(c)
    monkeypatch.setattr(schema, "load_workflow_spec", lambda *a, **k: None)
    monkeypatch.setattr(adapters, "build_adapter", lambda *a: None)
    result = recovery.sealed(
        {"status": "synthetic numerical result", "record_count": 1}
    )
    monkeypatch.setattr(contexts, "replay", lambda *a, **k: result)
    args = [
        "--repository-root",
        str(c.root),
        "--config",
        "unused",
        "--receipt",
        str(c.output),
        "--receipt-sha256",
        recovery._hash(c.output),
    ]
    return c, result, args


def test_cli_new_receipt_and_no_overwrite(cli_case, tmp_path, capsys):
    c, result, args = cli_case
    output = tmp_path / "numerical" / "new.json"
    assert contexts.main(args + ["--output", str(output)]) == 0
    assert recovery.read_sealed(output) == result
    assert json.loads(capsys.readouterr().out)["installed_replay"] is False
    with pytest.raises(SystemExit):
        contexts.main(args + ["--output", str(output)])
    for forbidden in (
        c.root / "new.json",
        c.run / "new.json",
        c.output.parent / "new.json",
    ):
        with pytest.raises(SystemExit):
            contexts.main(args + ["--output", str(forbidden)])
        assert not forbidden.exists()


def test_cli_independent_expected_mismatch_never_writes(cli_case, tmp_path):
    _, _, args = cli_case
    expected = tmp_path / "expected.json"
    recovery.write_json(expected, recovery.sealed({"wrong": True}))
    output = tmp_path / "new.json"
    with pytest.raises(InputCoverageError, match="differs from checkout"):
        contexts.main(
            args
            + [
                "--output",
                str(output),
                "--expected",
                str(expected),
                "--expected-sha256",
                recovery._hash(expected),
            ]
        )
    assert not output.exists()


def test_cli_expected_pin_required(cli_case, tmp_path):
    _, _, args = cli_case
    with pytest.raises(SystemExit):
        contexts.main(
            args + ["--output", str(tmp_path / "new.json"), "--expected", "missing"]
        )
