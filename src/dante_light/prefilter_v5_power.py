"""Outcome-blind power calculations for the frozen DANTE-Light v5 contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from scipy.stats import binom

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_evaluation import wilson_interval


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "dante_light_prefilter_v5_power_analysis.json"


def minimum_passing_successes(
    n: int, *, minimum_retention: float, minimum_wilson_lower: float, confidence: float
) -> int:
    if isinstance(n, bool) or int(n) != n or n <= 0:
        raise ContractError("sample size must be a positive integer")
    for value, name in (
        (minimum_retention, "minimum_retention"),
        (minimum_wilson_lower, "minimum_wilson_lower"),
        (confidence, "confidence"),
    ):
        if not math.isfinite(float(value)) or not 0.0 < float(value) <= 1.0:
            raise ContractError(f"{name} must be a finite fraction in (0,1]")
    for retained in range(int(n) + 1):
        lower, _ = wilson_interval(retained, int(n), float(confidence))
        if retained / int(n) >= float(minimum_retention) and lower >= float(minimum_wilson_lower):
            return retained
    raise ContractError(f"no passing retained count exists for n={n}")


def gate_pass_probability(
    n: int,
    *,
    true_retention: float,
    minimum_retention: float,
    minimum_wilson_lower: float,
    confidence: float,
) -> float:
    minimum = minimum_passing_successes(
        n,
        minimum_retention=minimum_retention,
        minimum_wilson_lower=minimum_wilson_lower,
        confidence=confidence,
    )
    return float(binom.sf(minimum - 1, int(n), float(true_retention)))


def worst_case_wilson_half_width(n: int, *, confidence: float) -> float:
    if isinstance(n, bool) or int(n) != n or n <= 0 or n % 2:
        raise ContractError("background n must be a positive even integer")
    lower, upper = wilson_interval(n // 2, n, confidence)
    return float(max(0.5 - lower, upper - 0.5))


def first_even_n_for_half_width(*, confidence: float, maximum_half_width: float) -> int:
    for n in range(2, 100_002, 2):
        if worst_case_wilson_half_width(n, confidence=confidence) <= maximum_half_width:
            return n
    raise ContractError("background precision target was not reached")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_power_config(path: str | Path = DEFAULT_CONFIG) -> tuple[dict[str, Any], dict[str, Any]]:
    source = Path(path)
    payload = _load_json(source)
    body = dict(payload)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v5 power contract digest mismatch")
    if payload.get("status") != "FROZEN_POWER_CONTRACT":
        raise ContractError("v5 power contract is not frozen")
    design = _load_json(ROOT / str(payload["design_path"]))
    if design.get("status") != "APPROVED_OUTCOME_BLIND_FREEZE_INPUT":
        raise ContractError("v5 design is not approved for outcome-blind freeze")
    return payload, design


def analyze_power(config: Mapping[str, Any], design: Mapping[str, Any]) -> dict[str, Any]:
    gate = design["gates"]["protected_retention"]
    target = design["power"]
    confidence = float(gate["wilson_confidence"])
    rows = []
    for raw_n in config["retention_sample_sizes"]:
        n = int(raw_n)
        minimum = minimum_passing_successes(
            n,
            minimum_retention=float(gate["minimum_point_retention"]),
            minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
            confidence=confidence,
        )
        rows.append(
            {
                "n": n,
                "minimum_retained": minimum,
                "minimum_observed_retention": minimum / n,
                "pass_probability_at_true_retention": gate_pass_probability(
                    n,
                    true_retention=float(target["true_retention_alternative"]),
                    minimum_retention=float(gate["minimum_point_retention"]),
                    minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
                    confidence=confidence,
                ),
            }
        )
    protected = design["partition_contract"]["protected_per_detector_stratum"]
    recommendations = {
        role: sorted({int(value) for value in counts.values()})
        for role, counts in protected.items()
    }
    for role, sizes in recommendations.items():
        for n in sizes:
            probability = gate_pass_probability(
                n,
                true_retention=float(target["true_retention_alternative"]),
                minimum_retention=float(gate["minimum_point_retention"]),
                minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
                confidence=confidence,
            )
            if probability < float(target["minimum_pass_probability"]):
                raise ContractError(f"frozen {role} sample size misses the power target")
    background_n = int(design["partition_contract"]["blocks_per_detector"]["confirmation"])
    minimum_background = first_even_n_for_half_width(
        confidence=confidence,
        maximum_half_width=float(target["background_maximum_wilson_half_width"]),
    )
    if background_n < minimum_background or background_n % 2:
        raise ContractError("frozen confirmation background misses its precision target")
    body = {
        "schema_version": 1,
        "status": "FROZEN_POWER_CONTRACT_VERIFIED",
        "analysis_id": config["analysis_id"],
        "config_digest": config["contract_digest"],
        "design_digest": canonical_json_sha256(design),
        "retention_gate": gate,
        "power_target": target,
        "candidate_results": rows,
        "frozen_recommendations": recommendations,
        "background_precision": {
            "frozen_n_per_detector_partition": background_n,
            "minimum_even_n_meeting_half_width": minimum_background,
            "frozen_n_worst_case_half_width": worst_case_wilson_half_width(
                background_n, confidence=confidence
            ),
        },
        "net_saving_gate_power": {
            "prospective_power_claimed": False,
            "reason": "No outcome-blind effect-size and block-dependence distribution was assumed; the positive lower-bound gate is prespecified without a fabricated power claim."
        },
        "outcomes_accessed": [],
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}
