"""Fairness control — does the fixed normalization destroy morphology?

Scores N known O3a L1 Blips (Gravity Spy, ml_confidence >= 0.95) and the
already-scored O3a background under both normalization schemes with the
O3a dictionary, and reports detection AUC per scheme.

Pre-registered gate: if AUC(fixed) < AUC(minmax) - 0.05 at any scale, the
factorial comparison is NOT fair (B2 saturates morphology) and a null
interaction cannot be read as evidence against hypothesis (2) — pick a
larger E_max and repeat.
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from src.core.utils import setup_logger
from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten_context, extract_clean_subwindow
from src.pipeline_v3_multiscale.norm_leakage.common import (
    DETECTOR, OUT_ROOT, SCALES, PatchEncoder, get_normalizer,
    raw_qgram, spectrogram_to_rgb, topk_score,
)
from src.pipeline_v3_multiscale.norm_leakage.score_testset import _load_dicts
from src.pipeline_v3_multiscale.norm_leakage.build_dictionaries import KMEANS_SEEDS

logger = setup_logger(__name__)


def run_check(n_blips: int = 100, detector: str = DETECTOR, seed: int = 42):
    from src.core.reference_index_builder import download_gs_classifications_csv
    from sklearn.metrics import roc_auc_score

    csv_path = download_gs_classifications_csv(
        OUT_ROOT / "gs_cache", run="O3a", detector=detector)
    df = pd.read_csv(csv_path)
    blips = df[(df.ml_label == "Blip") & (df.ml_confidence >= 0.95)]
    blips = blips.sample(n=min(n_blips, len(blips)), random_state=seed)

    dicts = _load_dicts(detector)
    encoder = PatchEncoder()
    normalizers = {"minmax": get_normalizer("minmax"),
                   "fixed": get_normalizer("fixed")}

    blip_scores = {sch: {s: [] for s in SCALES} for sch in normalizers}
    for _, row in blips.iterrows():
        t = float(row["event_time"])
        try:
            ts_super = fetch_strain_data(detector, t - 16 - 4.0, t + 16 + 4.0,
                                         cache_raw=True, edge_tolerance=4.0)
            ts_w, _ = whiten_context(ts_super, t - 16, t + 16, pad=4.0)
            ts_bp = extract_clean_subwindow(ts_w, t - 16, t + 16)
        except Exception as e:
            logger.debug(f"blip {t}: {e}")
            continue
        for scale in SCALES:
            try:
                spec_raw = raw_qgram(ts_bp.crop(t - scale / 2, t + scale / 2))
            except Exception:
                continue
            for sch, norm in normalizers.items():
                tokens = encoder.encode_rgb(spectrogram_to_rgb(norm(spec_raw)))
                seed_scores = [
                    topk_score(tokens, dicts[("o3a", sch, ks, scale)])
                    for ks in KMEANS_SEEDS if ("o3a", sch, ks, scale) in dicts]
                if seed_scores:
                    blip_scores[sch][scale].append(float(np.mean(seed_scores)))

    # background scores from the already-computed shared test set
    bg = pd.read_csv(OUT_ROOT / "scores_test_o3a.csv")
    bg = bg[bg.dict_run == "o3a"].groupby(
        ["gps", "norm", "scale"])["score"].mean().reset_index()

    report = {"n_blips": int(len(blips)), "auc": {}}
    for sch in normalizers:
        report["auc"][sch] = {}
        for scale in SCALES:
            pos = np.array(blip_scores[sch][scale])
            neg = bg[(bg.norm == sch) & (bg.scale == scale)]["score"].to_numpy()
            if len(pos) < 10 or len(neg) < 50:
                report["auc"][sch][f"{scale}s"] = None
                continue
            y = np.r_[np.ones(len(pos)), np.zeros(len(neg))]
            auc = float(roc_auc_score(y, np.r_[pos, neg]))
            report["auc"][sch][f"{scale}s"] = auc
            logger.info(f"[{sch}] {scale}s detection AUC = {auc:.3f}")

    fair = True
    for scale in SCALES:
        a_mm = report["auc"]["minmax"].get(f"{scale}s")
        a_fx = report["auc"]["fixed"].get(f"{scale}s")
        if a_mm is not None and a_fx is not None and a_fx < a_mm - 0.05:
            fair = False
    report["b2_comparison_is_fair"] = fair
    if not fair:
        logger.warning("B2 degrades detection by >0.05 AUC: the factorial "
                       "comparison is NOT fair — raise E_max and repeat.")

    with open(OUT_ROOT / "check_detection_b2.json", "w") as f:
        json.dump(report, f, indent=2)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n_blips", type=int, default=100)
    p.add_argument("--detector", type=str, default=DETECTOR)
    a = p.parse_args()
    run_check(n_blips=a.n_blips, detector=a.detector)
