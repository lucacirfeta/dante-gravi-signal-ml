"""Verify the frozen v7 training contract and optional compute artifact."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training_freeze import (
    DEFAULT_CONTRACT,
    file_sha256,
    load_training_freeze,
    validate_training_freeze,
)


DEFAULT_ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_design"
    / "five_member_compute_benchmark_v7.json"
)


def _reference(root: Path, value: Mapping[str, Any], label: str) -> Path:
    if set(value) != {"path", "sha256"}:
        raise ContractError(f"v7 benchmark reference is malformed: {label}")
    relative = Path(str(value["path"]))
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(value["path"]):
        raise ContractError(f"v7 benchmark reference is not portable: {label}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError(f"v7 benchmark reference is absent: {label}")
    if file_sha256(path) != str(value["sha256"]):
        raise ContractError(f"v7 benchmark reference hash mismatch: {label}")
    return path


def _historical_values(payload: Any) -> list[float]:
    values: list[float] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "mean_avoidable_exact_path_cost_s":
                values.append(float(value))
            else:
                values.extend(_historical_values(value))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(_historical_values(value))
    return values


def verify_artifact(
    artifact: Mapping[str, Any], *, contract: Mapping[str, Any], root: Path
) -> dict[str, Any]:
    body = dict(artifact)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v7 benchmark artifact digest mismatch")
    if artifact.get("status") != "OUTCOME_BLIND_FIVE_MEMBER_COMPUTE_BENCHMARK_COMPLETE":
        raise ContractError("v7 benchmark status changed")
    if artifact.get("training_contract_digest") != contract["training_contract_digest"]:
        raise ContractError("v7 benchmark is not bound to the training freeze")
    references = {
        label: _reference(root, value, label)
        for label, value in artifact["source_references"].items()
    }
    production = artifact["production_candidate"]
    timing = production["complete_five_member_path_cpu_batch1"]
    required_stats = (
        "mean_s",
        "median_s",
        "p95_s",
        "maximum_s",
        "standard_deviation_s",
    )
    if (
        production["member_count"] != 5
        or production["all_members_executed_per_window"] is not True
        or production["second_stage_distillation_executed"] is not False
        or production["trainable_parameters_total"]
        != contract["candidate"]["trainable_parameters_total"]
        or int(timing["count"]) != int(contract["benchmark"]["timed_repetitions"])
        or any(not math.isfinite(float(timing[key])) or float(timing[key]) <= 0.0 for key in required_stats)
        or not 0.0 <= float(production["observed_defer_score"]) <= 1.0
    ):
        raise ContractError("v7 complete-ensemble benchmark is invalid")
    diagnostic = artifact["diagnostic_single_member"]
    if diagnostic["promotion_or_compute_gate_role"] is not False:
        raise ContractError("v7 single-member timing was given a decision role")
    access = artifact["access_boundary"]
    if any(access.values()):
        raise ContractError("v7 compute benchmark accessed an outcome")
    decision = artifact["decision"]
    if (
        decision["compute_feasibility_gate_frozen"] is not False
        or decision["candidate_promoted"] is not False
        or decision["training_authorized"] is not False
        or decision["routing_enabled"] is not False
    ):
        raise ContractError("v7 compute artifact makes an unauthorized decision")
    historical = json.loads(references["historical_exact_cost"].read_text(encoding="utf-8"))
    unique = sorted(set(_historical_values(historical)))
    recorded = float(artifact["historical_cost_context"]["mean_avoidable_exact_path_cost_s"])
    if len(unique) != 1 or recorded != unique[0]:
        raise ContractError("v7 historical exact-path cost does not reproduce")
    ratio = float(
        artifact["historical_cost_context"][
            "five_member_mean_to_historical_exact_cost_ratio"
        ]
    )
    if not math.isclose(ratio, float(timing["mean_s"]) / recorded, rel_tol=1e-12):
        raise ContractError("v7 benchmark cost ratio does not reproduce")
    return {
        "status": "PASS_ARTIFACT_INTEGRITY_ONLY",
        "artifact_digest": declared,
        "five_member_mean_ms": 1000.0 * float(timing["mean_s"]),
        "five_member_p95_ms": 1000.0 * float(timing["p95_s"]),
        "historical_exact_mean_ms": 1000.0 * recorded,
        "outcome_access": access,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--contract-only", action="store_true")
    args = parser.parse_args()
    contract = load_training_freeze(args.contract.resolve(), root=ROOT)
    result: dict[str, Any] = {
        "contract": validate_training_freeze(contract, root=ROOT)
    }
    if not args.contract_only:
        if not args.artifact.is_file():
            raise ContractError("v7 compute benchmark artifact is absent")
        artifact = json.loads(args.artifact.read_text(encoding="utf-8"))
        result["benchmark"] = verify_artifact(artifact, contract=contract, root=ROOT)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
