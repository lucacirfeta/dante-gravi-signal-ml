"""Cost accounting helpers for DANTE-Light feasibility studies.

This module deliberately contains no routing policy.  It keeps batch expected
compute and per-window tail latency separate so marginal quantiles are not
combined as if they were paired observations.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from src.dante_light.contracts import ContractError


def expected_batch_saving(
    *,
    reduction_fraction: float,
    prefilter_cost_s: Sequence[float],
    avoidable_exact_cost_s: Sequence[float],
) -> dict[str, float | str | bool]:
    """Estimate mean compute saving under an explicit independence assumption.

    Without paired routing decisions and exact-path timings, the identifiable
    quantity is ``r * E[S] - E[C]`` only if avoidable exact cost ``S`` is
    independent of rejection.  Tail latency is intentionally not estimated.
    """

    reduction = float(reduction_fraction)
    if not 0.0 <= reduction <= 1.0:
        raise ContractError("reduction_fraction must lie in [0, 1]")
    prefilter = np.asarray(prefilter_cost_s, dtype=np.float64)
    exact = np.asarray(avoidable_exact_cost_s, dtype=np.float64)
    if prefilter.size == 0 or exact.size == 0:
        raise ContractError("cost samples must be non-empty")
    if (
        not np.all(np.isfinite(prefilter))
        or not np.all(np.isfinite(exact))
        or np.any(prefilter < 0.0)
        or np.any(exact < 0.0)
    ):
        raise ContractError("cost samples must be finite and non-negative")
    mean_prefilter = float(np.mean(prefilter))
    mean_exact = float(np.mean(exact))
    expected_gross = reduction * mean_exact
    return {
        "reduction_fraction": reduction,
        "mean_prefilter_cost_s": mean_prefilter,
        "mean_avoidable_exact_cost_s": mean_exact,
        "expected_gross_saving_s": expected_gross,
        "expected_net_saving_s": expected_gross - mean_prefilter,
        "break_even_reduction_fraction": (
            mean_prefilter / mean_exact if mean_exact > 0.0 else float("inf")
        ),
        "assumes_rejection_independent_of_avoidable_cost": True,
        "tail_latency_identified": False,
        "tail_note": (
            "Paired per-window prefilter cost, routing decision, and exact-path "
            "cost are required; marginal p95 values cannot identify net p95."
        ),
    }


def paired_cost_accounting(
    *,
    rejected: Sequence[bool],
    prefilter_cost_s: Sequence[float],
    avoidable_exact_cost_s: Sequence[float],
) -> dict[str, float]:
    """Compute exact mean and quantiles when per-window samples are paired."""

    mask = np.asarray(rejected, dtype=bool)
    prefilter = np.asarray(prefilter_cost_s, dtype=np.float64)
    exact = np.asarray(avoidable_exact_cost_s, dtype=np.float64)
    if not (mask.size == prefilter.size == exact.size) or mask.size == 0:
        raise ContractError("paired cost arrays must have the same non-zero length")
    if (
        not np.all(np.isfinite(prefilter))
        or not np.all(np.isfinite(exact))
        or np.any(prefilter < 0.0)
        or np.any(exact < 0.0)
    ):
        raise ContractError("paired cost samples must be finite and non-negative")
    net_saving = mask.astype(np.float64) * exact - prefilter
    return {
        "reduction_fraction": float(np.mean(mask)),
        "mean_net_saving_s": float(np.mean(net_saving)),
        "p05_net_saving_s": float(np.quantile(net_saving, 0.05)),
        "p50_net_saving_s": float(np.quantile(net_saving, 0.50)),
        "p95_net_saving_s": float(np.quantile(net_saving, 0.95)),
    }
