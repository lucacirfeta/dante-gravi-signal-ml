"""Are the DSD survivors an artifact of which background built the dictionary?

The native index is a K-means dictionary over a *sample* of the run's own
background. If which candidates survive the DSD depends on that sample, the
survivor population -- the central object of the survey -- is partly an artifact
of a random draw rather than a property of the candidates.

The test builds several independent native indices from disjoint bootstrap draws
of the background pool (raw_qgram, vetoed background -- matching
``build_native_index``), and re-scores the same candidates against each. The
answer is read from three threshold-independent statistics:

* **Score rank correlation** across draws -- if a candidate scores high against
  one draw and high against another, the ordering is a property of the
  candidate, not of the reference.
* **Per-candidate score std** across draws -- how much a single candidate's
  score wobbles when the reference is resampled.
* **ROBUST vs rejected separation** under the rebuilt indices -- if survivors
  still score above rejected candidates against a fresh index, the boundary is
  a property of the candidates.

All three avoid a threshold on purpose. Reproducing the *production* survive/
reject threshold is subtle -- production calibrates it on un-vetoed
(glitch-inclusive) background while it builds the index on vetoed background
(LAB_NOTEBOOK section 19) -- so the verdict metrics are reported only as
diagnostics, not as production-faithful decisions. The rank correlation is the
headline result and needs no threshold.

The sample concentrates near the DSD threshold, where the survivor/reject
distinction is most fragile; a rejected (BACKGROUND) contrast set is included.

Candidate patch tokens are not stored, so candidates are re-encoded. Catalogues
before 2026-07-24 label the padded crop, so the analysis window is
[gps + 4, gps + 36] (see the reproducibility note). Encoding is cached.

Usage
-----
    python -m src.pipeline_v2_production.dsd_index_stability --pilot
    python -m src.pipeline_v2_production.dsd_index_stability --n-candidates 60

Writes ``data/production/aggregated/dsd_index_stability_{run}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.utils import normalize_spectrogram, record_environment, setup_logger
from src.pipeline_v2_production.dsd_absorption_threshold import (
    _build_index, _encode_segments)
from src.pipeline_v3_multiscale.norm_leakage.common import (
    PatchEncoder, iter_clean_segments, raw_qgram, spectrogram_to_rgb, topk_score)

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
PROD = Path("data/production")
SEGMENT_LENGTH = 32.0
WINDOW_OFFSET = 4.0          # catalogue GPS labels the padded crop
TOP_K = 68


def _encode_candidates(cands: pd.DataFrame) -> np.ndarray:
    """Patch tokens for each candidate, from the true [gps+4, gps+36] window."""
    import warnings

    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import (whiten_context, extract_clean_subwindow,
                                       generate_qtransform)

    enc = PatchEncoder()
    toks, kept = [], []
    for _, c in cands.iterrows():
        w0 = float(c.gps_start) + WINDOW_OFFSET
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ts = fetch_strain_data(c.detector, w0 - 4.0, w0 + SEGMENT_LENGTH + 4.0,
                                       edge_tolerance=4.0)
                tw, _ = whiten_context(ts, w0, w0 + SEGMENT_LENGTH, pad=4.0)
                clean = extract_clean_subwindow(tw, w0, w0 + SEGMENT_LENGTH)
                spec = generate_qtransform(clean, save_path=None, cmap="cividis")
            toks.append(enc.encode_rgb(spectrogram_to_rgb(normalize_spectrogram(spec))))
            kept.append(True)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"candidate {c.gps_start} failed: {e}")
            kept.append(False)
    return np.asarray(toks, dtype=np.float32), np.asarray(kept)


def _sample(tax: pd.DataFrame, n_each: int, seed: int) -> pd.DataFrame:
    """Near-threshold ROBUST survivors and near-threshold rejected, both detectors."""
    import json as _json
    mc = _json.loads((AGG / "dsd_threshold_mc_error.json").read_text())["detectors"]
    picks = []
    for det in ("H1", "L1"):
        thr = mc[det]["tau_hi"]["mean"]
        d = tax[tax.detector == det]
        rob = d[(d.robustness_class == "ROBUST") &
                (d.native_o4a_score < thr + 0.04)].nsmallest(n_each, "native_o4a_score")
        rej = d[(d.robustness_class == "BACKGROUND") &
                (d.native_o4a_score > thr - 0.06)].nlargest(n_each, "native_o4a_score")
        picks += [rob, rej]
    out = pd.concat(picks).drop_duplicates(["detector", "gps_start"]).reset_index(drop=True)
    return out


# Production native index: 1295 background segments, K=1216 (~1458 tokens per
# centroid). The rebuilt indices must match that scale, or their score scale is
# compressed and does not reproduce the DSD decision boundary -- a smaller index
# scores every candidate above its threshold, survivors and rejected alike.
PRODUCTION_N_BACKGROUND = 1300


def run(run_name: str = "O4a", n_candidates: int = 40,
        n_background: int = PRODUCTION_N_BACKGROUND,
        n_holdout_bg: int = 300, n_draws: int = 4, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    tax = pd.read_csv(AGG / f"Master_Taxonomy_{run_name.lower()}.csv")
    tax["gps_start"] = tax.gps_start.astype(int)

    cands = _sample(tax, n_candidates, seed)
    logger.info(f"{len(cands)} candidates "
                f"({(cands.robustness_class=='ROBUST').sum()} ROBUST, "
                f"{(cands.robustness_class=='BACKGROUND').sum()} rejected)")

    cache = AGG / f"dsd_index_stability_tokens_{run_name.lower()}_n{n_candidates}_s{seed}.npz"
    if cache.exists():
        logger.info(f"loading cached tokens from {cache.name}")
        z = np.load(cache, allow_pickle=True)
        cand_tok, kept = z["cand"], z["kept"]
        bg_tok, hold_tok = z["bg"], z["hold"]
        cands = cands[kept].reset_index(drop=True)
    else:
        logger.info("encoding candidates (true [gps+4, gps+36] window)")
        cand_tok, kept = _encode_candidates(cands)
        cands = cands[kept].reset_index(drop=True)
        enc = PatchEncoder()
        logger.info(f"collecting {n_background + n_holdout_bg} background segments")
        segs = list(iter_clean_segments(run_name.lower(), "L1",
                                        n_background + n_holdout_bg + 40, seed=seed))
        logger.info("encoding background pool + held-out background")
        bg_tok = _encode_segments(enc, segs[:n_background])
        hold_tok = _encode_segments(enc, segs[n_background:n_background + n_holdout_bg])
        np.savez_compressed(cache, cand=cand_tok, kept=kept, bg=bg_tok, hold=hold_tok)
        logger.info(f"cached tokens to {cache.name}")

    # Independent index draws: disjoint bootstrap resamples of the background
    # pool. Each gets its own threshold from the held-out background.
    n_bg = len(bg_tok)
    cand_scores = np.zeros((n_draws, len(cand_tok)))
    survive = np.zeros((n_draws, len(cand_tok)), dtype=bool)
    thresholds = []
    for k in range(n_draws):
        idx = rng.choice(n_bg, size=n_bg, replace=True)
        cents = _build_index(bg_tok[idx], seed + k)
        hb = np.array([topk_score(t, cents, TOP_K) for t in hold_tok])
        thr = float(np.percentile(hb, 99))
        thresholds.append(thr)
        cs = np.array([topk_score(t, cents, TOP_K) for t in cand_tok])
        cand_scores[k] = cs
        survive[k] = cs > thr
        logger.info(f"draw {k}: threshold {thr:.4f}, survivors "
                    f"{int(survive[k].sum())}/{len(cs)}")

    is_rob = (cands.robustness_class == "ROBUST").to_numpy()

    # PRIMARY, threshold-independent metrics. The survive/reject verdict needs a
    # threshold, and reproducing the production threshold is subtle: production
    # calibrates it on UN-VETOED background (glitch-inclusive, P99=0.447) while
    # the index is built on VETOED background (see LAB_NOTEBOOK §19). The
    # held-out threshold here uses vetoed background and lands at ~0.10, far
    # below where the candidates sit, so the verdict metrics are not
    # production-faithful and are reported only as diagnostics. These three do
    # not depend on any threshold and answer the stability question directly:
    from scipy.stats import spearmanr
    rhos = [spearmanr(cand_scores[i], cand_scores[j]).statistic
            for i in range(n_draws) for j in range(i + 1, n_draws)]
    per_cand_std = cand_scores.std(axis=0)          # score wobble across draws
    rob_mean = float(cand_scores.mean(axis=0)[is_rob].mean())
    rej_mean = float(cand_scores.mean(axis=0)[~is_rob].mean())

    # Diagnostic verdict metrics (NOT production-faithful, see above).
    all_survive = survive.all(axis=0)
    all_reject = (~survive).all(axis=0)

    out = {
        "run": run_name, "n_candidates": int(len(cand_tok)),
        "n_robust": int(is_rob.sum()), "n_rejected": int((~is_rob).sum()),
        "n_draws": n_draws, "n_background": n_bg, "seed": seed,
        # --- primary, threshold-independent ---
        "score_rank_correlation_mean": float(np.mean(rhos)),
        "score_rank_correlation_min": float(np.min(rhos)),
        "per_candidate_score_std_median": float(np.median(per_cand_std)),
        "per_candidate_score_std_max": float(per_cand_std.max()),
        "robust_mean_score": rob_mean,
        "rejected_mean_score": rej_mean,
        "robust_rejected_separation": rob_mean - rej_mean,
        # --- diagnostic only: threshold not production-faithful (§19) ---
        "_diagnostic_thresholds": thresholds,
        "_diagnostic_verdict_note": (
            "held-out threshold uses vetoed background (~0.10) not the "
            "un-vetoed production calibration (~0.447); verdict metrics below "
            "are not production-faithful, see LAB_NOTEBOOK section 19"),
        "_diagnostic_verdict_stable_fraction": float((all_survive | all_reject).mean()),
    }
    dest = AGG / f"dsd_index_stability_{run_name.lower()}.json"
    dest.write_text(json.dumps(out, indent=2))
    logger.info(
        f"score rank-corr {out['score_rank_correlation_mean']:.3f} "
        f"(min {out['score_rank_correlation_min']:.3f}) | per-candidate std "
        f"median {out['per_candidate_score_std_median']:.4f} | ROBUST "
        f"{rob_mean:.3f} vs rejected {rej_mean:.3f} across independent draws")
    logger.info(f"wrote {dest}")
    record_environment(AGG, f"dsd_index_stability_{run_name.lower()}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-candidates", type=int, default=40,
                   help="Near-threshold candidates per (class, detector).")
    p.add_argument("--n-background", type=int, default=PRODUCTION_N_BACKGROUND,
                   help="Background segments per index. Must match the production "
                        "index size (~1300, K~1216) or the score scale is "
                        "compressed and the DSD boundary is not reproduced.")
    p.add_argument("--n-draws", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Fast machinery check. NOTE: its small index does NOT "
                        "reproduce the DSD boundary (everything survives); use "
                        "only to confirm the pipeline runs end to end.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, n_candidates=8, n_background=120, n_holdout_bg=60,
            n_draws=3, seed=a.seed)
    else:
        run(a.run, n_candidates=a.n_candidates, n_background=a.n_background,
            n_draws=a.n_draws, seed=a.seed)


if __name__ == "__main__":
    main()
