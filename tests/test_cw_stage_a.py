"""Synthetic fixtures only; no detector strain, encoder or O4b inputs."""
import copy
import json
import runpy
from types import SimpleNamespace
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import pytest

from src.validation import cw_stage_a as cw

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config/dante_cw_stage_a_v1.json"


@pytest.fixture(scope="module")
def c():
    return cw.load_contract(CONTRACT)


def test_approved_grid_and_pairing(c):
    grid = cw.task_grid(c)
    assert len(grid) == 3280
    assert len({t["id"] for t in grid}) == len(grid)
    assert {kind: sum(t["kind"] == kind for t in grid)
            for kind in ("baseline", "single", "pair")} == {
                "baseline": 16, "single": 2880, "pair": 384}
    assert {t["noise"] for t in grid} == set(range(16))
    assert {t["pulsar"] for t in grid if t["kind"] == "single"} == set(range(18))
    assert c["probes"]["frequencies_hz"][13] < c["preprocessing"]["frange"][0]
    assert c["probes"]["frequencies_hz"][15] > c["preprocessing"]["frange"][1]


@pytest.mark.parametrize("center", [0.5, 1, 1.25, 2])
def test_bin_overlap_integrates_constant_density(center):
    f = np.arange(5.0)
    assert cw.band_power(f, np.full(5, 3.0), center, 1) == 3


