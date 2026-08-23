#!/usr/bin/env python3
"""Fail-closed verification and compact summary for v4 feasibility artifacts.

This verifier checks provenance and numerical invariants. It cannot freeze a
v4 protocol, select a candidate, enable routing, or inspect protected outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_bank import greedy_farthest_bank


DEFAULT_ARTIFACT_ROOT = (
    ROOT / "artifacts/dante_light/prefilter_l4_v4_feasibility"
)
DEFAULT_SUMMARY = DEFAULT_ARTIFACT_ROOT / "feasibility_summary_v4.json"
CONFIG = ROOT / "config/dante_light_prefilter_v4_feasibility.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    if not path.is_file():
        raise ContractError(f"missing feasibility artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _require_boundary(payload: dict, *, expected_status: str) -> None:
    if payload.get("status") != expected_status:
        raise ContractError(f"unexpected artifact status: {payload.get('status')}")
    for key in ("routing_enabled", "candidate_selected", "protocol_frozen"):
        if payload.get(key) is not False:
            raise ContractError(f"forbidden feasibility state: {key}")
    access = payload.get("outcome_access", {})
    if any(access.get(key) is not False for key in ("development_labels", "reserved_confirmation", "o4b")):
        raise ContractError("a protected outcome was accessed")


def _verify_file_hash(reference: dict, expected_path: Path) -> None:
    raw_path = str(reference["path"])
    if "\\" in raw_path:
        raise ContractError("provenance paths must use repository-relative POSIX syntax")
    relative = Path(raw_path)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ContractError(f"provenance path must be repository-relative: {raw_path}")
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ContractError(f"provenance path escapes the repository: {raw_path}") from exc
    if path.resolve() != expected_path.resolve():
        raise ContractError(f"unexpected provenance path: {path}")
    if _sha256(path) != reference["sha256"]:
        raise ContractError(f"provenance hash mismatch: {path}")


def _verify_source_hashes(payload: dict, expected: dict[str, Path]) -> None:
    if set(payload["source_sha256"]) != set(expected):
        raise ContractError("source hash key mismatch")
    for key, path in expected.items():
        if _sha256(path) != payload["source_sha256"][key]:
            raise ContractError(f"source hash mismatch: {key}")


def _close(actual: float, expected: float, *, name: str) -> None:
    if not np.isclose(actual, expected, rtol=1e-12, atol=1e-15):
        raise ContractError(f"numerical mismatch: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--write-summary", type=Path, default=None)
    args = parser.parse_args()
    artifact_root = args.artifact_root.resolve()
    compute_path = artifact_root / "compute_feasibility_v4.json"
    bank_path = artifact_root / "mini_bank_coverage_v4.json"
    cost_path = artifact_root / "cost_accounting_v3_corrected.json"
    compute = _load(compute_path)
    bank = _load(bank_path)
    cost = _load(cost_path)

    _require_boundary(compute, expected_status="COMPLETE_FEASIBILITY_ONLY")
    _require_boundary(bank, expected_status="COMPLETE_FEASIBILITY_ONLY")
    _verify_file_hash(compute["config"], CONFIG)
    _verify_file_hash(bank["config"], CONFIG)
    _verify_source_hashes(
        compute,
        {
            "runner": ROOT / "scripts/run_dante_light_prefilter_v4_feasibility.py",
            "phase_module": ROOT / "src/dante_light/prefilter_v4_phase.py",
            "student_module": ROOT / "src/dante_light/prefilter_v4_student.py",
        },
    )
    _verify_source_hashes(
        bank,
        {
            "runner": ROOT / "scripts/run_dante_light_prefilter_v4_bank_coverage.py",
            "bank_module": ROOT / "src/dante_light/prefilter_v4_bank.py",
        },
    )

    if cost.get("status") != "COMPLETE_COST_AUDIT_ONLY" or cost.get("routing_changed") is not False:
        raise ContractError("cost audit boundary mismatch")
    boundary = cost["scientific_boundary"]
    if boundary.get("reserved_confirmation_accessed") is not False or boundary.get("o4b_accessed") is not False:
        raise ContractError("cost audit accessed protected outcomes")
    provenance = cost["provenance"]
    _verify_file_hash(
        provenance["screening"],
        ROOT / "artifacts/dante_light/prefilter_l4_v3/screening_summary_v3.json",
    )
    _verify_file_hash(
        provenance["benchmark"],
        ROOT / "benchmarks/dante_light_l1_score_only_shared.json",
    )
    if _sha256(ROOT / "scripts/audit_dante_light_prefilter_v3_cost.py") != provenance["runner_sha256"]:
        raise ContractError("cost runner hash mismatch")
    if _sha256(ROOT / "src/dante_light/prefilter_v4_cost.py") != provenance["cost_module_sha256"]:
        raise ContractError("cost module hash mismatch")

    accounting = cost["accounting"]
    mean_exact = sum(cost["avoidable_exact_cost_mean_s_by_stage"].values())
    _close(accounting["mean_avoidable_exact_cost_s"], mean_exact, name="mean avoidable cost")
    _close(
        accounting["expected_gross_saving_s"],
        accounting["reduction_fraction"] * mean_exact,
        name="expected gross saving",
    )
    _close(
        accounting["expected_net_saving_s"],
        accounting["expected_gross_saving_s"] - accounting["mean_prefilter_cost_s"],
        name="expected net saving",
    )
    if accounting.get("tail_latency_identified") is not False:
        raise ContractError("marginal timing data cannot identify net tail latency")

    matrix = np.ascontiguousarray(bank["match_matrix"]["values"], dtype=np.float64)
    if list(matrix.shape) != bank["match_matrix"]["shape"]:
        raise ContractError("match matrix shape mismatch")
    if hashlib.sha256(matrix.tobytes()).hexdigest() != bank["match_matrix"]["sha256"]:
        raise ContractError("match matrix byte hash mismatch")
    if not np.allclose(matrix, matrix.T, rtol=0.0, atol=1e-12):
        raise ContractError("match matrix is not symmetric")
    if not np.allclose(np.diag(matrix), 1.0, rtol=0.0, atol=1e-12):
        raise ContractError("match matrix diagonal is not unity")
    if np.any(matrix < 0.0) or np.any(matrix > 1.0):
        raise ContractError("match matrix leaves [0, 1]")
    config = _load(CONFIG)
    anchor = {key: float(value) for key, value in config["mini_bank_probe"]["anchor"].items()}
    anchors = [index for index, row in enumerate(bank["waveform_grid"]) if row == anchor]
    if len(anchors) != 1:
        raise ContractError("bank anchor mismatch")
    recomputed = greedy_farthest_bank(
        matrix,
        bank_sizes=config["mini_bank_probe"]["bank_sizes"],
        anchor_index=anchors[0],
    )["curve"]
    previous = -np.inf
    for size in config["mini_bank_probe"]["bank_sizes"]:
        key = str(size)
        for metric in ("minimum_match", "p05_match", "median_match", "mean_match"):
            _close(bank["coverage"]["curve"][key][metric], recomputed[key][metric], name=f"bank {key} {metric}")
        current = float(recomputed[key]["minimum_match"])
        if current < previous:
            raise ContractError("bank minimum coverage is not monotone")
        previous = current

    phase = compute["phase_probe"]
    ordered = phase["synthetic_features"]["ordered_chirp"]
    scrambled = phase["phase_scrambled_control_distribution"]
    if ordered["phase_frequency_time_spearman"] <= scrambled["phase_frequency_time_spearman"]["p95"]:
        raise ContractError("ordered chirp does not exceed scrambled-control p95")
    if ordered["phase_cubic_circular_residual"] >= scrambled["phase_cubic_circular_residual"]["median"]:
        raise ContractError("ordered chirp phase residual is not lower than scrambled median")

    curve = bank["coverage"]["curve"]
    kernel = bank["kernel_benchmark"]["results"]
    student = compute["student_probe"]["benchmarks"]
    summary = {
        "schema_version": 1,
        "status": "FEASIBILITY_COMPLETE_AWAITING_SCIENTIFIC_DECISION",
        "routing_enabled": False,
        "candidate_selected": False,
        "protocol_frozen": False,
        "outcome_access": {
            "development_labels": False,
            "reserved_confirmation": False,
            "o4b": False,
        },
        "cost_accounting": {
            "reduction_fraction": accounting["reduction_fraction"],
            "mean_prefilter_cost_ms": 1e3 * accounting["mean_prefilter_cost_s"],
            "mean_avoidable_exact_cost_ms": 1e3 * accounting["mean_avoidable_exact_cost_s"],
            "expected_gross_saving_ms_per_window": 1e3 * accounting["expected_gross_saving_s"],
            "expected_net_saving_ms_per_window": 1e3 * accounting["expected_net_saving_s"],
            "break_even_reduction_fraction": accounting["break_even_reduction_fraction"],
            "assumes_rejection_independent_of_avoidable_cost": True,
            "tail_latency_identified": False,
        },
        "phase_probe": {
            "ordered_chirp_spearman": ordered["phase_frequency_time_spearman"],
            "scrambled_spearman_p95": scrambled["phase_frequency_time_spearman"]["p95"],
            "ordered_chirp_cubic_residual": ordered["phase_cubic_circular_residual"],
            "scrambled_cubic_residual_median": scrambled["phase_cubic_circular_residual"]["median"],
            "runtime_mean_ms": 1e3 * phase["timing"]["mean_s"],
            "scope": "ideal synthetic behavior and runtime only",
        },
        "mini_bank_probe": {
            "grid_size": len(bank["waveform_grid"]),
            "coverage_by_bank_size": {
                key: {
                    "minimum_match": curve[key]["minimum_match"],
                    "p05_match": curve[key]["p05_match"],
                    "median_match": curve[key]["median_match"],
                    "kernel_p95_ms": 1e3 * kernel[key]["p95_s"],
                }
                for key in curve
            },
            "minimal_match_threshold_defined": False,
            "scope": "illustrative aligned-spin in-family grid only",
        },
        "student_compute_probe": {
            "raw_1d_parameters": student["cpu"]["raw_1d_depthwise_proxy"]["trainable_parameters"],
            "raw_1d_cpu_batch1_mean_ms": 1e3 * student["cpu"]["raw_1d_depthwise_proxy"]["timings_by_batch"]["1"]["transfer_and_inference"]["mean_s"],
            "complex_stft_parameters": student["cpu"]["complex_stft_2d_proxy"]["trainable_parameters"],
            "complex_stft_cpu_preprocess_mean_ms": 1e3 * student["complex_stft_preprocessing_cpu"]["mean_s"],
            "complex_stft_cpu_batch1_inference_mean_ms": 1e3 * student["cpu"]["complex_stft_2d_proxy"]["timings_by_batch"]["1"]["transfer_and_inference_excluding_stft"]["mean_s"],
            "scope": "random-weight compute only; no learnability or fidelity evidence",
        },
        "verified_artifact_sha256": {
            "compute": _sha256(compute_path),
            "mini_bank": _sha256(bank_path),
            "cost_accounting": _sha256(cost_path),
            "config": _sha256(CONFIG),
        },
    }
    output = args.write_summary.resolve() if args.write_summary else None
    if output is not None:
        _atomic_json(output, summary)
    print(json.dumps({"status": "PASS", "summary": str(output) if output else None}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
