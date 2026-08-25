"""Non-gating power analysis for the proposed DANTE-Light v4 confirmation.

This module quantifies the operating characteristics of an already-specified
retention gate. It does not choose a scientific threshold, inspect cohort
outcomes, or freeze confirmation sample sizes.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from scipy.stats import binom

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_evaluation import wilson_interval


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POWER_CONFIG = ROOT / "config" / "dante_light_prefilter_v4_power_analysis.json"


def _fraction(value: Any, label: str, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ContractError(f"{label} must be a finite fraction")
    if positive and result <= 0.0:
        raise ContractError(f"{label} must be positive")
    return result


def minimum_passing_successes(
    n: int,
    *,
    minimum_retention: float,
    minimum_wilson_lower: float,
    confidence: float,
) -> int:
    """Return the smallest retained count that satisfies the full gate."""

    if isinstance(n, bool) or int(n) != n or n <= 0:
        raise ContractError("sample size must be a positive integer")
    retention = _fraction(minimum_retention, "minimum_retention")
    lower_limit = _fraction(minimum_wilson_lower, "minimum_wilson_lower")
    confidence_value = _fraction(confidence, "confidence", positive=True)
    for retained in range(int(n) + 1):
        lower, _ = wilson_interval(retained, int(n), confidence_value)
        if retained / int(n) >= retention and lower >= lower_limit:
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
    """Exact binomial probability that a fixed retention gate passes."""

    probability = _fraction(true_retention, "true_retention")
    minimum = minimum_passing_successes(
        n,
        minimum_retention=minimum_retention,
        minimum_wilson_lower=minimum_wilson_lower,
        confidence=confidence,
    )
    return float(binom.sf(minimum - 1, int(n), probability))


def worst_case_wilson_half_width(n: int, *, confidence: float) -> float:
    """Wilson half-width at p-hat=0.5 for an even binomial sample size."""

    if isinstance(n, bool) or int(n) != n or n <= 0 or n % 2:
        raise ContractError("background precision n must be a positive even integer")
    lower, upper = wilson_interval(
        n // 2, n, _fraction(confidence, "confidence", positive=True)
    )
    return float(max(0.5 - lower, upper - 0.5))


def first_even_n_for_half_width(
    *, confidence: float, maximum_half_width: float, maximum_n: int = 100_000
) -> int:
    target = _fraction(maximum_half_width, "maximum_half_width", positive=True)
    for n in range(2, int(maximum_n) + 1, 2):
        if worst_case_wilson_half_width(n, confidence=confidence) <= target:
            return n
    raise ContractError("background precision target not reached within maximum_n")


def first_n_for_power(
    *,
    true_retention: float,
    minimum_pass_probability: float,
    minimum_retention: float,
    minimum_wilson_lower: float,
    confidence: float,
    maximum_n: int = 100_000,
) -> int:
    target = _fraction(minimum_pass_probability, "minimum_pass_probability", positive=True)
    for n in range(1, int(maximum_n) + 1):
        try:
            probability = gate_pass_probability(
                n,
                true_retention=true_retention,
                minimum_retention=minimum_retention,
                minimum_wilson_lower=minimum_wilson_lower,
                confidence=confidence,
            )
        except ContractError as exc:
            if "no passing retained count exists" not in str(exc):
                raise
            continue
        if probability >= target:
            return n
    raise ContractError("power target not reached within maximum_n")


def load_power_config(path: str | Path = DEFAULT_POWER_CONFIG) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v4 power-analysis config digest mismatch")
    if payload.get("status") != "ANALYSIS_ONLY_NOT_FROZEN":
        raise ContractError("v4 power analysis cannot authorize a frozen protocol")
    parent = payload["source_v3_protocol"]
    parent_path = ROOT / str(parent["path"])
    if hashlib.sha256(parent_path.read_bytes()).hexdigest() != parent["sha256"]:
        raise ContractError("v4 power-analysis parent protocol hash mismatch")
    if not payload["interpretation"].get("does_not_freeze_confirmation_counts"):
        raise ContractError("power analysis must remain non-freezing")
    if not payload["interpretation"].get("does_not_open_protected_outcomes"):
        raise ContractError("power analysis must remain outcome blind")
    return payload


def analyze_power(payload: Mapping[str, Any]) -> dict[str, Any]:
    gate = payload["gate"]
    target = payload["power_target"]
    confidence = float(gate["wilson_confidence"])
    rows: list[dict[str, Any]] = []
    for raw_n in payload["candidate_sample_sizes"]:
        n = int(raw_n)
        minimum = minimum_passing_successes(
            n,
            minimum_retention=float(gate["minimum_retention"]),
            minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
            confidence=confidence,
        )
        lower, upper = wilson_interval(minimum, n, confidence)
        rows.append(
            {
                "n": n,
                "minimum_retained": minimum,
                "minimum_observed_retention": minimum / n,
                "minimum_passing_wilson_interval": [lower, upper],
                "pass_probability_at_true_retention": gate_pass_probability(
                    n,
                    true_retention=float(target["true_retention_alternative"]),
                    minimum_retention=float(gate["minimum_retention"]),
                    minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
                    confidence=confidence,
                ),
            }
        )
    background = payload["background_precision"]
    minimum_background = first_even_n_for_half_width(
        confidence=confidence,
        maximum_half_width=float(background["maximum_wilson_half_width_per_detector"]),
    )
    recommended_background = int(background["recommended_rounded_n_per_detector"])
    if recommended_background < minimum_background or recommended_background % 2:
        raise ContractError("rounded background recommendation misses its precision target")
    recommendations: dict[str, dict[str, Any]] = {}
    for name, raw_n in payload["recommended_for_author_review"].items():
        n = int(raw_n)
        minimum = minimum_passing_successes(
            n,
            minimum_retention=float(gate["minimum_retention"]),
            minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
            confidence=confidence,
        )
        probability = gate_pass_probability(
            n,
            true_retention=float(target["true_retention_alternative"]),
            minimum_retention=float(gate["minimum_retention"]),
            minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
            confidence=confidence,
        )
        if probability < float(target["minimum_pass_probability"]):
            raise ContractError(f"recommended sample size misses power target: {name}")
        recommendations[name] = {
            "n": n,
            "minimum_retained": minimum,
            "pass_probability_at_true_retention": probability,
        }
    result = {
        "schema_version": 1,
        "status": "ANALYSIS_ONLY_NOT_FROZEN",
        "analysis_id": payload["analysis_id"],
        "config_digest": payload["contract_digest"],
        "source_v3_protocol": payload["source_v3_protocol"],
        "gate": gate,
        "power_target": target,
        "candidate_results": rows,
        "first_n_meeting_power_target": first_n_for_power(
            true_retention=float(target["true_retention_alternative"]),
            minimum_pass_probability=float(target["minimum_pass_probability"]),
            minimum_retention=float(gate["minimum_retention"]),
            minimum_wilson_lower=float(gate["minimum_wilson_lower"]),
            confidence=confidence,
        ),
        "background_precision": {
            **background,
            "minimum_even_n_meeting_half_width": minimum_background,
            "recommended_n_half_width": worst_case_wilson_half_width(
                recommended_background, confidence=confidence
            ),
        },
        "recommended_for_author_review": payload["recommended_for_author_review"],
        "recommendation_operating_characteristics": recommendations,
        "interpretation": payload["interpretation"],
    }
    result["artifact_digest"] = canonical_json_sha256(result)
    return result
