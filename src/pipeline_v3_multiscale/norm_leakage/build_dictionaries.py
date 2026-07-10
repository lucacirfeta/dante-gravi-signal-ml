"""Factorial dictionary builder — one protocol, 2 runs x 2 norms x N seeds.

Every cell uses the SAME segment-sampling protocol (iter_clean_segments),
the SAME K (275, production value), the SAME veto chain. The only
differences between cells are the experimental factors: source run and
normalization scheme. KMeans is repeated over multiple seeds because
seed-to-seed variance is the noise floor against which the interaction
effect must be judged (pre-registered gate in analyze.py).

Segments are drawn once per run (seed fixed) and their embeddings under
both normalization schemes are extracted in the same pass, so the B1/B2
dictionaries of a given run come from IDENTICAL strain data.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import numpy as np

from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.norm_leakage.common import (
    DETECTOR, K_CLUSTERS, OUT_ROOT, SCALES, PatchEncoder, get_normalizer,
    iter_clean_segments, raw_qgram, spectrogram_to_rgb,
)

logger = setup_logger(__name__)

KMEANS_SEEDS = [42, 43, 44]


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def build_for_run(run: str, n_dict: int = 500, seed: int = 42,
                  detector: str = DETECTOR):
    out_dir = OUT_ROOT / "dictionaries"
    out_dir.mkdir(parents=True, exist_ok=True)

    encoder = PatchEncoder()
    normalizers = {"minmax": get_normalizer("minmax"),
                   "fixed": get_normalizer("fixed")}

    # tokens[scheme][scale] -> list of (1369, 384) arrays
    tokens_acc = {sch: {s: [] for s in SCALES} for sch in normalizers}
    t_bgs: list[float] = []

    logger.info(f"=== Building embeddings for run={run}, n_dict={n_dict} ===")
    for seg in iter_clean_segments(run, detector, n_dict, seed=seed):
        per_scale_ok = True
        staged = {sch: {} for sch in normalizers}
        for scale in SCALES:
            ts_crop = seg.ts_whitened.crop(seg.t_bg - scale / 2.0,
                                           seg.t_bg + scale / 2.0)
            try:
                spec_raw = raw_qgram(ts_crop)
            except Exception as e:
                logger.debug(f"qgram failed at {seg.t_bg}/{scale}s: {e}")
                per_scale_ok = False
                break
            for sch, norm in normalizers.items():
                rgb = spectrogram_to_rgb(norm(spec_raw))
                staged[sch][scale] = encoder.encode_rgb(rgb)
        if not per_scale_ok:
            continue
        t_bgs.append(seg.t_bg)
        for sch in normalizers:
            for scale in SCALES:
                tokens_acc[sch][scale].append(staged[sch][scale])

    if len(t_bgs) < n_dict:
        logger.warning(f"[{run}] only {len(t_bgs)}/{n_dict} segments embedded.")

    with open(out_dir / f"{detector}_{run}_dict_t_bg.json", "w") as f:
        json.dump(t_bgs, f)

    from sklearn.cluster import MiniBatchKMeans

    for sch in normalizers:
        for scale in SCALES:
            embs = np.vstack(tokens_acc[sch][scale])
            for km_seed in KMEANS_SEEDS:
                km = MiniBatchKMeans(n_clusters=K_CLUSTERS, batch_size=4096,
                                     compute_labels=False, random_state=km_seed,
                                     n_init="auto")
                km.fit(embs)
                cents = km.cluster_centers_
                cents = cents / (np.linalg.norm(cents, axis=1, keepdims=True) + 1e-12)
                out = out_dir / f"{detector}_{run}_{sch}_seed{km_seed}_{scale}s.npz"
                np.savez_compressed(
                    out, embeddings=cents.astype(np.float32),
                    labels=np.arange(K_CLUSTERS),
                    meta=json.dumps({
                        "run": run, "norm": sch, "kmeans_seed": km_seed,
                        "segment_seed": seed, "K": K_CLUSTERS, "scale": scale,
                        "n_segments": len(t_bgs), "detector": detector,
                        "git": _git_commit(),
                    }),
                )
                logger.info(f"Saved {out.name}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", choices=["o3a", "o4a"], required=True)
    p.add_argument("--n_dict", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--detector", type=str, default=DETECTOR)
    a = p.parse_args()
    build_for_run(a.run, n_dict=a.n_dict, seed=a.seed, detector=a.detector)
