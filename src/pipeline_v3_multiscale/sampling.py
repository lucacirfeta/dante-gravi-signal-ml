"""Guard-time-aware sampling of background center times.

The V3 leakage fix requires every pair of sampled centers to be separated
by at least guard = max(scales) + 64 s (audit finding B-4: the FPR test
scripts sampled centers with no mutual separation, so the guard-time
believed to be active was never enforced on the measurement path).
"""

from __future__ import annotations

import numpy as np

GUARD_TIME_S = 96.0  # max(scales)=32 + 64 s


def assert_threshold_run(thresholds: dict, target_run: str,
                         allow_cross_run: bool = False) -> None:
    """Refuse to apply thresholds calibrated on one run to data of another.

    The 2026-07 leakage investigation concluded that cross-run threshold
    transfer is the only channel with any residual excess (mild, tail-only,
    block-clustered). Production must recalibrate per run; only explicitly
    cross-run measurement scripts may pass allow_cross_run=True.
    """
    calib = thresholds.get("calibration_run")
    if calib is None:
        raise ValueError(
            "Thresholds file has no 'calibration_run' tag — recalibrate with "
            "the current micro_mdc_multiscale (post-audit) before use."
        )
    if calib.lower() != target_run.lower() and not allow_cross_run:
        raise RuntimeError(
            f"Cross-run threshold application refused: calibrated on {calib}, "
            f"target run {target_run}. Recalibrate on {target_run} or pass "
            "allow_cross_run=True in a measurement-only context."
        )


def respects_guard(t: float, accepted: list[float] | np.ndarray,
                   guard: float = GUARD_TIME_S) -> bool:
    """True if `t` is at least `guard` seconds away from every accepted center."""
    if len(accepted) == 0:
        return True
    arr = np.asarray(accepted, dtype=np.float64)
    return bool(np.min(np.abs(arr - t)) >= guard)


def sample_guarded_times(
    rng: np.random.Generator,
    low: float,
    high: float,
    n: int,
    guard: float = GUARD_TIME_S,
    max_attempts_factor: int = 50,
) -> np.ndarray:
    """Draw up to `n` center times in [low, high), pairwise separated by >= guard.

    Rejection sampling with a hard attempt budget; returns fewer than `n`
    if the interval cannot host them (caller must check).
    """
    accepted: list[float] = []
    attempts = 0
    budget = max(n * max_attempts_factor, 1000)
    while len(accepted) < n and attempts < budget:
        attempts += 1
        t = float(rng.uniform(low, high))
        if respects_guard(t, accepted, guard):
            accepted.append(t)
    return np.array(sorted(accepted))
