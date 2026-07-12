"""V3 integration — multiscale CHARACTERIZATION of V2 candidates.

Design decision (2026-07, post leakage investigation): V3 does not act as a
second discovery trigger. It re-scores the candidates already found by the
V2 production pipeline at sub-scales {0.5, 1, 2, 4} s, producing a
score-vs-scale profile per candidate: an estimate of the transient's
characteristic duration (blips ~O(0.1 s), scattered-light arches ~O(s)).
No OR-fusion of flags -> no multiplicity inflation on discovery claims.

Inputs:
  - Master_Taxonomy_{run}.csv from the V2 aggregate stage,
  - per-scale dictionaries + thresholds from results/micro_mdc/multiscale
    (thresholds are gated by assert_threshold_run: same-run only).

Output:
  - Multiscale_Profile_{run}.csv (one row per candidate x scale),
  - a per-candidate summary with dominant scale and per-scale exceedance
    (exceedance reported for characterization, NOT as a veto/promotion).

In-memory scoring throughout (no PNG round-trip), batched DINOv2.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten_context, extract_clean_subwindow
from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.sampling import assert_threshold_run
from src.pipeline_v3_multiscale.norm_leakage.common import (
    PatchEncoder, raw_qgram, spectrogram_to_rgb, topk_score,
)
from src.core.utils import normalize_spectrogram

logger = setup_logger(__name__)

SCALES = [0.5, 1, 2, 4]
DICT_DIR = Path("results/micro_mdc/multiscale")


def load_scale_dictionaries(detector: str) -> dict[float, np.ndarray]:
    dicts = {}
    for scale in SCALES:
        p = DICT_DIR / f"{detector}_patch_dict_{scale}s.npz"
        if not p.exists():
            raise FileNotFoundError(
                f"Missing V3 dictionary {p} — build it with "
                f"build_multiscale_dictionaries.py --detector {detector}")
        with np.load(p) as d:
            dicts[scale] = d["embeddings"].astype(np.float32)
    return dicts


def load_thresholds(detector: str, run: str) -> dict:
    p = DICT_DIR / f"{detector}_thresholds.json"
    if not p.exists():
        raise FileNotFoundError(f"Missing thresholds {p}")
    with open(p) as f:
        thr = json.load(f)
    # Hard gate: characterization thresholds must be calibrated on the same
    # run as the candidates (cross-run application is the one channel with
    # residual excess — see the 2026-07 leakage investigation).
    assert_threshold_run(thr, run)
    return thr


def profile_candidates(run: str = "O4a",
                       aggregated_dir: str | Path = "data/production/aggregated",
                       detectors: tuple[str, ...] = ("L1", "H1"),
                       batch_size: int = 16,
                       survivors_only: bool = True) -> Path | None:
    aggregated_dir = Path(aggregated_dir)
    tax_path = aggregated_dir / f"Master_Taxonomy_{run}.csv"
    if not tax_path.exists():
        logger.error(f"Taxonomy not found: {tax_path} — run aggregate-report first.")
        return None
    tax = pd.read_csv(tax_path)
    if tax.empty:
        logger.warning("Taxonomy is empty: nothing to characterize.")
        return None

    if survivors_only:
        # Characterize only the candidates that survived the funnel: the
        # full taxonomy is O(10k) rows and re-paying per-candidate strain
        # ops on vetoed/classified entries adds nothing scientifically.
        mask = pd.Series(False, index=tax.index)
        if "transitivity_status" in tax.columns:
            mask |= tax["transitivity_status"] == "Unclassified_Physical_Anomaly"
        if "global_family_id" in tax.columns:
            mask |= tax["global_family_id"].astype(str).str.startswith("Singleton")
        if "robustness_class" in tax.columns:
            mask &= tax["robustness_class"].fillna("ROBUST") != "BACKGROUND"
        n_before = len(tax)
        tax = tax[mask]
        logger.info(f"survivors_only: {len(tax)}/{n_before} candidates "
                    "selected for multiscale characterization.")
        if tax.empty:
            logger.warning("No funnel survivors to characterize.")
            return None

    encoder = PatchEncoder()
    rows = []

    for det in detectors:
        cand = tax[tax["detector"] == det]
        if cand.empty:
            continue
        try:
            dicts = load_scale_dictionaries(det)
            thr = load_thresholds(det, run)
        except FileNotFoundError as e:
            logger.warning(f"[{det}] {e} — skipping detector (explicitly reported).")
            continue

        logger.info(f"[{det}] Characterizing {len(cand)} candidates at "
                    f"scales {SCALES}...")
        for _, row in cand.iterrows():
            gps = float(row["gps_start"])
            center = gps + 16.0  # V2 windows are [gps, gps+32]
            try:
                ts_super = fetch_strain_data(det, gps - 4.0, gps + 36.0,
                                             cache_raw=False, edge_tolerance=4.0)
                ts_w, _ = whiten_context(ts_super, gps, gps + 32.0, pad=4.0)
                ts_bp = extract_clean_subwindow(ts_w, gps, gps + 32.0)
            except Exception as e:
                logger.warning(f"[{det}] fetch/whiten failed at {gps}: {e} — "
                               "candidate profiled as UNAVAILABLE.")
                for scale in SCALES:
                    rows.append({"gps_start": gps, "detector": det,
                                 "scale_s": scale, "score": np.nan,
                                 "p99_threshold": np.nan, "exceeds": None,
                                 "status": "STRAIN_UNAVAILABLE"})
                continue

            rgbs, ok_scales = [], []
            for scale in SCALES:
                try:
                    ts_crop = ts_bp.crop(center - scale / 2.0, center + scale / 2.0)
                    spec = normalize_spectrogram(raw_qgram(ts_crop, qrange=(4, 32)))
                    rgbs.append(spectrogram_to_rgb(spec))
                    ok_scales.append(scale)
                except Exception as e:
                    logger.warning(f"[{det}] qgram failed {gps}/{scale}s: {e}")
                    rows.append({"gps_start": gps, "detector": det,
                                 "scale_s": scale, "score": np.nan,
                                 "p99_threshold": np.nan, "exceeds": None,
                                 "status": "QGRAM_FAILED"})
            if not ok_scales:
                continue
            tokens = encoder.encode_batch(rgbs)
            for scale, tok in zip(ok_scales, tokens):
                score = topk_score(tok, dicts[scale])
                t = thr[f"{scale}s"]["p99_mean"]
                rows.append({"gps_start": gps, "detector": det,
                             "scale_s": scale, "score": score,
                             "p99_threshold": t, "exceeds": bool(score > t),
                             "status": "OK"})

    if not rows:
        logger.warning("No candidates were profiled (missing dictionaries?).")
        return None

    out = pd.DataFrame(rows)
    # dominant scale = scale of max score margin over its own threshold
    out["margin"] = out["score"] - out["p99_threshold"]
    dom = (out[out.status == "OK"]
           .sort_values("margin", ascending=False)
           .groupby(["gps_start", "detector"], as_index=False).first()
           [["gps_start", "detector", "scale_s", "margin"]]
           .rename(columns={"scale_s": "dominant_scale_s",
                            "margin": "dominant_margin"}))
    out = out.merge(dom, on=["gps_start", "detector"], how="left")

    out_path = aggregated_dir / f"Multiscale_Profile_{run}.csv"
    out.to_csv(out_path, index=False)
    n_cand = out.groupby(["gps_start", "detector"]).ngroups
    logger.info(f"Multiscale characterization complete: {n_cand} candidates "
                f"-> {out_path}")
    return out_path


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="V3 multiscale characterization "
                                            "of V2 candidates")
    p.add_argument("--run", type=str, default="O4a")
    p.add_argument("--aggregated-dir", type=str,
                   default="data/production/aggregated")
    p.add_argument("--detectors", nargs="*", default=["L1", "H1"])
    a = p.parse_args()
    profile_candidates(run=a.run, aggregated_dir=a.aggregated_dir,
                       detectors=tuple(a.detectors))
