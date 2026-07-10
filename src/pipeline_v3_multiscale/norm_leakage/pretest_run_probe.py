"""Pre-test 2 — is the run decodable from embeddings of CLEAN background?

Linear probe (logistic regression, 5-fold CV) classifying O3a vs O4a from
mean patch-token embeddings of vetoed background segments, under both
normalization schemes.

Interpretation (pre-registered):
  AUC(B1) ~ 0.5              -> no run signature in feature space at all;
                                the cross-run FPR must come from
                                centroids/thresholds, not features.
  AUC(B1) high, AUC(B2) ~0.5 -> the signature is carried by the per-image
                                min-max: strong direct evidence for (2).
  AUC high under BOTH        -> the signature survives fixed normalization:
                                physical covariate shift dominates.

Requires frozen_emax.json (run pretest_max_ks.py first). GPU recommended.
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.norm_leakage.common import (
    DETECTOR, OUT_ROOT, SCALES, PatchEncoder, get_normalizer,
    iter_clean_segments, raw_qgram, spectrogram_to_rgb,
)

logger = setup_logger(__name__)


def run_probe(n_per_run: int = 300, seed: int = 42, detector: str = DETECTOR):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import roc_auc_score

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    encoder = PatchEncoder()
    normalizers = {"minmax": get_normalizer("minmax"),
                   "fixed": get_normalizer("fixed")}

    # embeddings[scheme][scale] -> list of (vector, label)
    embs = {sch: {s: [] for s in SCALES} for sch in normalizers}
    labels = {sch: {s: [] for s in SCALES} for sch in normalizers}

    for label, run in enumerate(("o3a", "o4a")):
        logger.info(f"=== Encoding {n_per_run} clean segments from {run} ===")
        for seg in iter_clean_segments(run, detector, n_per_run, seed=seed):
            for scale in SCALES:
                ts_crop = seg.ts_whitened.crop(seg.t_bg - scale / 2.0,
                                               seg.t_bg + scale / 2.0)
                try:
                    spec_raw = raw_qgram(ts_crop)
                except Exception:
                    break
                for sch, norm in normalizers.items():
                    rgb = spectrogram_to_rgb(norm(spec_raw))
                    tokens = encoder.encode_rgb(rgb)
                    vec = tokens.mean(axis=0)
                    vec /= np.linalg.norm(vec) + 1e-12
                    embs[sch][scale].append(vec)
                    labels[sch][scale].append(label)

    report = {"n_per_run": n_per_run, "seed": seed, "detector": detector,
              "auc": {}}
    for sch in normalizers:
        report["auc"][sch] = {}
        for scale in SCALES:
            X = np.array(embs[sch][scale])
            y = np.array(labels[sch][scale])
            if len(np.unique(y)) < 2 or len(y) < 40:
                report["auc"][sch][f"{scale}s"] = None
                continue
            cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
            aucs = []
            for tr, te in cv.split(X, y):
                clf = LogisticRegression(max_iter=2000, C=1.0)
                clf.fit(X[tr], y[tr])
                aucs.append(roc_auc_score(y[te], clf.predict_proba(X[te])[:, 1]))
            auc_mean = float(np.mean(aucs))
            report["auc"][sch][f"{scale}s"] = {
                "mean": auc_mean, "std": float(np.std(aucs)), "folds": aucs}
            logger.info(f"[{sch}] {scale}s: run-probe AUC = "
                        f"{auc_mean:.3f} +/- {np.std(aucs):.3f}")

    with open(OUT_ROOT / "pretest_run_probe.json", "w") as f:
        json.dump(report, f, indent=2)
    logger.info(f"Saved -> {OUT_ROOT / 'pretest_run_probe.json'}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--detector", type=str, default=DETECTOR)
    a = p.parse_args()
    run_probe(n_per_run=a.n, seed=a.seed, detector=a.detector)
