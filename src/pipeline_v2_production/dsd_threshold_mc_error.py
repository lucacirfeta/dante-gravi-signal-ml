"""Monte Carlo error of the DSD block-bootstrap thresholds.

The DSD thresholds are the 2.5th and 97.5th percentiles of the $P_{99}$
distribution over $B=1000$ moving-block bootstrap replicas of the native
background scores (``block_bootstrap_p99_ci`` in ``aggregate_report.py``). Both
manuscripts assert that $B=1000$ keeps the Monte Carlo error on
$\\tau_{\\mathrm{lo}}, \\tau_{\\mathrm{hi}}$ "well below the bin width of the
underlying score histogram" -- an argument, never a measurement.

This measures it. The bootstrap is repeated ``--reps`` times with independent
seeds; the spread of the resulting thresholds *across seeds* is the Monte Carlo
error, i.e. the part of the threshold that would move if the analysis were
re-run unchanged. It is distinct from the bootstrap CI width itself, which
estimates sampling variability of the data.

Two reference scales are reported alongside it:

* the CI width $\\tau_{\\mathrm{hi}} - \\tau_{\\mathrm{lo}}$ -- MC error must be
  small against this or the interval is mostly noise;
* the histogram bin width, both Freedman--Diaconis and the plain 50-bin rule,
  since that is the comparison the manuscripts actually claim.

Usage
-----
    python -m src.pipeline_v2_production.dsd_threshold_mc_error --reps 200

Writes ``data/production/aggregated/dsd_threshold_mc_error.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)

AGG_DIR = Path("data/production/aggregated")
B_PRODUCTION = 1000
P_TAIL = 99.0


def _bootstrap_p99(scores: np.ndarray, B: int, seed: int) -> np.ndarray:
    """`B` moving-block bootstrap replicas of the P99, vectorised.

    Same scheme as production: block length ``b = n^(1/3)``, ``ceil(n / b)``
    blocks drawn with replacement from uniformly random starts, concatenated
    and truncated back to ``n``.
    """
    n = len(scores)
    b = max(1, int(n ** (1 / 3)))
    num_blocks = int(np.ceil(n / b))

    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - b + 1, size=(B, num_blocks))
    idx = starts[:, :, None] + np.arange(b)[None, None, :]
    boot = scores[idx.reshape(B, -1)[:, :n]]
    return np.percentile(boot, P_TAIL, axis=1)


def measure(scores: np.ndarray, reps: int, B: int = B_PRODUCTION) -> dict:
    """Spread of the CI endpoints across independent bootstrap runs."""
    lo = np.empty(reps)
    hi = np.empty(reps)
    for r in range(reps):
        p99s = _bootstrap_p99(scores, B, seed=1000 + r)
        lo[r] = np.percentile(p99s, 2.5)
        hi[r] = np.percentile(p99s, 97.5)

    # Reference scales.
    q75, q25 = np.percentile(scores, [75, 25])
    fd_width = 2 * (q75 - q25) / len(scores) ** (1 / 3)
    bin50_width = (scores.max() - scores.min()) / 50

    ci_width = float(hi.mean() - lo.mean())
    return {
        "n_background": int(len(scores)),
        "block_length": int(max(1, int(len(scores) ** (1 / 3)))),
        "B": int(B),
        "reps": int(reps),
        "tau_lo": {"mean": float(lo.mean()), "mc_std": float(lo.std(ddof=1)),
                   "min": float(lo.min()), "max": float(lo.max())},
        "tau_hi": {"mean": float(hi.mean()), "mc_std": float(hi.std(ddof=1)),
                   "min": float(hi.min()), "max": float(hi.max())},
        "ci_width": ci_width,
        "hist_bin_width_freedman_diaconis": float(fd_width),
        "hist_bin_width_50bin": float(bin50_width),
        "mc_std_over_ci_width": float(max(lo.std(ddof=1), hi.std(ddof=1)) / ci_width),
        "mc_std_over_fd_bin": float(max(lo.std(ddof=1), hi.std(ddof=1)) / fd_width),
        "mc_std_over_50bin": float(max(lo.std(ddof=1), hi.std(ddof=1)) / bin50_width),
    }


def run(run_name: str = "O4a", reps: int = 200, B: int = B_PRODUCTION) -> dict:
    """Measure the Monte-Carlo error on the DSD thresholds from stored native
    background scores. Requires ``background_scores_native_{det}_{run}.npy``,
    written by ``aggregate-report``'s native-threshold calibration."""
    out: dict = {"run": run_name, "detectors": {}}
    for det in ("H1", "L1"):
        path = AGG_DIR / f"background_scores_native_{det}_{run_name}.npy"
        if not path.exists():
            logger.error(f"{path} missing — cannot measure {det}. Run "
                         "aggregate-report first to produce the native scores.")
            continue
        scores = np.load(path).astype(float)
        logger.info(f"[{det}] {len(scores)} background scores, {reps} runs of B={B}")
        res = measure(scores, reps=reps, B=B)
        out["detectors"][det] = res
        logger.info(
            f"[{det}] tau_lo={res['tau_lo']['mean']:.5f}+/-{res['tau_lo']['mc_std']:.5f}  "
            f"tau_hi={res['tau_hi']['mean']:.5f}+/-{res['tau_hi']['mc_std']:.5f}  "
            f"MC/FD-bin={res['mc_std_over_fd_bin']:.3f}"
        )

    dest = AGG_DIR / "dsd_threshold_mc_error.json"
    dest.write_text(json.dumps(out, indent=2))
    logger.info(f"Wrote {dest}")
    record_environment(AGG_DIR, "dsd_threshold_mc_error")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--reps", type=int, default=200,
                   help="Independent bootstrap runs used to estimate the spread.")
    p.add_argument("--B", type=int, default=B_PRODUCTION,
                   help="Replicas per bootstrap run (production value: 1000).")
    args = p.parse_args()
    run(args.run, reps=args.reps, B=args.B)


if __name__ == "__main__":
    main()
