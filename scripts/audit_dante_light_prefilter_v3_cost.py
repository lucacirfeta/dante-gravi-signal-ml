#!/usr/bin/env python3
"""Correct mean-vs-mean cost accounting for the frozen v3 development run.

Only the already-open v3 development timing fields are consumed.  The script
does not read the reserved confirmation partition or O4b outcomes and cannot
change any routing result.
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
from src.dante_light.prefilter_v4_cost import expected_batch_saving


DEFAULT_SCREENING = (
    ROOT / "artifacts/dante_light/prefilter_l4_v3/screening_summary_v3.json"
)
DEFAULT_BENCHMARK = ROOT / "benchmarks/dante_light_l1_score_only_shared.json"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v4_feasibility"
    / "cost_accounting_v3_corrected.json"
)


ROLE_FILES = {
    "background": "background/background_feature_ledger_v3_development.json",
    "injection": "injection/injection_feature_ledger_v3_development.json",
    "known_glitch": "known/known_glitch_feature_ledger_v3_development.json",
    "robust_candidate": "robust/robust_candidate_feature_ledger_v3_development.json",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError(f"provenance input is outside the repository: {path}") from exc


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger-root", type=Path, required=True)
    parser.add_argument("--screening", type=Path, default=DEFAULT_SCREENING)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    screening_path = args.screening.resolve()
    benchmark_path = args.benchmark.resolve()
    screening = json.loads(screening_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    root = args.ledger_root.resolve()
    expected_hashes = screening["external_evidence"]["ledger_file_sha256_by_role"]
    feature_costs: list[float] = []
    actual_hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    row_hashes: dict[str, str] = {}
    for role, relative in ROLE_FILES.items():
        manifest_path = root / relative
        actual_hashes[role] = _sha256(manifest_path)
        if actual_hashes[role] != expected_hashes[role]:
            raise ContractError(f"v3 {role} ledger provenance mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("role") != role or manifest.get("status") != "complete":
            raise ContractError(f"v3 {role} ledger manifest contract mismatch")
        path = manifest_path.parent / str(manifest["rows_path"])
        row_hashes[role] = _sha256(path)
        if row_hashes[role] != manifest.get("rows_sha256"):
            raise ContractError(f"v3 {role} row ledger provenance mismatch")
        count = 0
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                # Deliberately consume only the timing field.  Labels, feature
                # values, scores and decisions are not used by this audit.
                row = json.loads(line)
                feature_costs.append(float(row["timings"]["feature_extraction_s"]))
                count += 1
        counts[role] = count
        if count != int(manifest["row_count"]):
            raise ContractError(f"v3 {role} row count mismatch")
    stage = benchmark["stage_timings"]
    avoidable_names = ("q_transform_s", "rendering_s", "score_total_s")
    avoidable_means = {
        name: float(stage[name]["total_s"]) / int(stage[name]["count"])
        for name in avoidable_names
    }
    mean_avoidable = float(sum(avoidable_means.values()))
    reduction = float(
        screening["candidate_results"]["signed_plus_ridge"][
            "oof_development_background_call_reduction"
        ]
    )
    accounting = expected_batch_saving(
        reduction_fraction=reduction,
        prefilter_cost_s=feature_costs,
        avoidable_exact_cost_s=[mean_avoidable],
    )
    costs = np.asarray(feature_costs, dtype=np.float64)
    payload = {
        "schema_version": 1,
        "status": "COMPLETE_COST_AUDIT_ONLY",
        "routing_changed": False,
        "scientific_boundary": {
            "source_partition": "already-open frozen v3 development only",
            "reserved_confirmation_accessed": False,
            "o4b_accessed": False,
            "non_timing_fields_used": False,
        },
        "accounting": accounting,
        "prefilter_cost_distribution_s": {
            "count": int(costs.size),
            "mean": float(np.mean(costs)),
            "median": float(np.median(costs)),
            "p95": float(np.quantile(costs, 0.95)),
            "maximum": float(np.max(costs)),
        },
        "avoidable_exact_cost_mean_s_by_stage": avoidable_means,
        "marginal_tail_diagnostic_only": {
            "sum_of_component_p95_s": float(
                sum(float(stage[name]["p95_s"]) for name in avoidable_names)
            ),
            "prefilter_p95_s": float(np.quantile(costs, 0.95)),
            "warning": (
                "These marginal quantiles are not paired and must not be combined "
                "into a net-p95 claim."
            ),
        },
        "provenance": {
            "screening": {
                "path": _repo_relative(screening_path),
                "sha256": _sha256(screening_path),
            },
            "benchmark": {
                "path": _repo_relative(benchmark_path),
                "sha256": _sha256(benchmark_path),
            },
            "ledger_root": str(root),
            "ledger_sha256_by_role": actual_hashes,
            "row_ledger_sha256_by_role": row_hashes,
            "ledger_count_by_role": counts,
            "runner_sha256": _sha256(Path(__file__).resolve()),
            "cost_module_sha256": _sha256(
                ROOT / "src/dante_light/prefilter_v4_cost.py"
            ),
        },
    }
    _atomic_json(args.output.resolve(), payload)
    print(json.dumps({"status": payload["status"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
