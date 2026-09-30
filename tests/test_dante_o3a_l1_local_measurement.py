"""Synthetic Gate C tests: never inspect the real local event/null outcomes."""

import copy

import h5py
import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from scripts import run_dante_o3a_l1_local_measurement as runner
from src.dante_light.contracts import ContractError
from src.dante_light.o3a_l1_local_followup import local_coherence_max, load_design
from src.dante_light.o3a_l1_local_measurement import (
    NativeContextReader,
    UnavailableContext,
    block_record,
    decision_and_bootstrap,
    half_open_indices,
    independent_coherence,
    measure_context,
    preprocess_context,
)
from src.dante_light.o3a_o4a_common_pem_acquisition import _atomic_json, sealed_json
from src.dante_light.o3a_o4a_common_pem_aux_samples import data_path


@pytest.fixture
def design():
    return load_design()


def test_contract_records_parity_sources_and_immutable_method():
    config = runner.load_config()
    assert "NOT an optimization" in config["preprocessing"]["reason"]
    assert len(config["preprocessing"]["historical_sources"]) == 4
    assert (
        config["method"]["sha256"]
        == "2625867ba9eb904fe99c7185ffd1c2fc059632172dcdb8bd0bcf6b7e3be3b241"
    )
    assert not config["preprocessing"]["auxiliary_highpass"]
    assert not config["execution"]["download_allowed"]


@pytest.mark.parametrize(
    "fault", ["order", "auxiliary", "crop", "method", "claim", "resume"]
)
def test_execution_contract_tampering_rejected(tmp_path, monkeypatch, fault):
    config = runner.load_config()
    if fault == "order":
        config["preprocessing"]["order"] = "CROP_FIRST"
    elif fault == "auxiliary":
        config["preprocessing"]["auxiliary_highpass"] = True
    elif fault == "crop":
        config["sampling"]["library_crop_rounding_allowed"] = True
    elif fault == "method":
        config["method"]["sha256"] = "bad"
    elif fault == "claim":
        config["scientific_boundary"]["formal_p_value_or_fwer"] = True
    else:
        config["execution"]["automatic_resume_allowed"] = True
    _atomic_json(tmp_path / runner.CONFIG_PATH, config)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    with pytest.raises((ContractError, FileNotFoundError)):
        runner.load_config()


@pytest.mark.parametrize(
    "interval,expected",
    [
        ([0, 1], (0, 512)),
        ([16.364864864864863, 17.364864864864863], (8379, 8891)),
        ([17.66216216216216, 18.66216216216216], (9044, 9556)),
        ([1 / 512, 2 / 512], (1, 2)),
        ([0.1, 0.2], (52, 103)),
    ],
)
def test_exact_relative_half_open_timestamps(interval, expected):
    first, last = half_open_indices(interval, 512, 32 * 512)
    assert (first, last) == expected
    assert first / 512 >= interval[0] and (last - 1) / 512 < interval[1]
    if first:
        assert (first - 1) / 512 < interval[0]
    assert last / 512 >= interval[1]


@pytest.mark.parametrize(
    "interval", [[-1, 1], [2, 1], [0, 0], [0, 33], [0, float("nan")]]
)
def test_boundary_invalid_fails_closed(interval):
    with pytest.raises(ContractError):
        half_open_indices(interval, 512, 32 * 512)


def synthetic_native():
    rng = np.random.default_rng(91)
    strain = rng.normal(size=32 * 4096)
    aux = {
        "L1:A": rng.normal(size=32 * 2048).astype("float32"),
        "L1:B": rng.normal(size=32 * 512).astype("float32"),
    }
    args = {
        "strain_rate": 4096,
        "auxiliary_rates": {"L1:A": 2048, "L1:B": 512},
        "channels": list(aux),
        "duration": 32,
        "target_rate": 512,
        "highpass_hz": 20,
        "interval": [16.333, 17.333],
    }
    return strain, aux, args


def test_preprocessing_matches_historical_api_order_not_crop_first():
    strain, aux, args = synthetic_native()
    before = (strain.copy(), {n: a.copy() for n, a in aux.items()})
    x, y, provenance = preprocess_context(strain, aux, **args)
    first, last = half_open_indices(args["interval"], 512, 32 * 512)
    expected_x = (
        TimeSeries(strain, sample_rate=4096, t0=0)
        .highpass(20)
        .resample(512)
        .value[first:last]
    )
    expected_y = (
        TimeSeries(aux["L1:A"], sample_rate=2048, t0=0).resample(512).value[first:last]
    )
    np.testing.assert_array_equal(x, expected_x)
    np.testing.assert_array_equal(y["L1:A"], expected_y)
    np.testing.assert_array_equal(y["L1:B"], aux["L1:B"][first:last])
    np.testing.assert_array_equal(strain, before[0])
    for n in aux:
        np.testing.assert_array_equal(aux[n], before[1][n])
    assert provenance["half_open_sample_indices"] == [first, last]
    crop_first = (
        TimeSeries(strain[16 * 4096 : 17 * 4096], sample_rate=4096)
        .highpass(20)
        .resample(512)
        .value
    )
    assert not np.array_equal(x, crop_first)


