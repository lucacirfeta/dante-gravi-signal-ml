#!/usr/bin/env python3
"""Run the frozen, outcome-blind DANTE-Light v6 Phase-A compute benchmark."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Callable

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_student import trainable_parameter_count
from src.dante_light.prefilter_v6_phase_a import (
    aggregation_contract,
    build_candidate,
    candidate_seed,
    file_sha256,
    load_phase_a_contract,
    synthetic_seed,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v6_phase_a.json"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "phase_a_compute_feasibility_v6.json"
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
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
    if values.size == 0 or not np.isfinite(values).all():
        raise ContractError("invalid Phase-A timing samples")
    return {
        "count": int(values.size),
        "mean_s": float(values.mean()),
        "median_s": float(np.median(values)),
        "p95_s": float(np.quantile(values, 0.95)),
        "maximum_s": float(values.max()),
    }


def _benchmark(
    function: Callable[[], torch.Tensor],
    *,
    warmup: int,
    repetitions: int,
    synchronize: bool,
) -> dict[str, float | int]:
    if warmup < 0 or repetitions < 1:
        raise ContractError("invalid Phase-A benchmark repetitions")
    with torch.inference_mode():
        for _ in range(warmup):
            output = function()
            if synchronize:
                torch.cuda.synchronize()
            if not torch.isfinite(output).all():
                raise ContractError("non-finite random-weight benchmark output")
        samples: list[float] = []
        for _ in range(repetitions):
            if synchronize:
                torch.cuda.synchronize()
            began = time.perf_counter()
            output = function()
            if synchronize:
                torch.cuda.synchronize()
            elapsed = time.perf_counter() - began
            if not torch.isfinite(output).all():
                raise ContractError("non-finite random-weight benchmark output")
            samples.append(elapsed)
    return _timing_summary(samples)


def _tensor_bytes(value: object) -> int:
    if isinstance(value, torch.Tensor):
        return int(value.numel() * value.element_size())
    if isinstance(value, (tuple, list)):
        return sum(_tensor_bytes(item) for item in value)
    if isinstance(value, dict):
        return sum(_tensor_bytes(item) for item in value.values())
    return 0


def _leaf_activation_bytes(model: torch.nn.Module, values: torch.Tensor) -> int:
    observed: list[int] = []
    handles = []
    for module in model.modules():
        if module is model or any(module.children()):
            continue
        handles.append(
            module.register_forward_hook(
                lambda _module, _inputs, output: observed.append(_tensor_bytes(output))
            )
        )
    try:
        with torch.inference_mode():
            output = model(values)
        if not torch.isfinite(output).all():
            raise ContractError("non-finite output during activation accounting")
    finally:
        for handle in handles:
            handle.remove()
    return int(sum(observed))


def _parameter_bytes(model: torch.nn.Module) -> int:
    return int(
        sum(parameter.numel() * parameter.element_size() for parameter in model.parameters())
    )


def _local_instance_count(model: torch.nn.Module, input_length: int) -> int | None:
    encoder = getattr(model, "encoder", None)
    if encoder is None:
        return None
    with torch.inference_mode():
        values = encoder(torch.zeros(1, 1, input_length, dtype=torch.float32))
    return int(values.shape[-1])


def _one_device(
    *,
    candidate: dict[str, Any],
    model: torch.nn.Module,
    cpu_input: torch.Tensor,
    device: torch.device,
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    model = model.to(device).eval()
    synchronization = device.type == "cuda"
    device_input = cpu_input.to(device)
    if synchronization:
        torch.cuda.synchronize()

    spec = benchmark["cuda" if synchronization else "cpu"]
    warmup = int(spec["warmup_repetitions"])
    repetitions = int(spec["repetitions"])
    inference = _benchmark(
        lambda: model(device_input),
        warmup=warmup,
        repetitions=repetitions,
        synchronize=synchronization,
    )

    transfer_and_inference = None
    if synchronization and bool(spec.get("include_host_to_device")):
        transfer_and_inference = _benchmark(
            lambda: model(cpu_input.to(device)),
            warmup=warmup,
            repetitions=repetitions,
            synchronize=True,
        )

    cuda_peak = None
    if synchronization:
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats(device)
        baseline = int(torch.cuda.memory_allocated(device))
        with torch.inference_mode():
            output = model(device_input)
        torch.cuda.synchronize()
        if not torch.isfinite(output).all():
            raise ContractError("non-finite output during CUDA memory accounting")
        cuda_peak = int(torch.cuda.max_memory_allocated(device) - baseline)

    return {
        "device": str(device),
        "inference_only": inference,
        "host_to_device_and_inference": transfer_and_inference,
        "cuda_peak_incremental_allocated_bytes": cuda_peak,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--devices", choices=("auto", "cpu", "cuda", "both"), default="auto"
    )
    args = parser.parse_args()

    config_path = args.config.resolve()
    contract = load_phase_a_contract(config_path, root=ROOT)
    teacher_reference = contract["parent_references"]["teacher_contract"]
    teacher = json.loads((ROOT / teacher_reference["path"]).read_text(encoding="utf-8"))
    aggregation = aggregation_contract(contract, teacher)

    sample_rate = int(teacher["representation"]["sample_rate_hz"])
    duration = float(teacher["representation"]["analysis_duration_s"])
    input_length = int(round(sample_rate * duration))
    if input_length != sample_rate * duration:
        raise ContractError("Phase-A signal duration does not map to an integer sample count")

    torch.use_deterministic_algorithms(
        bool(contract["benchmark"]["deterministic_algorithms"])
    )
    torch.set_num_threads(int(contract["benchmark"]["cpu"]["torch_num_threads"]))
    generator = torch.Generator(device="cpu")
    generator.manual_seed(synthetic_seed(contract["contract_digest"]))
    cpu_input = torch.randn(1, 1, input_length, generator=generator, dtype=torch.float32)

    want_cpu = args.devices in {"auto", "cpu", "both"}
    want_cuda = args.devices in {"auto", "cuda", "both"}
    if args.devices in {"cuda", "both"} and not torch.cuda.is_available():
        raise ContractError("CUDA was requested but is unavailable")
    devices: list[torch.device] = []
    if want_cpu and bool(contract["benchmark"]["cpu"]["enabled"]):
        devices.append(torch.device("cpu"))
    if (
        want_cuda
        and bool(contract["benchmark"]["cuda"]["enabled_if_available"])
        and torch.cuda.is_available()
    ):
        devices.append(torch.device("cuda"))
    if not devices:
        raise ContractError("no Phase-A benchmark device is enabled")

    results: dict[str, Any] = {}
    for candidate in contract["candidate_matrix"]:
        candidate_id = str(candidate["id"])
        torch.manual_seed(candidate_seed(contract["contract_digest"], candidate_id))
        model = build_candidate(candidate, aggregation).eval()
        local_instances = _local_instance_count(model, input_length)
        local_k = (
            aggregation.student_top_k(local_instances) if local_instances is not None else None
        )
        static = {
            "trainable_parameters": trainable_parameter_count(model),
            "parameter_bytes": _parameter_bytes(model),
            "input_bytes": _tensor_bytes(cpu_input),
            "leaf_activation_bytes_per_forward": _leaf_activation_bytes(model, cpu_input),
            "student_instance_count": local_instances,
            "student_top_k": local_k,
        }
        by_device: dict[str, Any] = {}
        for device in devices:
            torch.manual_seed(candidate_seed(contract["contract_digest"], candidate_id))
            fresh_model = build_candidate(candidate, aggregation).eval()
            by_device[device.type] = _one_device(
                candidate=candidate,
                model=fresh_model,
                cpu_input=cpu_input,
                device=device,
                benchmark=contract["benchmark"],
            )
        results[candidate_id] = {
            "candidate_contract": candidate,
            "static": static,
            "devices": by_device,
        }

    source_references = {
        "config": {"path": config_path.relative_to(ROOT).as_posix(), "sha256": file_sha256(config_path)},
        "architecture": {
            "path": "src/dante_light/prefilter_v6_phase_a.py",
            "sha256": file_sha256(ROOT / "src/dante_light/prefilter_v6_phase_a.py"),
        },
        "v5_baseline": contract["parent_references"]["v5_student_architectures"],
        "runner": {
            "path": "scripts/run_dante_light_prefilter_v6_phase_a.py",
            "sha256": file_sha256(Path(__file__).resolve()),
        },
    }
    body = {
        "schema_version": 1,
        "status": "PHASE_A_COMPUTE_FEASIBILITY_COMPLETE",
        "phase_id": contract["phase_id"],
        "contract_digest": contract["contract_digest"],
        "scientific_boundary": contract["scientific_boundary"],
        "outcome_access": {
            "teacher_scores": [],
            "morphology_labels": [],
            "development": [],
            "confirmation": [],
            "o4b": [],
        },
        "signal": {
            "sample_rate_hz": sample_rate,
            "duration_s": duration,
            "input_length": input_length,
            "batch_size": 1,
            "dtype": "float32",
            "source": "deterministic_standard_normal_synthetic",
            "seed": synthetic_seed(contract["contract_digest"]),
        },
        "aggregation": {
            "teacher_top_k": aggregation.teacher_top_k,
            "teacher_instance_count": aggregation.teacher_instance_count,
            "retained_fraction": aggregation.retained_fraction,
            "centroid_count_not_used_as_denominator": True,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "cuda_available": torch.cuda.is_available(),
            "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "torch_num_threads": torch.get_num_threads(),
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "automatic_mixed_precision": False,
        },
        "results": results,
        "decision": {
            "candidate_selected": False,
            "training_authorized": False,
            "routing_enabled": False,
            "scope": contract["decision_rule"]["allowed_conclusion"],
        },
        "source_references": source_references,
    }
    payload = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(args.output.resolve(), payload)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(args.output.resolve()),
                "artifact_digest": payload["artifact_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
