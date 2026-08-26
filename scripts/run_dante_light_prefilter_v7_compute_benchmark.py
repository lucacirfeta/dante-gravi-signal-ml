"""Benchmark the complete random-weight five-member v7 routing path."""

from __future__ import annotations

import argparse
import hashlib
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
from src.dante_light.prefilter_v7_training_freeze import (
    build_ensemble,
    derive_seed,
    file_sha256,
    load_training_freeze,
)


DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_design"
    / "five_member_compute_benchmark_v7.json"
)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _timing_summary(samples: list[float]) -> dict[str, float | int]:
    values = np.asarray(samples, dtype=np.float64)
    if values.size == 0 or not np.isfinite(values).all() or np.any(values <= 0.0):
        raise ContractError("v7 benchmark produced invalid timing samples")
    return {
        "count": int(values.size),
        "mean_s": float(values.mean()),
        "median_s": float(np.median(values)),
        "p95_s": float(np.quantile(values, 0.95)),
        "maximum_s": float(values.max()),
        "standard_deviation_s": float(values.std(ddof=0)),
    }


def _audit_selected(seed: int, fraction: float, window_id: str) -> bool:
    digest = hashlib.sha256(f"{seed}:{window_id}".encode("ascii")).digest()
    uniform = int.from_bytes(digest[:8], "big") / float(2**64)
    return uniform < fraction


def _benchmark(
    function: Callable[[], tuple[float, bool, bool]], *, warmup: int, repetitions: int
) -> tuple[dict[str, float | int], tuple[float, bool, bool]]:
    if warmup < 0 or repetitions < 1:
        raise ContractError("v7 benchmark repetition contract is invalid")
    observed: tuple[float, bool, bool] | None = None
    samples: list[float] = []
    with torch.inference_mode():
        for _ in range(warmup):
            observed = function()
        for _ in range(repetitions):
            began = time.perf_counter()
            observed = function()
            samples.append(time.perf_counter() - began)
    if observed is None or not math.isfinite(observed[0]) or not 0.0 <= observed[0] <= 1.0:
        raise ContractError("v7 benchmark produced an invalid defer score")
    return _timing_summary(samples), observed


def _historical_exact_cost(payload: Any) -> float:
    observed: list[float] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "mean_avoidable_exact_path_cost_s":
                observed.append(float(value))
            else:
                observed.extend(_historical_exact_cost_values(value))
    unique = sorted(set(observed))
    if len(unique) != 1 or not math.isfinite(unique[0]) or unique[0] <= 0.0:
        raise ContractError("historical exact-path cost is absent or inconsistent")
    return unique[0]


