"""Outcome-blind Phase-C fidelity power contract for DANTE-Light v6."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from scipy.optimize import brentq
from scipy.stats import norm

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "dante_light_prefilter_v6_phase_c_power.json"


def bonett_wright_lower(
    sample_spearman: float, *, n_blocks: int, confidence: float
) -> float:
    """One-sided Bonett-Wright Fisher-z lower confidence bound."""
    rho = float(sample_spearman)
    if not math.isfinite(rho) or not -1.0 < rho < 1.0:
        raise ContractError("sample Spearman must be finite and strictly inside (-1,1)")
    if isinstance(n_blocks, bool) or int(n_blocks) != n_blocks or n_blocks <= 3:
        raise ContractError("Bonett-Wright interval requires an integer n_blocks > 3")
    if not math.isfinite(float(confidence)) or not 0.5 < float(confidence) < 1.0:
        raise ContractError("confidence must be finite and in (0.5,1)")
    standard_error = math.sqrt((1.0 + rho * rho / 2.0) / (int(n_blocks) - 3))
    transformed = math.atanh(rho) - float(norm.ppf(confidence)) * standard_error
    return float(math.tanh(transformed))


def critical_observed_spearman(
    *,
    n_blocks: int,
    confidence: float,
    minimum_point_spearman: float,
    minimum_lower_bound: float,
) -> float:
    """Smallest observed rho satisfying both frozen fidelity conditions."""
    point = float(minimum_point_spearman)
    lower = float(minimum_lower_bound)
    if not -1.0 < lower < point < 1.0:
        raise ContractError("fidelity thresholds must satisfy -1 < lower < point < 1")
    root = brentq(
        lambda rho: bonett_wright_lower(
            rho, n_blocks=n_blocks, confidence=confidence
        )
        - lower,
        lower + 1e-12,
        1.0 - 1e-12,
    )
    return float(max(point, root))


def approximate_gate_pass_probability(
    *,
    n_blocks: int,
    confidence: float,
    minimum_point_spearman: float,
    minimum_lower_bound: float,
    true_spearman: float,
) -> float:
    """Prospective pass probability under the declared Fisher-z model."""
    true_rho = float(true_spearman)
    if not -1.0 < true_rho < 1.0:
        raise ContractError("true Spearman alternative must be inside (-1,1)")
    critical = critical_observed_spearman(
        n_blocks=n_blocks,
        confidence=confidence,
        minimum_point_spearman=minimum_point_spearman,
        minimum_lower_bound=minimum_lower_bound,
    )
    standard_error = math.sqrt(
        (1.0 + true_rho * true_rho / 2.0) / (int(n_blocks) - 3)
    )
    standardized = (math.atanh(critical) - math.atanh(true_rho)) / standard_error
    return float(norm.sf(standardized))


def load_power_contract(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-C power contract digest mismatch")
    if payload.get("status") != "FROZEN_PHASE_C_FIDELITY_GATE":
        raise ContractError("v6 Phase-C power contract is not frozen")
    if any(payload["outcome_access"].values()):
        raise ContractError("v6 Phase-C power freeze accessed an outcome")
    boundary = payload["scientific_boundary"]
    if any(value for key, value in boundary.items() if key != "does_not_establish"):
        raise ContractError("v6 Phase-C power freeze authorizes a forbidden action")
    sampling = payload["sampling_contract"]
    if sampling["independence_unit"] != "detector_gps_4096s_block":
        raise ContractError("v6 Phase-C independence unit changed")
    if int(sampling["windows_per_block"]) != 1:
        raise ContractError("v6 Phase-C power requires one observation per block")
    return payload


def analyze_power(contract: Mapping[str, Any]) -> dict[str, Any]:
    gate = contract["fidelity_gate"]
    model = contract["power_model"]
    sampling = contract["sampling_contract"]
    confidence = float(gate["confidence"])
    point = float(gate["minimum_point_spearman"])
    lower = float(gate["minimum_one_sided_lower_bound"])
    alternative = float(model["true_spearman_alternative"])
    rows = []
    for raw_n in model["candidate_block_counts"]:
        n_blocks = int(raw_n)
        rows.append(
            {
                "n_blocks": n_blocks,
                "critical_observed_spearman": critical_observed_spearman(
                    n_blocks=n_blocks,
                    confidence=confidence,
                    minimum_point_spearman=point,
                    minimum_lower_bound=lower,
                ),
                "lower_bound_at_true_alternative": bonett_wright_lower(
                    alternative, n_blocks=n_blocks, confidence=confidence
                ),
                "approximate_pass_probability_at_true_alternative": approximate_gate_pass_probability(
                    n_blocks=n_blocks,
                    confidence=confidence,
                    minimum_point_spearman=point,
                    minimum_lower_bound=lower,
                    true_spearman=alternative,
                ),
            }
        )
    frozen_n = int(sampling["blocks_per_detector"])
    frozen = next((row for row in rows if row["n_blocks"] == frozen_n), None)
    if frozen is None:
        raise ContractError("frozen Phase-C block count is absent from the power grid")
    if frozen["approximate_pass_probability_at_true_alternative"] < float(
        model["minimum_gate_pass_probability"]
    ):
        raise ContractError("frozen Phase-C block count misses the power target")
    body = {
        "schema_version": 1,
        "status": "FROZEN_PHASE_C_FIDELITY_POWER_VERIFIED",
        "analysis_id": contract["analysis_id"],
        "contract_digest": contract["contract_digest"],
        "sampling_contract": sampling,
        "fidelity_gate": gate,
        "power_model": model,
        "candidate_results": rows,
        "frozen_recommendation": frozen,
        "interpretation": {
            "power_is_model_based": True,
            "single_cell_power_only": True,
            "familywise_pass_probability_claimed": False,
            "reason": "Promotion requires every detector/replicate cell to pass; dependence across replicas is not assumed prospectively.",
        },
        "outcomes_accessed": [],
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}