def test_resampler_rejects_alias_and_auxiliary_low_band_not_highpassed():
    t = np.arange(32 * 4096) / 4096
    a = np.arange(32 * 2048) / 2048
    # 400 Hz would alias to 112 Hz if naively decimated to 512 Hz.
    strain = np.sin(2 * np.pi * 40 * t) + np.sin(2 * np.pi * 400 * t)
    aux = {
        "L1:A": (np.sin(2 * np.pi * 5 * a) + np.sin(2 * np.pi * 400 * a)).astype(
            "float32"
        )
    }
    x, y, _ = preprocess_context(
        strain,
        aux,
        strain_rate=4096,
        auxiliary_rates={"L1:A": 2048},
        channels=list(aux),
        duration=32,
        target_rate=512,
        highpass_hz=20,
        interval=[16, 18],
    )
    f = np.fft.rfftfreq(x.size, 1 / 512)
    sx, sy = np.abs(np.fft.rfft(x)), np.abs(np.fft.rfft(y["L1:A"]))
    assert sx[f == 112][0] < sx[f == 40][0] / 100
    assert sy[f == 112][0] < sy[f == 5][0] / 100
    assert sy[f == 5][0] > 100


@pytest.mark.parametrize("fault", ["constant", "nonfinite", "shape", "channel"])
def test_unavailable_never_negative_geometry_never_silently_fixed(fault):
    strain, aux, args = synthetic_native()
    if fault == "constant":
        aux["L1:A"][:] = 1
    elif fault == "nonfinite":
        aux["L1:A"][0] = np.nan
    elif fault == "shape":
        strain = strain[:-1]
    else:
        aux["H1:A"] = aux.pop("L1:A")
    with pytest.raises(UnavailableContext if fault == "constant" else ContractError):
        preprocess_context(strain, aux, **args)


@pytest.mark.parametrize("coupled", [False, True])
def test_direct_fft_independent_of_scipy_coherence(design, coupled):
    rng = np.random.default_rng(8)
    x = rng.normal(size=512)
    aux = {
        "L1:A": (x + rng.normal(scale=0.1, size=512))
        if coupled
        else rng.normal(size=512),
        "L1:B": rng.normal(size=512),
    }
    kwargs = {
        "channels": list(aux),
        "band": [20, 58.968209801245216],
        "measurement": design["measurement"],
    }
    expected = local_coherence_max(x, aux, **kwargs)
    measured = independent_coherence(x, aux, **kwargs)
    assert measured["maximum"] == pytest.approx(expected, abs=1e-12)
    assert measured["welch_segments"] == 7
    assert measured["frequency_bins_hz"] == list(range(20, 57, 4))


def contexts(values, starts=(0, 32, 64)):
    return [
        {
            "gps_start": s,
            "duration_s": 32,
            "role": "background",
            "status": "MEASURED",
            "value": v,
        }
        for s, v in zip(starts, values, strict=True)
    ]


def test_whole_paired_block_no_stitching_or_context_bootstrap(design):
    cs = contexts([0.2, 0.8, 0.4])
    assert block_record(cs, [0, 32, 64], design)["value"] == 0.8
    cs[1] = {**cs[1], "status": "UNAVAILABLE", "reason": "CONSTANT"}
    assert (
        block_record(cs, [0, 32, 64], design)["status"] == "EXCLUDED_INCOMPLETE_BLOCK"
    )
    with pytest.raises(ContractError):
        block_record(contexts([0.2, 0.3, 0.4], (0, 32, 96)), [0, 32, 96], design)


def test_numeric_cutoff_equality_ties_two_target_family_and_bootstrap(design):
    event = {"status": "MEASURED", "value": 0.8}
    blocks = [{"status": "MEASURED", "value": 0.2} for _ in range(199)]
    result = decision_and_bootstrap(event, blocks, design, independent=False)
    assert result["corrected_reference_tail_fraction"] == 0.01
    assert result["status"] == design["decision"]["screen_positive"]
    assert result["bootstrap_exceedance_counts"] == [0] * 2000
    blocks[0]["value"] = event["value"]
    result = decision_and_bootstrap(event, blocks, design, independent=False)
    assert result["corrected_reference_tail_fraction"] == 0.02
    assert result["status"] == design["decision"]["screen_negative"]
    assert result == decision_and_bootstrap(event, blocks, design, independent=True)
    assert result["bootstrap_unit"] == "WHOLE_96S_MULTICHANNEL_CONTROL_BLOCKS"
    assert len(set(result["bootstrap_exceedance_counts"])) > 1
    assert (
        decision_and_bootstrap(event, blocks[:-1], design, independent=False)["status"]
        == "INCONCLUSIVE"
    )
    assert (
        decision_and_bootstrap(
            {"status": "UNAVAILABLE"}, blocks, design, independent=True
        )["status"]
        == "INCONCLUSIVE"
    )