def test_one_sided_synthesis_normalization():
    class FixedRNG:
        def standard_normal(self, count):
            return np.ones(count)

    fs, count, density = 64, 1024, 3.0
    signal = cw.synthesize(np.full(count // 2 + 1, density), fs, FixedRNG())
    spectrum = np.fft.rfft(signal)
    np.testing.assert_allclose(spectrum[1:-1].real, np.sqrt(count * fs * density / 4), rtol=1e-13)
    np.testing.assert_allclose(spectrum[1:-1].imag, np.sqrt(count * fs * density / 4), rtol=1e-13)
    # One-sided periodogram bin expectation and Parseval, not a stochastic pass rule.
    power = 2 * np.abs(spectrum[1:-1]) ** 2 / (count * fs)
    np.testing.assert_allclose(power, density, rtol=1e-13)
    np.testing.assert_allclose(np.mean(signal ** 2), density * fs / count * (count // 2 - 1), rtol=1e-13)
    assert abs(spectrum[0]) < 1e-10
    assert abs(spectrum[-1]) < 1e-10


def test_seed_children_and_central_context_identity(c):
    children = np.random.SeedSequence(c["noise"]["seed"]).spawn(16)
    a = cw.synthesize(np.ones(513), 64, np.random.Generator(np.random.PCG64(children[0])))
    b = cw.synthesize(np.ones(513), 64, np.random.Generator(np.random.PCG64(children[0])))
    d = cw.synthesize(np.ones(513), 64, np.random.Generator(np.random.PCG64(children[1])))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, d)


def test_design_psd_low_extension(c):
    low = c["noise"]["low_flat_hz"]
    result = cw.model_psd([0, 1, low], c)
    assert np.all(result == result[0])


@pytest.mark.parametrize("pulsar", range(18))
@pytest.mark.parametrize("phase", [0, np.pi / 2])
def test_every_published_tone_dose_in_band(c, pulsar, phase):
    component = {"f": c["probes"]["frequencies_hz"][pulsar], "dose": 1, "phase": phase}
    tone, metadata = cw.make_tone(component, c)
    n = c["noise"]
    start = int(n["pad_seconds"] * n["sample_rate_hz"])
    stop = start + int(n["analysis_seconds"] * n["sample_rate_hz"])
    f, psd = cw.diagnostic_psd(tone[start:stop], c)
    measured = cw.band_power(f, psd, component["f"], c["probes"]["band_hz"])
    np.testing.assert_allclose(measured, metadata["target_line_band_power"], rtol=1e-12, atol=0)


@pytest.mark.parametrize("dose", [0.01, 0.1, 1, 10, 100])
def test_all_approved_doses(c, dose):
    tone, metadata = cw.make_tone({"f": c["probes"]["frequencies_hz"][0], "dose": dose, "phase": 0}, c)
    assert len(tone) == c["noise"]["context_seconds"] * c["noise"]["sample_rate_hz"]
    assert metadata["target_line_band_power"] / metadata["model_noise_band_power"] == dose


@pytest.mark.parametrize("invalid", [0, -1, np.nan, np.inf])
def test_invalid_denominator_not_clipped(invalid):
    with pytest.raises(ValueError, match="denominator"):
        cw.paired_metrics(invalid, 1, 1)


def test_negative_response_and_unsigned_image_safety():
    assert cw.paired_metrics(2, 1, 0.5)["G"] == -1
    assert cw.image_difference(np.zeros((2, 2, 3), np.uint8),
                               np.full((2, 2, 3), 255, np.uint8)) == 1


def test_runtime_source_boundary(c):
    runtime = cw.audit(c, ROOT)
    assert runtime["filter_order"] == 10
    assert runtime["versions"] == c["runtime_versions"]


def test_source_mismatch_is_not_waived(c):
    changed = copy.deepcopy(c)
    changed["inherited_sha256"]["src/core/preprocessor.py"] = "0" * 64
    with pytest.raises(ValueError, match="provenance"):
        cw.audit(changed, ROOT)


def test_inherited_config_mismatch_is_not_waived(c):
    changed = copy.deepcopy(c)
    changed["preprocessing"]["f_high"] += 1
    with pytest.raises(ValueError, match="scientific config"):
        cw.audit(changed, ROOT)


def test_incomplete_context_rejected(c):
    with pytest.raises(ValueError, match="complete context"):
        cw.preprocess(np.zeros(10), c)


def test_no_active_production_route(c):
    source = Path(cw.__file__).read_text()
    assert "fetch_strain_data(" not in source
    assert "DINO" not in source
    assert "resample(" not in source
    assert c["scope"] == "synthetic_design_noise_descriptive_preprocessing_only"
    assert c["diagnostic"]["acceptance_threshold"] is None


def test_native_fixture_exact_inherited_worker(c, monkeypatch):
    from src.core import data_loader
    from src.core.patch_producer import _worker_preprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("real strain fetch forbidden")

    monkeypatch.setattr(data_loader, "fetch_strain_data", forbidden)
    n = c["noise"]
    fs = n["sample_rate_hz"]
    count = int(fs * n["synthesis_seconds"])
    psd = cw.model_psd(np.fft.rfftfreq(count, 1 / fs), c)
    seed = np.random.SeedSequence(n["seed"]).spawn(n["realizations"])[0]
    full = cw.synthesize(psd, fs, np.random.Generator(np.random.PCG64(seed)))
    start = int((n["synthesis_seconds"] - n["context_seconds"]) * fs / 2)
    noise = full[start:start + int(n["context_seconds"] * fs)]
    tone, _ = cw.make_tone({"f": c["probes"]["frequencies_hz"][14], "dose": 1, "phase": 0}, c)
    values = noise + tone
    # Exercise a real spawned worker, not only an in-process fixture.
    with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as pool:
        observed = pool.submit(cw.preprocess, values, c).result()
    identity, rgb = _worker_preprocess(values, -n["pad_seconds"], 1 / fs, "synthetic",
                                      0, n["analysis_seconds"], True)
    assert identity == 0
    assert np.array_equal(rgb, observed["rgb"])
    assert len(observed["spectral_f_hz"]) == int(fs * n["analysis_seconds"] / 2) + 1
    assert np.array_equal(observed["resized_q_mean_frequency_profile"], observed["scalar_q"].mean(axis=0))


def test_descriptive_summaries_do_not_pool_phase_or_dose():
    rows = []
    for phase in [0, np.pi / 2]:
        for noise in range(16):
            rows.append({"kind": "single", "pulsar": 0, "dose": 1, "phase": phase,
                         "noise": noise, "rgb_difference": noise / 16,
                         "bands": [{key: float(noise) for key in ["P_base", "P_injected", "delta_P", "E", "G"]}]})
    result = cw.summarize(rows)
    assert len(result) == 2
    assert all(row["noises"] == 16 for row in result)
    assert all(row["G"] == {"median": 7.5, "minimum": 0, "maximum": 15} for row in result)


def test_receipts_retained_metrics_and_tamper_rejection(c, tmp_path, monkeypatch):
    fixture = copy.deepcopy(c)
    fixture["noise"]["realizations"] = 1
    fixture["probes"].update(frequencies_hz=[100], doses=[1], phase_radians=[0], pair_ids=[])
    fixture["expected_contexts"] = 2
    contract = tmp_path / "fixture.json"
    contract.write_text(json.dumps(fixture))
    for name in ["noise", "arrays", "receipts"]:
        (tmp_path / name).mkdir()
    noise_path = tmp_path / "noise/00.npy"
    np.save(noise_path, np.zeros(40 * 16384))
    noise_hash = cw.sha256(noise_path)

    def fake_preprocess(values, contract):
        return {"spectral_f_hz": np.arange(8193, dtype=float),
                "spectral_psd": np.ones(8193),
                "rgb": np.zeros((256, 256, 3), np.uint8)}

    monkeypatch.setattr(cw, "preprocess", fake_preprocess)
    for task in cw.task_grid(fixture):
        cw._worker((task, str(contract), str(tmp_path), noise_hash, "00000"))
    assert cw.verify_artifacts(tmp_path, fixture)["contexts"] == 2
    receipt = tmp_path / "receipts/00001.json"
    changed = json.loads(receipt.read_text())
    changed["components"][0]["f"] += 1
    receipt.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="component binding"):
        cw.verify_artifacts(tmp_path, fixture)


def test_noise_tamper_rejected_before_processing(c, tmp_path):
    (tmp_path / "noise").mkdir()
    np.save(tmp_path / "noise/00.npy", np.zeros(40 * 16384))
    with pytest.raises(ValueError, match="noise identity"):
        cw._worker((cw.task_grid(c)[0], str(CONTRACT), str(tmp_path), "0" * 64, "00000"))


def test_supervisor_observes_exit_and_refuses_duplicate(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(ROOT / "scripts/run_dante_cw_stage_a.py"))
    class Child:
        pid = 123
        def wait(self):
            return 7

    monkeypatch.setattr(namespace["subprocess"], "Popen", lambda *a, **kw: Child())
    args = SimpleNamespace(output=str(tmp_path / "run_v1"), config="fixture",
                           config_sha256="x", module_sha256="y")
    assert namespace["supervise"](args) == 7
    assert "RUN_EXIT_CODE=7" in (tmp_path / "run_v1.supervisor.log").read_text()
    with pytest.raises(FileExistsError):
        namespace["supervise"](args)


def test_supervisor_rejects_existing_run(tmp_path):
    namespace = runpy.run_path(str(ROOT / "scripts/run_dante_cw_stage_a.py"))
    output = tmp_path / "run_v1"
    output.mkdir()
    with pytest.raises(FileExistsError, match="no resume"):
        namespace["supervise"](SimpleNamespace(output=str(output)))
