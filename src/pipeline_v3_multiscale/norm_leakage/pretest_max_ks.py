"""Pre-test 1 — can the hypothesis be killed for free?

Records the PRE-normalization per-image max of the Q-gram for clean
background segments of O3a and O4a (identical preprocessing), runs a KS
test per scale, and freezes E_max = p99.9 of the POOLED maxima for
scheme B2.

Kill criterion (pre-registered): if the max distributions do not differ
(KS p > 0.05 at every scale, Holm-corrected), the contrast-coupling
mechanism has no raw material and the norm-leakage hypothesis is dead —
skip the factorial and attribute the cross-run FPR to physical covariate
shift.

Cost: CPU-only for the statistics; strain fetch dominates. No GPU needed.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import scipy.stats as stats

from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.norm_leakage.common import (
    DETECTOR, OUT_ROOT, SCALES, iter_clean_segments, raw_qgram,
)

logger = setup_logger(__name__)


def run_pretest(n_per_run: int = 200, seed: int = 42, detector: str = DETECTOR):
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    maxima = {run: {s: [] for s in SCALES} for run in ("o3a", "o4a")}

    for run in ("o3a", "o4a"):
        logger.info(f"=== Collecting {n_per_run} clean segments from {run} ===")
        for seg in iter_clean_segments(run, detector, n_per_run, seed=seed):
            for scale in SCALES:
                ts_crop = seg.ts_whitened.crop(seg.t_bg - scale / 2.0,
                                               seg.t_bg + scale / 2.0)
                try:
                    spec = raw_qgram(ts_crop)
                except Exception as e:
                    logger.debug(f"qgram failed at {seg.t_bg}/{scale}s: {e}")
                    break
                maxima[run][scale].append(float(spec.max()))

    report = {"n_per_run": n_per_run, "seed": seed, "detector": detector,
              "scales": {}}
    pvals = []
    for scale in SCALES:
        a = np.array(maxima["o3a"][scale])
        b = np.array(maxima["o4a"][scale])
        ks = stats.ks_2samp(a, b)
        pvals.append(ks.pvalue)
        report["scales"][f"{scale}s"] = {
            "n_o3a": len(a), "n_o4a": len(b),
            "median_o3a": float(np.median(a)), "median_o4a": float(np.median(b)),
            "ks_stat": float(ks.statistic), "ks_pvalue": float(ks.pvalue),
        }
        logger.info(f"{scale}s: KS={ks.statistic:.4f} p={ks.pvalue:.3e} "
                    f"(med O3a={np.median(a):.3g}, med O4a={np.median(b):.3g})")

    # Holm correction across scales, pre-registered kill decision
    order = np.argsort(pvals)
    m = len(pvals)
    rejected_any = False
    for rank, i in enumerate(order):
        if pvals[i] < 0.05 / (m - rank):
            rejected_any = True
        else:
            break
    report["distributions_differ_holm05"] = bool(rejected_any)
    report["verdict"] = (
        "PROCEED: per-image maxima differ between runs — contrast coupling "
        "has raw material; run the factorial." if rejected_any else
        "KILL: maxima indistinguishable between runs — hypothesis (2) has no "
        "mechanism; attribute cross-run FPR to physical covariate shift."
    )

    # Freeze E_max from POOLED maxima (both runs, all scales pooled per-scale
    # would leak scale; we freeze one value per scale).
    report["e_max_per_scale"] = {
        f"{s}s": float(np.percentile(maxima["o3a"][s] + maxima["o4a"][s], 99.9))
        for s in SCALES
    }
    # Single global E_max (max over scales) for the simple B2 scheme.
    e_max = max(report["e_max_per_scale"].values())

    with open(OUT_ROOT / "frozen_emax.json", "w") as f:
        json.dump({"e_max": e_max, "per_scale": report["e_max_per_scale"],
                   "derivation": "p99.9 pooled O3a+O4a, frozen — do not re-derive"},
                  f, indent=2)
    with open(OUT_ROOT / "pretest_max_ks.json", "w") as f:
        json.dump(report, f, indent=2)
    np.savez(OUT_ROOT / "pretest_maxima_raw.npz",
             **{f"{run}_{s}s": np.array(maxima[run][s])
                for run in maxima for s in SCALES})

    logger.info(f"VERDICT: {report['verdict']}")
    logger.info(f"E_max frozen: {e_max:.4g} -> {OUT_ROOT / 'frozen_emax.json'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--detector", type=str, default=DETECTOR)
    a = p.parse_args()
    run_pretest(n_per_run=a.n, seed=a.seed, detector=a.detector)
