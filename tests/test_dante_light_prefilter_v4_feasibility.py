from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest
from scipy import signal
import torch

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_bank import (
    greedy_farthest_bank,
    phase_maximized_noise_weighted_match,
)
from src.dante_light.prefilter_v4_cost import (
    expected_batch_saving,
    paired_cost_accounting,
)
from src.dante_light.prefilter_v4_phase import extract_phase_feasibility_features
from src.dante_light.prefilter_v4_student import (
    ComplexSTFT2DStudentProxy,
    Raw1DDepthwiseStudentProxy,
    trainable_parameter_count,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "dante_light_prefilter_v4_feasibility.json"
MINIMUM_MATCH_CONTRACT = (
    ROOT / "config" / "dante_light_prefilter_v4_minimum_match_contract.json"
)


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def test_feasibility_contract_cannot_freeze_or_access_outcomes() -> None:
    payload = _config()
    assert payload["status"] == "FEASIBILITY_ONLY_NOT_A_V4_PROTOCOL"
    assert payload["routing_enabled"] is False
    boundary = payload["scientific_boundary"]
    assert boundary["may_freeze_v4"] is False
    assert boundary["may_select_a_candidate"] is False
    assert boundary["may_access_development_labels"] is False
    assert boundary["may_access_reserved_confirmation"] is False
    assert boundary["may_access_o4b_outcomes"] is False


def test_future_minimum_match_gate_is_frozen_without_retroactive_preregistration() -> None:
    payload = json.loads(MINIMUM_MATCH_CONTRACT.read_text(encoding="utf-8"))
    assert payload["criterion_frozen"] is True
    assert payload["v4_protocol_frozen"] is False
    assert payload["routing_enabled"] is False
    future = payload["future_preregistered_gate"]
    assert future["status"] == "DEFINED_NOT_EVALUATED"
    assert future["threshold"] == pytest.approx(0.97)
    assert future["pre_registered_for_future_evaluations"] is True
    assert future["physical_interpretation"][
        "maximum_snr_loss_fraction_from_bank_discreteness"
    ] == pytest.approx(0.03)
    assert future["physical_interpretation"][
        "minimum_euclidean_sensitive_volume_fraction_if_all_other_factors_are_fixed"
    ] == pytest.approx(0.97**3)
    observed = payload["already_observed_feasibility_artifact"]
    assert observed["pre_registered_for_this_artifact"] is False
    assert observed["classification"] == "RETROSPECTIVE_EXTERNAL_BENCHMARK_FAIL"


def test_expected_cost_accounting_uses_means_and_marks_tail_unidentified() -> None:
    result = expected_batch_saving(
        reduction_fraction=0.25,
        prefilter_cost_s=[0.004, 0.006],
        avoidable_exact_cost_s=[0.3, 0.5],
    )
    assert result["mean_prefilter_cost_s"] == pytest.approx(0.005)
    assert result["expected_gross_saving_s"] == pytest.approx(0.1)
    assert result["expected_net_saving_s"] == pytest.approx(0.095)
    assert result["tail_latency_identified"] is False


def test_paired_cost_accounting_does_not_mix_marginal_quantiles() -> None:
    result = paired_cost_accounting(
        rejected=[False, True, False, True],
        prefilter_cost_s=[0.01, 0.02, 0.03, 0.04],
        avoidable_exact_cost_s=[1.0, 0.5, 1.0, 0.25],
    )
    assert result["reduction_fraction"] == pytest.approx(0.5)
    assert result["mean_net_saving_s"] == pytest.approx(0.1625)


def test_phase_probe_detects_phase_order_destroyed_by_scrambling() -> None:
    payload = _config()
    sample_rate = payload["signal_contract"]["sample_rate_hz"]
    duration = payload["signal_contract"]["duration_s"]
    phase_config = payload["phase_probe"]
    probe = phase_config["synthetic_chirp"]
    time = np.arange(int(sample_rate * duration), dtype=np.float64) / sample_rate
    values = np.zeros(time.size, dtype=np.float64)
    selected = (time >= probe["start_s"]) & (
        time < probe["start_s"] + probe["duration_s"]
    )
    values[selected] = signal.chirp(
        time[selected] - probe["start_s"],
        f0=probe["f0_hz"],
        t1=probe["duration_s"],
        f1=probe["f1_hz"],
        method=probe["method"],
    )
    rng = np.random.default_rng(phase_config["synthetic_seed"])
    spectrum = np.fft.rfft(values)
    spectrum[1:] *= np.exp(1j * rng.uniform(-np.pi, np.pi, spectrum.size - 1))
    scrambled = np.fft.irfft(spectrum, n=values.size)
    ordered = extract_phase_feasibility_features(
        values,
        sample_rate_hz=sample_rate,
        analysis_band_hz=payload["signal_contract"]["analysis_band_hz"],
        config=phase_config,
    )
    destroyed = extract_phase_feasibility_features(
        scrambled,
        sample_rate_hz=sample_rate,
        analysis_band_hz=payload["signal_contract"]["analysis_band_hz"],
        config=phase_config,
    )
    assert ordered["phase_frequency_time_spearman"] > 0.7
    assert ordered["phase_cubic_circular_residual"] < 0.1
    assert destroyed["phase_cubic_circular_residual"] > 0.5


def test_phase_probe_rejects_nonfinite_input() -> None:
    payload = _config()
    values = np.zeros(4096, dtype=np.float64)
    values[3] = np.nan
    with pytest.raises(ContractError):
        extract_phase_feasibility_features(
            values,
            sample_rate_hz=4096,
            analysis_band_hz=[20.0, 1024.0],
            config=payload["phase_probe"],
        )


def test_noise_weighted_match_identity_and_symmetry() -> None:
    rng = np.random.default_rng(9)
    n = 1024
    size = n // 2 + 1
    first = rng.standard_normal(size) + 1j * rng.standard_normal(size)
    second = rng.standard_normal(size) + 1j * rng.standard_normal(size)
    psd = np.linspace(1.0, 2.0, size)
    identity = phase_maximized_noise_weighted_match(
        first, first, psd, delta_f_hz=1.0 / 8.0, n_time_samples=n
    )
    forward = phase_maximized_noise_weighted_match(
        first, second, psd, delta_f_hz=1.0 / 8.0, n_time_samples=n
    )
    reverse = phase_maximized_noise_weighted_match(
        second, first, psd, delta_f_hz=1.0 / 8.0, n_time_samples=n
    )
    assert identity == pytest.approx(1.0)
    assert forward == pytest.approx(reverse)


def test_greedy_bank_coverage_is_monotone() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.8, 0.2, 0.1],
            [0.8, 1.0, 0.3, 0.2],
            [0.2, 0.3, 1.0, 0.7],
            [0.1, 0.2, 0.7, 1.0],
        ]
    )
    result = greedy_farthest_bank(matrix, bank_sizes=[1, 2, 4], anchor_index=0)
    curve = result["curve"]
    assert curve["1"]["minimum_match"] <= curve["2"]["minimum_match"]
    assert curve["2"]["minimum_match"] <= curve["4"]["minimum_match"]
    assert curve["4"]["minimum_match"] == pytest.approx(1.0)