def test_native_reader_exact_context_not_container_filtering(tmp_path):
    root = tmp_path
    frame_path = root / "frame_acquisition" / "frames" / "frame.hdf5"
    frame_path.parent.mkdir(parents=True)
    strain = np.arange(96 * 4, dtype="float64")
    with h5py.File(frame_path, "w") as handle:
        dataset = handle.create_dataset("strain/Strain", data=strain)
        dataset.attrs["Xstart"], dataset.attrs["Xspacing"] = 100, 0.25
    spec = {
        "channel": "L1:A",
        "detector": "L1",
        "run": "O3a",
        "interval_gps": [100, 196],
        "sample_rate_hz": 2,
        "sample_count": 192,
        "key": "synthetic",
    }
    path = data_path(root / "auxiliary", spec)
    path.parent.mkdir(parents=True)
    np.save(path, np.arange(192, dtype="float32"))
    plan = {
        "spans": [{"role": "background", "detector": "L1", "interval_gps": [100, 196]}],
        "frames": [{"gps_start": 100, "filename": "frame.hdf5"}],
        "strain_source": {"sample_rate_hz": 4, "frame_duration_s": 96},
        "auxiliary_series": [spec],
    }
    reader = NativeContextReader(root, plan, ["L1:A"])
    x, aux, rate, rates = reader.read(132, 32, "background")
    np.testing.assert_array_equal(x, strain[128:256])
    np.testing.assert_array_equal(aux["L1:A"], np.arange(64, 128, dtype="float32"))
    assert rate == 4 and rates == {"L1:A": 2}
    with pytest.raises(ContractError):
        reader.read(180, 32, "background")


@pytest.fixture
def synthetic_run(tmp_path, monkeypatch, design):
    # Small synthetic-only reference population. Production Gate B file is never edited.
    design = copy.deepcopy(design)
    design["controls"]["minimum_reference_blocks"] = 1
    design["controls"]["bootstrap_resamples"] = 7

    class Reader:
        def __init__(self, *args):
            pass

        def read(self, start, duration, role):
            rng = np.random.default_rng(start)
            return (
                rng.normal(size=duration * 1024),
                {"L1:A": rng.normal(size=duration * 512)},
                1024,
                {"L1:A": 512},
            )

    plan = runner.seal(
        {
            "status": "FROZEN_LOCAL_MEASUREMENT_PLAN_NO_OUTCOMES",
            "execution_contract": runner.load_config(),
            "method": design,
            "input_root": str(tmp_path / "parent"),
            "channels": ["L1:A"],
            "strain_highpass_hz": 20,
            "target_region": {
                "gps_start": 1000,
                "local_offset_interval_s": [16.333, 17.333],
                "frequency_band_hz": [20, 60],
            },
            "source_freeze": {"commit": "synthetic"},
            "target_accounting": [
                {
                    "detector": "L1",
                    "gps_start": 1,
                    "status": "INCONCLUSIVE",
                    "reason": "REFERENCE_TAIL_UNRESOLVED",
                },
                {"detector": "L1", "gps_start": 1000, "identity_digest": "synthetic"},
            ],
            "blocks": [
                {"eligible": True, "context_starts_gps": [0, 32, 64]},
                {"eligible": False, "context_starts_gps": [96, 128, 160]},
            ],
        }
    )
    _atomic_json(
        tmp_path / "parent" / "plan.json", runner.seal({"status": "synthetic"})
    )
    plan["execution_contract"]["output_root"] = str(tmp_path / "run")
    plan.pop("receipt_digest")
    plan = runner.seal(plan)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "build_plan", lambda commit: plan)
    monkeypatch.setattr(runner, "NativeContextReader", Reader)
    path = tmp_path / "run" / f"local_{plan['receipt_digest']}"
    assert runner.main("plan", None, "synthetic") == 0
    return path, plan


def test_end_to_end_exact_and_independent_replay_with_family_preserved(synthetic_run):
    path, plan = synthetic_run
    assert runner.main("run", str(path), "synthetic") == 0
    assert runner.main("verify", str(path), "synthetic") == 0
    summary = sealed_json(path / "summary.json")
    assert len(summary["targets"]) == 2
    assert summary["targets"][0]["status"] == "INCONCLUSIVE"
    assert summary["context_count"] == 3 and summary["block_receipt_count"] == 1
    assert len(summary["metadata_excluded_blocks"]) == 1
    assert sealed_json(path / "verification.json")["independent_fft_replay"]
    with pytest.raises(ContractError, match="already terminal"):
        runner.main("run", str(path), "synthetic")