def _historical_exact_cost_values(payload: Any) -> list[float]:
    values: list[float] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "mean_avoidable_exact_path_cost_s":
                values.append(float(value))
            else:
                values.extend(_historical_exact_cost_values(value))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_historical_exact_cost_values(value))
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract = load_training_freeze(root=ROOT)
    benchmark = contract["benchmark"]
    torch.use_deterministic_algorithms(bool(benchmark["deterministic_algorithms"]))
    torch.set_num_threads(int(benchmark["torch_num_threads"]))
    input_seed = derive_seed(
        [contract["training_contract_digest"]], "outcome_blind_compute_input"
    )
    audit_seed = derive_seed(
        [contract["training_contract_digest"]], "outcome_blind_compute_audit"
    )
    generator = np.random.default_rng(input_seed)
    strain = generator.standard_normal(4096 * 32).astype(np.float32)
    member_seeds = [int(value) for value in contract["candidate"]["member_seeds"]]
    startup_began = time.perf_counter()
    ensemble = build_ensemble(ROOT, member_seeds).cpu().eval()
    startup_s = time.perf_counter() - startup_began
    member = ensemble.members[0]
    threshold = float(benchmark["mechanical_routing_threshold"])
    audit_fraction = float(contract["audit"]["nominal_fraction"])
    window_id = "dlv7-outcome-blind-compute-proxy"

    def full_path() -> tuple[float, bool, bool]:
        values = torch.from_numpy(strain).view(1, 1, -1)
        score = float(ensemble(values).item())
        defer = score >= threshold
        audited = (not defer) and _audit_selected(audit_seed, audit_fraction, window_id)
        return score, defer, audited

    def single_member_path() -> tuple[float, bool, bool]:
        values = torch.from_numpy(strain).view(1, 1, -1)
        score = float(torch.sigmoid(member(values)).item())
        return score, score >= threshold, False

    full_timing, full_output = _benchmark(
        full_path,
        warmup=int(benchmark["warmup_repetitions"]),
        repetitions=int(benchmark["timed_repetitions"]),
    )
    member_timing, member_output = _benchmark(
        single_member_path,
        warmup=int(benchmark["warmup_repetitions"]),
        repetitions=int(benchmark["timed_repetitions"]),
    )
    historical_path = (
        ROOT
        / "artifacts/dante_light/prefilter_l4_v5_development/screening_summary_v5.json"
    )
    historical = json.loads(historical_path.read_text(encoding="utf-8"))
    exact_cost_s = _historical_exact_cost(historical)
    body = {
        "schema_version": 1,
        "status": "OUTCOME_BLIND_FIVE_MEMBER_COMPUTE_BENCHMARK_COMPLETE",
        "training_contract_digest": contract["training_contract_digest"],
        "candidate_id": contract["candidate"]["id"],
        "production_candidate": {
            "member_count": len(ensemble.members),
            "all_members_executed_per_window": True,
            "second_stage_distillation_executed": False,
            "trainable_parameters_per_member": contract["candidate"][
                "trainable_parameters_per_member"
            ],
            "trainable_parameters_total": contract["candidate"][
                "trainable_parameters_total"
            ],
            "parameter_bytes_total": int(
                sum(
                    parameter.numel() * parameter.element_size()
                    for parameter in ensemble.parameters()
                )
            ),
            "complete_five_member_path_cpu_batch1": full_timing,
            "observed_defer_score": full_output[0],
            "mechanical_route_result": full_output[1],
            "mechanical_audit_result": full_output[2],
        },
        "diagnostic_single_member": {
            "promotion_or_compute_gate_role": False,
            "cpu_batch1": member_timing,
            "observed_defer_score": member_output[0],
        },
        "startup": {
            "five_member_graph_construction_s": startup_s,
            "included_in_steady_state_latency": False,
        },
        "historical_cost_context": {
            "mean_avoidable_exact_path_cost_s": exact_cost_s,
            "five_member_mean_to_historical_exact_cost_ratio": (
                float(full_timing["mean_s"]) / exact_cost_s
            ),
            "role": "descriptive_only_not_a_compute_pass_gate",
        },
        "signal": {
            "source": benchmark["input"],
            "seed": input_seed,
            "sample_rate_hz": 4096,
            "duration_s": 32.0,
            "input_length": int(strain.size),
            "dtype": str(strain.dtype),
            "batch_size": 1,
        },
        "audit_probe": {
            "seed": audit_seed,
            "nominal_fraction": audit_fraction,
            "finite_cohort_fraction_claimed": False,
            "window_id": window_id,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "torch": torch.__version__,
            "torch_num_threads": torch.get_num_threads(),
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
            "automatic_mixed_precision": False,
            "device": "cpu",
        },
        "access_boundary": {
            "training_strain_or_teacher_labels": [],
            "threshold_search": [],
            "risk_calibration": [],
            "confirmation": [],
            "o4b": [],
        },
        "decision": {
            "artifact_integrity_can_pass": True,
            "compute_feasibility_gate_frozen": False,
            "candidate_promoted": False,
            "training_authorized": False,
            "routing_enabled": False,
        },
        "source_references": {
            "training_contract": {
                "path": "config/dante_light_prefilter_v7_training_contract.json",
                "sha256": file_sha256(
                    ROOT / "config/dante_light_prefilter_v7_training_contract.json"
                ),
            },
            "ensemble_implementation": contract["source_references"][
                "freeze_implementation"
            ],
            "benchmark_runner": {
                "path": "scripts/run_dante_light_prefilter_v7_compute_benchmark.py",
                "sha256": file_sha256(Path(__file__).resolve()),
            },
            "historical_exact_cost": {
                "path": historical_path.relative_to(ROOT).as_posix(),
                "sha256": file_sha256(historical_path),
            },
        },
    }
    payload = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(args.output.resolve(), payload)
    print(
        json.dumps(
            {
                "status": "PASS_ARTIFACT_INTEGRITY_ONLY",
                "output": str(args.output.resolve()),
                "artifact_digest": payload["artifact_digest"],
                "five_member_mean_ms": 1000.0 * float(full_timing["mean_s"]),
                "single_member_mean_ms": 1000.0 * float(member_timing["mean_s"]),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
