#!/usr/bin/env python3
"""Run label-blind phase and student feasibility benchmarks.

This executable cannot freeze a protocol or access DANTE cohort manifests.  It
uses deterministic synthetic/random inputs and writes a provenance-bound JSON
artifact for a later human scientific decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Callable

import numpy as np
from scipy import signal
import scipy
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_phase import extract_phase_feasibility_features
from src.dante_light.prefilter_v4_student import (
    ComplexSTFT2DStudentProxy,
    Raw1DDepthwiseStudentProxy,
    trainable_parameter_count,
)


DEFAULT_CONFIG = ROOT / "config" / "dante_light_prefilter_v4_feasibility.json"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "dante_light"
    / "prefilter_l4_v4_feasibility"
    / "compute_feasibility_v4.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _timing_summary(samples: list[float]) -> dict[str, float | int]:
    values = np.asarray(samples, dtype=np.float64)
    return {
        "count": int(values.size),
        "mean_s": float(np.mean(values)),
        "median_s": float(np.median(values)),
        "p95_s": float(np.quantile(values, 0.95)),
        "maximum_s": float(np.max(values)),
    }


def _benchmark(
    function: Callable[[], object], *, repetitions: int, warmup: int, synchronize: bool
) -> dict[str, float | int]:
    for _ in range(warmup):
        function()
        if synchronize:
            torch.cuda.synchronize()
    samples = []
    for _ in range(repetitions):
        if synchronize:
            torch.cuda.synchronize()
        began = time.perf_counter()
        function()
        if synchronize:
            torch.cuda.synchronize()
        samples.append(time.perf_counter() - began)
    return _timing_summary(samples)


def _synthetic_inputs(config: dict) -> dict[str, np.ndarray]:
    contract = config["signal_contract"]
    phase = config["phase_probe"]
    probe = phase["synthetic_chirp"]
    sample_rate = int(contract["sample_rate_hz"])
    count = int(round(float(contract["duration_s"]) * sample_rate))
    time_axis = np.arange(count, dtype=np.float64) / sample_rate
    ordered = np.zeros(count, dtype=np.float64)
    selected = (time_axis >= float(probe["start_s"])) & (
        time_axis < float(probe["start_s"]) + float(probe["duration_s"])
    )
    ordered[selected] = signal.chirp(
        time_axis[selected] - float(probe["start_s"]),
        f0=float(probe["f0_hz"]),
        t1=float(probe["duration_s"]),
        f1=float(probe["f1_hz"]),
        method=str(probe["method"]),
    )
    rng = np.random.default_rng(int(phase["synthetic_seed"]))
    spectrum = np.fft.rfft(ordered)
    spectrum[1:] *= np.exp(1j * rng.uniform(-np.pi, np.pi, spectrum.size - 1))
    scrambled = np.fft.irfft(spectrum, n=count)
    noise = rng.standard_normal(count)
    return {"ordered_chirp": ordered, "phase_scrambled": scrambled, "noise": noise}


def _complex_stft_tensor(
    values: np.ndarray, *, sample_rate: int, band: list[float]
) -> torch.Tensor:
    frequencies, _times, transform = signal.stft(
        values,
        fs=sample_rate,
        window="hann",
        nperseg=1024,
        noverlap=512,
        nfft=1024,
        boundary=None,
        padded=False,
    )
    selected = (frequencies >= float(band[0])) & (frequencies <= float(band[1]))
    band_transform = transform[selected]
    channels = np.stack((band_transform.real, band_transform.imag)).astype(np.float32)
    return torch.from_numpy(channels)


def _student_benchmarks(config: dict, noise: np.ndarray) -> dict[str, object]:
    probe = config["student_probe"]
    signal_contract = config["signal_contract"]
    torch.manual_seed(int(probe["seed"]))
    repetitions = int(probe["benchmark_repetitions"])
    warmup = int(probe["warmup_repetitions"])
    sample_rate = int(signal_contract["sample_rate_hz"])
    band = signal_contract["analysis_band_hz"]
    devices = ["cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")
    result: dict[str, object] = {}
    for device_name in devices:
        device = torch.device(device_name)
        synchronize = device.type == "cuda"
        raw_model = Raw1DDepthwiseStudentProxy().eval().to(device)
        stft_model = ComplexSTFT2DStudentProxy().eval().to(device)
        architecture_result: dict[str, object] = {
            "raw_1d_depthwise_proxy": {
                "trainable_parameters": trainable_parameter_count(raw_model),
                "timings_by_batch": {},
            },
            "complex_stft_2d_proxy": {
                "trainable_parameters": trainable_parameter_count(stft_model),
                "timings_by_batch": {},
            },
        }
        for raw_batch in probe["batch_sizes"]:
            batch_size = int(raw_batch)
            raw_cpu = torch.from_numpy(noise.astype(np.float32)).reshape(1, 1, -1)
            raw_cpu = raw_cpu.repeat(batch_size, 1, 1)
            stft_cpu = _complex_stft_tensor(noise, sample_rate=sample_rate, band=band)
            stft_cpu = stft_cpu.unsqueeze(0).repeat(batch_size, 1, 1, 1)

            def raw_inference() -> torch.Tensor:
                with torch.inference_mode():
                    return raw_model(raw_cpu.to(device)).cpu()

            def stft_inference() -> torch.Tensor:
                with torch.inference_mode():
                    return stft_model(stft_cpu.to(device)).cpu()

            raw_timing = _benchmark(
                raw_inference,
                repetitions=repetitions,
                warmup=warmup,
                synchronize=synchronize,
            )
            raw_timing["mean_per_window_s"] = float(raw_timing["mean_s"]) / batch_size
            architecture_result["raw_1d_depthwise_proxy"]["timings_by_batch"][
                str(batch_size)
            ] = {
                "transfer_and_inference": raw_timing
            }
            stft_timing = _benchmark(
                stft_inference,
                repetitions=repetitions,
                warmup=warmup,
                synchronize=synchronize,
            )
            stft_timing["mean_per_window_s"] = float(stft_timing["mean_s"]) / batch_size
            architecture_result["complex_stft_2d_proxy"]["timings_by_batch"][
                str(batch_size)
            ] = {
                "transfer_and_inference_excluding_stft": stft_timing
            }
        result[device_name] = architecture_result

    def stft_preprocessing() -> torch.Tensor:
        return _complex_stft_tensor(noise, sample_rate=sample_rate, band=band)

    result["complex_stft_preprocessing_cpu"] = _benchmark(
        stft_preprocessing,
        repetitions=repetitions,
        warmup=warmup,
        synchronize=False,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config_path = args.config.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("status") != "FEASIBILITY_ONLY_NOT_A_V4_PROTOCOL":
        raise ContractError("refusing to run without the feasibility-only boundary")
    boundary = config["scientific_boundary"]
    forbidden = (
        "may_freeze_v4",
        "may_select_a_candidate",
        "may_access_development_labels",
        "may_access_reserved_confirmation",
        "may_access_o4b_outcomes",
    )
    if any(bool(boundary.get(key)) for key in forbidden):
        raise ContractError("feasibility config permits a forbidden scientific action")

    inputs = _synthetic_inputs(config)
    contract = config["signal_contract"]
    phase_config = config["phase_probe"]
    phase_features = {
        name: extract_phase_feasibility_features(
            values,
            sample_rate_hz=int(contract["sample_rate_hz"]),
            analysis_band_hz=contract["analysis_band_hz"],
            config=phase_config,
        )
        for name, values in inputs.items()
    }
    rng = np.random.default_rng(int(phase_config["synthetic_seed"]) + 1)
    ordered_spectrum = np.fft.rfft(inputs["ordered_chirp"])
    control_metrics: dict[str, list[float]] = {
        key: [] for key in phase_features["ordered_chirp"]
    }
    noise_metrics: dict[str, list[float]] = {
        key: [] for key in phase_features["ordered_chirp"]
    }
    for _ in range(int(phase_config["synthetic_control_repetitions"])):
        randomized = ordered_spectrum.copy()
        randomized[1:] *= np.exp(
            1j * rng.uniform(-np.pi, np.pi, randomized.size - 1)
        )
        scrambled = np.fft.irfft(randomized, n=inputs["ordered_chirp"].size)
        noise = rng.standard_normal(inputs["ordered_chirp"].size)
        for target, values in (
            (control_metrics, scrambled),
            (noise_metrics, noise),
        ):
            features = extract_phase_feasibility_features(
                values,
                sample_rate_hz=int(contract["sample_rate_hz"]),
                analysis_band_hz=contract["analysis_band_hz"],
                config=phase_config,
            )
            for key, value in features.items():
                target[key].append(float(value))

    def summarize_controls(values: dict[str, list[float]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, metric_values in values.items():
            array = np.asarray(metric_values, dtype=np.float64)
            result[key] = {
                "count": int(array.size),
                "mean": float(np.mean(array)),
                "median": float(np.median(array)),
                "p95": float(np.quantile(array, 0.95)),
                "maximum": float(np.max(array)),
            }
        return result

    def phase_call() -> dict[str, float]:
        return extract_phase_feasibility_features(
            inputs["noise"],
            sample_rate_hz=int(contract["sample_rate_hz"]),
            analysis_band_hz=contract["analysis_band_hz"],
            config=phase_config,
        )

    phase_timing = _benchmark(
        phase_call,
        repetitions=int(phase_config["benchmark_repetitions"]),
        warmup=int(phase_config["warmup_repetitions"]),
        synchronize=False,
    )
    payload = {
        "schema_version": 1,
        "status": "COMPLETE_FEASIBILITY_ONLY",
        "routing_enabled": False,
        "candidate_selected": False,
        "protocol_frozen": False,
        "outcome_access": {
            "development_labels": False,
            "reserved_confirmation": False,
            "o4b": False,
        },
        "config": {"path": str(config_path.relative_to(ROOT)), "sha256": _sha256(config_path)},
        "phase_probe": {
            "interpretation": (
                "Synthetic behavior and runtime only; no discriminative or retention claim."
            ),
            "synthetic_features": phase_features,
            "phase_scrambled_control_distribution": summarize_controls(control_metrics),
            "noise_control_distribution": summarize_controls(noise_metrics),
            "timing": phase_timing,
        },
        "student_probe": {
            "interpretation": (
                "Random-weight inference cost only; no learnability, fidelity, or retention claim."
            ),
            "benchmarks": _student_benchmarks(config, inputs["noise"]),
        },
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "torch": torch.__version__,
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "source_sha256": {
            "runner": _sha256(Path(__file__).resolve()),
            "phase_module": _sha256(ROOT / "src/dante_light/prefilter_v4_phase.py"),
            "student_module": _sha256(ROOT / "src/dante_light/prefilter_v4_student.py"),
        },
    }
    _atomic_json(args.output.resolve(), payload)
    print(json.dumps({"status": payload["status"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