@pytest.mark.parametrize(
    "fault", ["event", "block", "summary", "orphan", "partial", "lock", "key"]
)
def test_standalone_verifier_rejects_tampered_or_incomplete_outputs(
    synthetic_run, fault
):
    path, _ = synthetic_run
    runner.main("run", str(path), "synthetic")
    if fault in {"event", "block", "summary"}:
        name = {
            "event": "event.json",
            "block": "blocks/0.json",
            "summary": "summary.json",
        }[fault]
        value = sealed_json(path / name)
        value.pop("receipt_digest")
        value["tampered"] = True
        _atomic_json(path / name, runner.seal(value))
    elif fault == "orphan":
        _atomic_json(path / "blocks" / "orphan.json", runner.seal({"orphan": True}))
    elif fault == "partial":
        (path / "failed.partial").write_bytes(b"partial")
    elif fault == "lock":
        (path / "controller.lock").write_text("active")
    else:
        path = path.parent / "wrong"
    with pytest.raises(ContractError):
        runner.main("verify", str(path), "synthetic")


def test_independent_spectral_mismatch_caught(synthetic_run, monkeypatch):
    from src.dante_light import o3a_l1_local_measurement as module

    path, _ = synthetic_run
    runner.main("run", str(path), "synthetic")
    monkeypatch.setattr(
        module, "independent_coherence", lambda *a, **k: {"maximum": 0.0}
    )
    with pytest.raises(ContractError, match="independent FFT"):
        runner.main("verify", str(path), "synthetic")


def test_verifier_rereads_inputs_not_only_saved_outcomes(synthetic_run, monkeypatch):
    path, _ = synthetic_run
    runner.main("run", str(path), "synthetic")
    original = runner.NativeContextReader.read

    def changed(self, *args):
        strain, auxiliary, rate, rates = original(self, *args)
        strain[0] += 1
        return strain, auxiliary, rate, rates

    monkeypatch.setattr(runner.NativeContextReader, "read", changed)
    with pytest.raises(ContractError, match="event exact replay"):
        runner.main("verify", str(path), "synthetic")


def test_missing_context_excludes_entire_block_and_is_inconclusive(
    synthetic_run, monkeypatch
):
    path, _ = synthetic_run
    original = runner.NativeContextReader.read

    def unavailable(self, start, *args):
        strain, auxiliary, rate, rates = original(self, start, *args)
        if start == 32:
            auxiliary["L1:A"][:] = 1
        return strain, auxiliary, rate, rates

    monkeypatch.setattr(runner.NativeContextReader, "read", unavailable)
    runner.main("run", str(path), "synthetic")
    runner.main("verify", str(path), "synthetic")
    target = sealed_json(path / "summary.json")["targets"][1]
    assert target["excluded_unavailable_blocks"] == 1
    assert target["status"] == "INCONCLUSIVE"
    assert "bootstrap_exceedance_counts" not in target


def test_runtime_receipt_pins_numeric_implementations():
    value = runner.runtime_receipt(runner.load_config())
    assert value["versions"] == runner.load_config()["runtime_versions"]
    assert len(value["implementation_sha256"]) == 5
    assert all(len(v) == 64 for v in value["implementation_sha256"].values())


def test_failure_preserved_no_resume(synthetic_run, monkeypatch):
    path, _ = synthetic_run

    def fail(*args, **kwargs):
        raise ContractError("synthetic source mismatch")

    monkeypatch.setattr(runner, "run_measurement", fail)
    with pytest.raises(ContractError):
        runner.main("run", str(path), "synthetic")
    before = (path / "failure.json").read_bytes()
    assert not (path / "controller.lock").exists()
    with pytest.raises(ContractError, match="no automatic resume"):
        runner.main("run", str(path), "synthetic")
    assert (path / "failure.json").read_bytes() == before


def test_event_and_control_use_same_full_context_preprocessing(monkeypatch, design):
    strain, aux, args = synthetic_native()

    class Reader:
        def read(self, *arguments):
            return strain, aux, args["strain_rate"], args["auxiliary_rates"]

    plan = {
        "method": design,
        "target_region": {
            "local_offset_interval_s": args["interval"],
            "frequency_band_hz": [20, 60],
        },
        "channels": list(aux),
        "strain_highpass_hz": 20,
        "execution_contract": runner.load_config(),
    }
    event = measure_context(Reader(), 100, "event", plan, independent=False)
    control = measure_context(Reader(), 200, "background", plan, independent=True)
    assert event["value"] == control["value"]
    assert event["provenance"] == control["provenance"]
