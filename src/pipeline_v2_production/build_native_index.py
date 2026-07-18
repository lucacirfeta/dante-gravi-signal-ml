"""Run-agnostic builder for the NATIVE background index (Domain Shift Defense).

Produces data/reference/patch_compressed_index_{run}_ex.npz — the artifact
that enables (a) dual-scoring in patch production and (b) the Domain Shift
Defense phase of aggregate-report. Both consumers already resolve the
filename from the observing run, so building the index for a new run (O5,
...) requires no code changes.

Scientific guards:
  - Sampling protocol identical to the V3/leakage machinery
    (iter_clean_segments): full-run DQ window, guard-time >= 96 s,
    excess-power veto, canonical whiten_context preprocessing.
  - ANTI-CIRCULARITY: all candidate GPS windows from the current
    Master_Taxonomy (if present) are EXCLUDED (+/- exclusion_pad) from the
    background sampling, so the dictionary cannot absorb the very anomalies
    it is meant to re-test. The exclusion list is recorded in the metadata.
  - Images rendered with the production colormap (cividis) — the same
    domain used by the DSD candidate rescoring after fix B-DSD-1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.utils import setup_logger, normalize_spectrogram
from src.pipeline_v3_multiscale.norm_leakage.common import (
    PatchEncoder, iter_clean_segments, raw_qgram, spectrogram_to_rgb,
)

logger = setup_logger(__name__)

DEFAULT_K = 1216  # historical native-index size (distinct from the K=275 primary index)


def _candidate_exclusions(run: str, aggregated_dir: Path) -> list[float]:
    tax = aggregated_dir / f"Master_Taxonomy_{run}.csv"
    if not tax.exists():
        logger.warning(f"No taxonomy at {tax}: building WITHOUT candidate "
                       "exclusions (acceptable only if no production scan ran).")
        return []
    df = pd.read_csv(tax)
    gps = sorted(float(g) for g in df.get("gps_start", []))
    logger.info(f"Excluding {len(gps)} candidate windows from background sampling.")
    return gps


def build_native_index(run: str, detector: str, n_dict: int = 1500,
                       k_clusters: int = DEFAULT_K, seed: int = 42,
                       exclusion_pad: float = 96.0,
                       raw_sample_size: int = 50000,
                       aggregated_dir: str | Path = "data/production/aggregated",
                       out_dir: str | Path = "data/reference") -> Path:
    from sklearn.cluster import MiniBatchKMeans

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exclusions = np.array(_candidate_exclusions(run, Path(aggregated_dir)))

    def is_excluded(t_bg: float) -> bool:
        if len(exclusions) == 0:
            return False
        # candidate windows are [gps, gps+32]; t_bg is a 32 s window center
        return bool(np.any((exclusions - exclusion_pad - 16 <= t_bg)
                           & (t_bg <= exclusions + 32 + exclusion_pad + 16)))

    encoder = PatchEncoder()
    tokens_acc = []
    used_t_bgs = []
    n_excluded = 0

    # The DSD scorer is shared by H1 and L1 candidates: a background built
    # from a single detector would bias the rescoring of the other. With
    # detector="both", the background is balanced half/half.
    detectors = ["H1", "L1"] if detector.lower() == "both" else [detector]
    per_det = n_dict // len(detectors)

    logger.info(f"[{run}/{'+'.join(detectors)}] Building native index: "
                f"n_dict={n_dict}, K={k_clusters}, seed={seed}")
    for det_i, det in enumerate(detectors):
        for seg in iter_clean_segments(run.lower(), det, per_det,
                                       seed=seed + det_i):
            if is_excluded(seg.t_bg):
                n_excluded += 1
                continue
            try:
                spec = normalize_spectrogram(raw_qgram(
                    seg.ts_whitened.crop(seg.t_bg - 16, seg.t_bg + 16)))
                tokens = encoder.encode_rgb(spectrogram_to_rgb(spec))
            except Exception as e:
                logger.debug(f"[{det}] segment {seg.t_bg} failed: {e}")
                continue
            tokens_acc.append(tokens)
            used_t_bgs.append(seg.t_bg)

    if len(used_t_bgs) < max(50, n_dict // 4):
        raise RuntimeError(
            f"Only {len(used_t_bgs)} background segments collected "
            f"({n_excluded} vetoed as candidate-adjacent) — refusing to build "
            "a native index from an unrepresentative background.")

    embs = np.vstack(tokens_acc)
    logger.info(f"Clustering {embs.shape[0]} patch tokens from "
                f"{len(used_t_bgs)} segments ({n_excluded} candidate-adjacent "
                f"excluded)...")
    km = MiniBatchKMeans(n_clusters=k_clusters, batch_size=4096,
                         compute_labels=False, random_state=seed, n_init="auto")
    km.fit(embs)
    cents = km.cluster_centers_
    cents = cents / (np.linalg.norm(cents, axis=1, keepdims=True) + 1e-12)

    # Persist a seeded, L2-normalized subsample of the RAW pre-quantization
    # patch tokens. The K-means centroids are well separated by construction,
    # so a point-to-point comparison against them (e.g. the morphological
    # diffusivity test) over-estimates the true background spread. Retaining
    # raw points makes that comparison, and index-stability re-clustering,
    # reproducible for this and every future run. Set raw_sample_size=0 to
    # opt out. Does not affect the existing `embeddings` (centroid) key.
    raw_sample = np.empty((0, embs.shape[1]), dtype=np.float32)
    if raw_sample_size and raw_sample_size > 0:
        rng = np.random.default_rng(seed)
        n_take = min(int(raw_sample_size), embs.shape[0])
        idx = rng.choice(embs.shape[0], size=n_take, replace=False)
        raw_sample = embs[idx].astype(np.float32)
        raw_sample = raw_sample / (
            np.linalg.norm(raw_sample, axis=1, keepdims=True) + 1e-12)
        logger.info(f"Persisting {n_take} raw pre-quantization background "
                    f"tokens (of {embs.shape[0]}) for reproducible "
                    "point-to-point analyses.")

    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        git = "unknown"

    out = out_dir / f"patch_compressed_index_{run.lower()}_ex.npz"
    np.savez_compressed(
        out,
        embeddings=cents.astype(np.float32),
        labels=np.array([f"BG_{run}"] * k_clusters),
        raw_embeddings_sample=raw_sample,
        meta=json.dumps({
            "run": run, "detector": detector, "K": k_clusters, "seed": seed,
            "n_segments": len(used_t_bgs), "n_candidate_excluded": n_excluded,
            "exclusion_pad_s": exclusion_pad, "colormap": "cividis",
            "preprocessing": "whiten_context_v1_single_bandpass", "git": git,
            "raw_sample_size": int(raw_sample.shape[0]),
            "raw_sample_total_tokens": int(embs.shape[0]),
            "raw_sample_seed": seed,
        }),
    )
    with open(out.with_suffix(".t_bg.json"), "w") as f:
        json.dump(used_t_bgs, f)
    logger.info(f"Native index saved -> {out}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build run-native background index (DSD)")
    p.add_argument("--run", type=str, required=True)
    p.add_argument("--detector", type=str, default="L1")
    p.add_argument("--n_dict", type=int, default=1500)
    p.add_argument("--k", type=int, default=DEFAULT_K)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--raw_sample_size", type=int, default=50000,
                   help="Rows of raw pre-quantization tokens to persist "
                        "for reproducible point-to-point analyses (0=off).")
    a = p.parse_args()
    build_native_index(a.run, a.detector, n_dict=a.n_dict, k_clusters=a.k,
                       seed=a.seed, raw_sample_size=a.raw_sample_size)
