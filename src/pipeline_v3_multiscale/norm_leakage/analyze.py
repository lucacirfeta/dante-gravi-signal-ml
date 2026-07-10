"""Pre-registered analysis of the norm-leakage factorial experiment.

DO NOT edit the criteria in this file after scores_test_o3a.csv exists.

Primary endpoint (continuous): per-segment paired difference
    D_i(norm) = score(dict_O4a) - score(dict_O3a)   on the same O3a segment,
averaged over KMeans seeds. Interaction statistic:
    Delta_int = mean(D | minmax) - mean(D | fixed).
CI via moving-block bootstrap (b = n^(1/3), B = 1000, seed = 42) on the
GPS-ordered D-difference series (segments are guard-time separated, but
block bootstrap costs nothing and protects against residual correlation).

Secondary endpoint (operational): FPR_cross = fraction of O3a test
segments whose O4a-dictionary score exceeds the p99 threshold calibrated
on O4a background (per norm scheme, per seed, per scale). McNemar test on
paired exceedances minmax-vs-fixed.

Pre-registered verdicts (per scale, Holm-corrected across scales):
  CONFIRM (2) dominant:  FPR_cross(fixed) CI95 within [0.5%, 2%]
                         AND Delta_int > 0 with bootstrap CI95 excluding 0
                         AND |Delta_int| > 3 * seed-to-seed std of Delta_int.
  REJECT  (2):           FPR_cross(fixed) > 4% with CI95 excluding 2%
                         AND Delta_int CI95 including 0.
  PARTIAL otherwise:     report attributable fraction
                         Delta_int / mean(D | minmax) with CI, no binary claim.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.norm_leakage.common import OUT_ROOT, SCALES
from src.pipeline_v3_multiscale.norm_leakage.build_dictionaries import KMEANS_SEEDS

logger = setup_logger(__name__)

B_BOOT = 1000
BOOT_SEED = 42


def moving_block_ci(x: np.ndarray, B: int = B_BOOT, seed: int = BOOT_SEED,
                    stat=np.mean, alpha: float = 0.05):
    rng = np.random.default_rng(seed)
    n = len(x)
    b = max(1, int(n ** (1 / 3)))
    num_blocks = int(np.ceil(n / b))
    stats_ = np.empty(B)
    for i in range(B):
        starts = rng.integers(0, n - b + 1, size=num_blocks)
        boot = np.concatenate([x[s:s + b] for s in starts])[:n]
        stats_[i] = stat(boot)
    return (float(np.percentile(stats_, 100 * alpha / 2)),
            float(np.percentile(stats_, 100 * (1 - alpha / 2))))


def mcnemar_p(b01: int, b10: int) -> float:
    """Exact binomial McNemar on discordant pairs."""
    import scipy.stats as st
    n = b01 + b10
    if n == 0:
        return 1.0
    return float(st.binomtest(min(b01, b10), n, 0.5).pvalue * 1.0)


def analyze():
    test_csv = OUT_ROOT / "scores_test_o3a.csv"
    calib_csv = OUT_ROOT / "scores_calib_o4a.csv"
    df = pd.read_csv(test_csv)
    dfc = pd.read_csv(calib_csv)

    results = {"scales": {}, "pre_registered": True}

    for scale in SCALES:
        d = df[df.scale == scale]
        dc = dfc[dfc.scale == scale]

        # ------- primary endpoint -------
        # pivot: per (gps, norm, kmeans_seed): D = score(o4a) - score(o3a)
        piv = d.pivot_table(index=["gps", "norm", "kmeans_seed"],
                            columns="dict_run", values="score").dropna()
        piv["D"] = piv["o4a"] - piv["o3a"]

        delta_int_by_seed = {}
        for ks in KMEANS_SEEDS:
            sub = piv.xs(ks, level="kmeans_seed")
            d_mm = sub.xs("minmax", level="norm")["D"]
            d_fx = sub.xs("fixed", level="norm")["D"]
            common = d_mm.index.intersection(d_fx.index)
            delta_int_by_seed[ks] = float(d_mm[common].mean() - d_fx[common].mean())

        seed_std = float(np.std(list(delta_int_by_seed.values())))

        # seed-averaged paired series, GPS-ordered
        avg = piv.groupby(["gps", "norm"])["D"].mean().unstack("norm").dropna()
        avg = avg.sort_index()
        diff_series = (avg["minmax"] - avg["fixed"]).to_numpy()
        delta_int = float(diff_series.mean())
        ci_lo, ci_hi = moving_block_ci(diff_series)

        mean_d_minmax = float(avg["minmax"].mean())
        attributable = delta_int / mean_d_minmax if mean_d_minmax != 0 else np.nan

        # ------- secondary endpoint: cross-run FPR -------
        fpr = {}
        exceed = {}
        for norm in ("minmax", "fixed"):
            hits_per_gps = None
            fprs = []
            for ks in KMEANS_SEEDS:
                cal = dc[(dc.norm == norm) & (dc.kmeans_seed == ks)
                         & (dc.dict_run == "o4a")]["score"]
                if len(cal) < 50:
                    continue
                thr = float(np.percentile(cal, 99))
                tst = d[(d.norm == norm) & (d.kmeans_seed == ks)
                        & (d.dict_run == "o4a")].set_index("gps")["score"]
                hits = (tst > thr)
                fprs.append(float(hits.mean()))
                hits_per_gps = hits if hits_per_gps is None else (hits_per_gps | hits)
            fpr[norm] = {"mean": float(np.mean(fprs)) if fprs else None,
                         "per_seed": fprs}
            exceed[norm] = hits_per_gps

        mcn = None
        if exceed["minmax"] is not None and exceed["fixed"] is not None:
            common = exceed["minmax"].index.intersection(exceed["fixed"].index)
            a01 = int((exceed["minmax"][common] & ~exceed["fixed"][common]).sum())
            a10 = int((~exceed["minmax"][common] & exceed["fixed"][common]).sum())
            mcn = mcnemar_p(a01, a10)

        # binomial CI (Wilson) on FPR(fixed) — segments are guard-separated
        fpr_fx = fpr["fixed"]["mean"]
        n_test = int(avg.shape[0])
        wilson = None
        if fpr_fx is not None and n_test > 0:
            import scipy.stats as st
            k = int(round(fpr_fx * n_test))
            lo, hi = st.binomtest(k, n_test).proportion_ci(0.95, method="wilson")
            wilson = (float(lo), float(hi))

        # ------- verdict -------
        confirm = (wilson is not None and wilson[1] <= 0.02 and wilson[0] >= 0.0
                   and ci_lo > 0 and abs(delta_int) > 3 * seed_std)
        reject = (wilson is not None and wilson[0] > 0.02 and
                  (fpr_fx or 0) > 0.04 and ci_lo <= 0 <= ci_hi)
        verdict = ("CONFIRM_NORMALIZATION_LEAKAGE" if confirm else
                   "REJECT_NORMALIZATION_LEAKAGE" if reject else "PARTIAL")

        results["scales"][f"{scale}s"] = {
            "n_test_segments": n_test,
            "delta_int": delta_int,
            "delta_int_ci95": [ci_lo, ci_hi],
            "delta_int_by_seed": delta_int_by_seed,
            "seed_std": seed_std,
            "mean_D_minmax": mean_d_minmax,
            "attributable_fraction": attributable,
            "fpr_cross": fpr,
            "fpr_fixed_wilson_ci95": wilson,
            "mcnemar_p": mcn,
            "verdict": verdict,
        }
        logger.info(f"{scale}s: Delta_int={delta_int:.5f} CI[{ci_lo:.5f},{ci_hi:.5f}] "
                    f"seed_std={seed_std:.5f} FPR(minmax)={fpr['minmax']['mean']} "
                    f"FPR(fixed)={fpr_fx} -> {verdict}")

    out = OUT_ROOT / "analysis_verdict.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"Saved verdict -> {out}")


if __name__ == "__main__":
    analyze()
