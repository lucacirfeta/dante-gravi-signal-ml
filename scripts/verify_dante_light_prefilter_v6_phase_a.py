#!/usr/bin/env python3
"""Fail-closed verification for DANTE-Light v6 Phase-A compute evidence."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_student import trainable_parameter_count
from src.dante_light.prefilter_v6_phase_a import (
    aggregation_contract,
    build_candidate,
    file_sha256,
    load_phase_a_contract,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v6_phase_a.json"
DEFAULT_ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "phase_a_compute_feasibility_v6.json"
)


def _finite_positive(value: object, name: str, *, allow_zero: bool = False) -> float:
    converted = float(value)
    if not math.isfinite(converted) or converted < 0 or (not allow_zero and converted == 0):
        raise ContractError(f"invalid Phase-A metric: {name}")
    return converted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    args = parser.parse_args()

    config_path = args.config.resolve()
    artifact_path = args.artifact.resolve()
    contract = load_phase_a_contract(config_path, root=ROOT)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-A artifact digest mismatch")
    if payload.get("status") != "PHASE_A_COMPUTE_FEASIBILITY_COMPLETE":
        raise ContractError("v6 Phase-A artifact is incomplete")
    if payload.get("contract_digest") != contract["contract_digest"]:
        raise ContractError("v6 Phase-A artifact uses the wrong contract")
    if payload.get("scientific_boundary") != contract["scientific_boundary"]:
        raise ContractError("v6 Phase-A scientific boundary mismatch")
    if any(payload.get("outcome_access", {}).get(key) != [] for key in (
        "teacher_scores", "morphology_labels", "development", "confirmation", "o4b"
    )):
        raise ContractError("v6 Phase-A artifact records forbidden outcome access")
    decision = payload.get("decision", {})
    if any(decision.get(key) is not False for key in (
        "candidate_selected", "training_authorized", "routing_enabled"
    )):
        raise ContractError("v6 Phase-A artifact makes a forbidden promotion")

    teacher_reference = contract["parent_references"]["teacher_contract"]
    teacher = json.loads((ROOT / teacher_reference["path"]).read_text(encoding="utf-8"))
    aggregation = aggregation_contract(contract, teacher)
    observed_aggregation = payload["aggregation"]
    if int(observed_aggregation["teacher_top_k"]) != aggregation.teacher_top_k:
        raise ContractError("v6 Phase-A teacher top-k mismatch")
    if int(observed_aggregation["teacher_instance_count"]) != aggregation.teacher_instance_count:
        raise ContractError("v6 Phase-A teacher instance-count mismatch")
    if not math.isclose(
        float(observed_aggregation["retained_fraction"]),
        aggregation.retained_fraction,
        rel_tol=0.0,
        abs_tol=1e-15,
    ):
        raise ContractError("v6 Phase-A retained-fraction mismatch")
    if observed_aggregation.get("centroid_count_not_used_as_denominator") is not True:
        raise ContractError("v6 Phase-A artifact confuses centroids with patch instances")

    signal = payload["signal"]
    expected_length = int(
        teacher["representation"]["sample_rate_hz"]
        * teacher["representation"]["analysis_duration_s"]
    )
    if int(signal["input_length"]) != expected_length or signal.get("source") != (
        "deterministic_standard_normal_synthetic"
    ):
        raise ContractError("v6 Phase-A signal contract mismatch")

    expected_candidates = {str(row["id"]): row for row in contract["candidate_matrix"]}
    if set(payload["results"]) != set(expected_candidates):
        raise ContractError("v6 Phase-A candidate matrix mismatch")
    device_sets: set[tuple[str, ...]] = set()
    for candidate_id, candidate in expected_candidates.items():
        result = payload["results"][candidate_id]
        if result["candidate_contract"] != candidate:
            raise ContractError(f"candidate contract mismatch: {candidate_id}")
        model = build_candidate(candidate, aggregation)
        static = result["static"]
        if int(static["trainable_parameters"]) != trainable_parameter_count(model):
            raise ContractError(f"parameter count mismatch: {candidate_id}")
        for key in ("parameter_bytes", "input_bytes", "leaf_activation_bytes_per_forward"):
            _finite_positive(static[key], f"{candidate_id}.{key}")
        local_instances = static["student_instance_count"]
        local_k = static["student_top_k"]
        if candidate_id == "raw_v5_global_average":
            if local_instances is not None or local_k is not None:
                raise ContractError("unchanged v5 baseline acquired a local pooling contract")
        else:
            if int(local_instances) != 256:
                raise ContractError(f"unexpected student instance count: {candidate_id}")
            if int(local_k) != aggregation.student_top_k(int(local_instances)):
                raise ContractError(f"student top-k mismatch: {candidate_id}")
        devices = result["devices"]
        if not devices:
            raise ContractError(f"candidate has no device benchmark: {candidate_id}")
        device_sets.add(tuple(sorted(devices)))
        for device_name, metrics in devices.items():
            timing = metrics["inference_only"]
            for key in ("mean_s", "median_s", "p95_s", "maximum_s"):
                _finite_positive(timing[key], f"{candidate_id}.{device_name}.{key}")
            if int(timing["count"]) < 1:
                raise ContractError("empty Phase-A timing sample")
            transfer = metrics["host_to_device_and_inference"]
            peak = metrics["cuda_peak_incremental_allocated_bytes"]
            if device_name == "cuda":
                if transfer is None or peak is None:
                    raise ContractError("CUDA cost or memory evidence is missing")
                _finite_positive(peak, f"{candidate_id}.cuda.peak", allow_zero=True)
            elif transfer is not None or peak is not None:
                raise ContractError("CPU result contains CUDA-only evidence")
    if len(device_sets) != 1:
        raise ContractError("candidates were benchmarked on different device sets")

    for name, reference in payload["source_references"].items():
        relative = Path(reference["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError(f"non-portable source reference: {name}")
        source = ROOT / relative
        if not source.is_file() or file_sha256(source) != reference["sha256"]:
            raise ContractError(f"v6 Phase-A source mismatch: {name}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "artifact": artifact_path.relative_to(ROOT).as_posix(),
                "artifact_digest": declared,
                "candidates": len(expected_candidates),
                "devices": list(device_sets.pop()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