def test_student_proxies_have_finite_shapes_and_small_parameter_counts() -> None:
    torch.manual_seed(4)
    raw = Raw1DDepthwiseStudentProxy().eval()
    stft = ComplexSTFT2DStudentProxy().eval()
    with torch.inference_mode():
        raw_result = raw(torch.zeros(2, 1, 131072))
        stft_result = stft(torch.zeros(2, 2, 503, 255))
    assert raw_result.shape == (2, 1)
    assert stft_result.shape == (2, 1)
    assert torch.isfinite(raw_result).all()
    assert torch.isfinite(stft_result).all()
    assert trainable_parameter_count(raw) < 10_000
    assert trainable_parameter_count(stft) < 10_000


def test_committed_feasibility_artifacts_verify_fail_closed(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v4_feasibility.py"),
            "--write-summary",
            str(summary),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["status"] == "FEASIBILITY_COMPLETE_AWAITING_SCIENTIFIC_DECISION"
    assert payload["routing_enabled"] is False
    assert payload["candidate_selected"] is False
    assert payload["protocol_frozen"] is False
    assert payload["cost_accounting"]["tail_latency_identified"] is False


def test_cost_provenance_paths_are_repository_relative() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/prefilter_l4_v4_feasibility"
        / "cost_accounting_v3_corrected.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    for key in ("screening", "benchmark"):
        stored = payload["provenance"][key]["path"]
        assert not Path(stored).is_absolute()
        assert "\\" not in stored
        assert ".." not in Path(stored).parts


def test_feasibility_verifier_passes_from_relocated_checkout(tmp_path: Path) -> None:
    clone = tmp_path / "independent_checkout"
    required = (
        "scripts/verify_dante_light_prefilter_v4_feasibility.py",
        "scripts/run_dante_light_prefilter_v4_feasibility.py",
        "scripts/run_dante_light_prefilter_v4_bank_coverage.py",
        "scripts/audit_dante_light_prefilter_v3_cost.py",
        "src/__init__.py",
        "src/dante_light/__init__.py",
        "src/dante_light/contracts.py",
        "src/dante_light/prefilter_v4_bank.py",
        "src/dante_light/prefilter_v4_cost.py",
        "src/dante_light/prefilter_v4_phase.py",
        "src/dante_light/prefilter_v4_student.py",
        "config/dante_light_prefilter_v4_feasibility.json",
        "config/dante_light_prefilter_v4_minimum_match_contract.json",
        "artifacts/dante_light/prefilter_l4_v3/screening_summary_v3.json",
        "benchmarks/dante_light_l1_score_only_shared.json",
        "artifacts/dante_light/prefilter_l4_v4_feasibility/compute_feasibility_v4.json",
        "artifacts/dante_light/prefilter_l4_v4_feasibility/mini_bank_coverage_v4.json",
        "artifacts/dante_light/prefilter_l4_v4_feasibility/cost_accounting_v3_corrected.json",
    )
    for relative in required:
        source = ROOT / relative
        destination = clone / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    completed = subprocess.run(
        [
            sys.executable,
            str(clone / "scripts/verify_dante_light_prefilter_v4_feasibility.py"),
        ],
        cwd=clone,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"status": "PASS"' in completed.stdout


def test_feasibility_verifier_rejects_corrupted_match_matrix(tmp_path: Path) -> None:
    source = ROOT / "artifacts/dante_light/prefilter_l4_v4_feasibility"
    for name in (
        "compute_feasibility_v4.json",
        "mini_bank_coverage_v4.json",
        "cost_accounting_v3_corrected.json",
    ):
        shutil.copy2(source / name, tmp_path / name)
    bank_path = tmp_path / "mini_bank_coverage_v4.json"
    bank = json.loads(bank_path.read_text(encoding="utf-8"))
    bank["match_matrix"]["values"][0][1] += 0.01
    bank_path.write_text(json.dumps(bank), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v4_feasibility.py"),
            "--artifact-root",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "match matrix byte hash mismatch" in completed.stderr
