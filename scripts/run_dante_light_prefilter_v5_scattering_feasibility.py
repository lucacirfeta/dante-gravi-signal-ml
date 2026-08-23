#!/usr/bin/env python3
"""Run or verify the WSL-only, outcome-blind v5 scattering feasibility audit."""

from __future__ import annotations

import argparse
import gc
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np
import scipy
import torch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_protocol import repository_reference
from src.dante_light.prefilter_v5_scattering import (
    ARTIFACT_STATUS,
    array_sha256,
    instantiate_scattering,
    load_config,
    sha256_path,
    synthetic_probes,
    timing_summary,
    validate_artifact,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v5_scattering_feasibility.json"
DEFAULT_OUTPUT = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/scattering_feasibility_v5.json"


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _require_wsl() -> None:
    if platform.system() != "Linux" or "microsoft" not in platform.release().lower():
        raise ContractError("scattering execution is restricted to the approved WSL runtime")


def _wheel_provenance(config: dict[str, Any], wheel_path: Path) -> dict[str, Any]:
    expected = config["dependency"]["wheel"]
    if not wheel_path.is_file() or wheel_path.name != expected["filename"]:
        raise ContractError("approved Kymatio wheel is unavailable")
    digest = sha256_path(wheel_path)
    if digest != expected["sha256"]:
        raise ContractError("Kymatio wheel SHA256 mismatch")
    return dict(expected)


def _output_record(values: torch.Tensor) -> dict[str, Any]:
    array = values.detach().cpu().numpy()
    return {
        "shape": list(array.shape),
        "coefficient_count": int(array.size),
        "dtype": str(array.dtype),
        "all_finite": bool(np.all(np.isfinite(array))),
        "sha256": array_sha256(array),
    }


def build(config_path: Path, output_path: Path, wheel_path: Path) -> dict[str, Any]:
    _require_wsl()
    config = load_config(config_path)
    wheel = _wheel_provenance(config, wheel_path)
    package_metadata = importlib.metadata.metadata("kymatio")
    package_version = package_metadata["Version"]
    if package_version != config["dependency"]["version"]:
        raise ContractError("imported Kymatio version differs from the approved wheel")
    if package_metadata["License"] != config["dependency"]["license"]:
        raise ContractError("installed Kymatio license metadata differs from the contract")

    probes = synthetic_probes(config)
    model, import_status = instantiate_scattering(config)
    tensors = {
        name: torch.from_numpy(values).reshape(1, -1).contiguous()
        for name, values in probes.items()
    }
    determinism: dict[str, Any] = {}
    repeats = int(config["benchmark"]["determinism_repetitions"])
    with torch.inference_mode():
        for name, tensor in tensors.items():
            records = [_output_record(model(tensor)) for _ in range(repeats)]
            determinism[name] = {
                "input_sha256": array_sha256(probes[name]),
                "output_shape": records[0]["shape"],
                "coefficient_count": records[0]["coefficient_count"],
                "output_dtype": records[0]["dtype"],
                "all_finite": all(record["all_finite"] for record in records),
                "output_sha256_by_repetition": [record["sha256"] for record in records],
            }

    benchmark_tensor = tensors["white_noise"]
    warmup = int(config["benchmark"]["warmup_repetitions"])
    with torch.inference_mode():
        for _ in range(warmup):
            model(benchmark_tensor)
            benchmark_tensor.clone()

    ledger: list[dict[str, Any]] = []
    gc_enabled = gc.isenabled()
    gc.disable()
    try:
        with torch.inference_mode():
            for index in range(int(config["benchmark"]["repetitions"])):
                scattering_first = index % 2 == 0
                if scattering_first:
                    began = time.perf_counter_ns()
                    model(benchmark_tensor)
                    scattering_ns = time.perf_counter_ns() - began
                    began = time.perf_counter_ns()
                    benchmark_tensor.clone()
                    control_ns = time.perf_counter_ns() - began
                    order = "scattering_first"
                else:
                    began = time.perf_counter_ns()
                    benchmark_tensor.clone()
                    control_ns = time.perf_counter_ns() - began
                    began = time.perf_counter_ns()
                    model(benchmark_tensor)
                    scattering_ns = time.perf_counter_ns() - began
                    order = "control_first"
                ledger.append(
                    {
                        "index": index,
                        "order": order,
                        "scattering_s": scattering_ns / 1_000_000_000.0,
                        "control_s": control_ns / 1_000_000_000.0,
                    }
                )
    finally:
        if gc_enabled:
            gc.enable()

    scattering_samples = [float(row["scattering_s"]) for row in ledger]
    control_samples = [float(row["control_s"]) for row in ledger]
    paired_deltas = [left - right for left, right in zip(scattering_samples, control_samples)]
    body = {
        "schema_version": 1,
        "audit_id": config["audit_id"],
        "status": ARTIFACT_STATUS,
        "candidate_selected": False,
        "protocol_frozen": False,
        "routing_enabled": False,
        "eligibility_decision": "DEFERRED_TO_SEPARATE_SCIENTIFIC_CHECKPOINT",
        "outcome_access": {
            "development_outcomes": [],
            "reserved_confirmation": [],
            "o4b": [],
            "teacher_scores": [],
        },
        "source_references": {
            "config": repository_reference(ROOT, config_path),
            "implementation": repository_reference(
                ROOT, ROOT / "src/dante_light/prefilter_v5_scattering.py"
            ),
            "runner": repository_reference(ROOT, Path(__file__).resolve()),
        },
        "dependency": {
            **config["dependency"],
            "wheel": wheel,
            "imported_version": package_version,
            "installed_metadata_license": package_metadata["License"],
            "import_status": import_status,
        },
        "runtime": {
            "execution_scope": "WSL_ONLY",
            "platform": platform.platform(),
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "torch": torch.__version__,
            "torch_cpu_threads": int(torch.get_num_threads()),
            "device": "cpu",
            "batch_size": 1,
        },
        "transform": config["transform"],
        "input_contract": config["input_contract"],
        "determinism": {
            "criterion": "bitwise_equal_repeated_cpu_outputs",
            "rtol": config["benchmark"]["determinism_rtol"],
            "atol": config["benchmark"]["determinism_atol"],
            "all_repetitions_bitwise_equal": all(
                len(set(record["output_sha256_by_repetition"])) == 1
                for record in determinism.values()
            ),
            "probes": determinism,
        },
        "timing": {
            "clock": "time.perf_counter_ns",
            "garbage_collection_disabled_during_measurement": True,
            "warmup_repetitions": warmup,
            "paired_batch1_cpu_ledger": ledger,
            "summary": {
                "scattering": timing_summary(scattering_samples),
                "control": timing_summary(control_samples),
                "paired_delta": timing_summary(paired_deltas),
            },
        },
        "interpretation_boundary": {
            "establishes": [
                "output dimension on deterministic outcome-blind inputs",
                "same-runtime CPU determinism",
                "batch-1 CPU cost on the recorded WSL runtime",
                "current dependency compatibility behavior",
            ],
            "does_not_establish": [
                "teacher fidelity",
                "morphology retention",
                "background reduction",
                "cross-platform transform support",
                "routing readiness",
                "scientific independence from exact DANTE",
            ],
            "maintenance_risk_must_be_reassessed_before_protocol_entry": True,
        },
    }
    artifact = {**body, "artifact_digest": canonical_json_sha256(body)}
    _write_json_atomic(output_path, artifact)
    validate_artifact(artifact, config=config)
    return artifact


def verify(config_path: Path, output_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    validate_artifact(artifact, config=config)
    expected = {
        "config": config_path,
        "implementation": ROOT / "src/dante_light/prefilter_v5_scattering.py",
        "runner": Path(__file__).resolve(),
    }
    for key, path in expected.items():
        if artifact["source_references"][key] != repository_reference(ROOT, path):
            raise ContractError(f"scattering source reference mismatch: {key}")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            artifact = verify(args.config.resolve(), args.output.resolve())
        else:
            if args.wheel is None:
                raise ContractError("--wheel is required for an evidence build")
            artifact = build(args.config.resolve(), args.output.resolve(), args.wheel.resolve())
    except (ContractError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    summary = {
        "status": artifact["status"],
        "artifact_digest": artifact["artifact_digest"],
        "output_shape": artifact["determinism"]["probes"]["white_noise"]["output_shape"],
        "coefficient_count": artifact["determinism"]["probes"]["white_noise"]["coefficient_count"],
        "mean_batch1_cpu_ms": 1000.0 * artifact["timing"]["summary"]["scattering"]["mean_s"],
        "p95_batch1_cpu_ms": 1000.0 * artifact["timing"]["summary"]["scattering"]["p95_s"],
        "candidate_selected": False,
        "protected_outcomes_used": [],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
