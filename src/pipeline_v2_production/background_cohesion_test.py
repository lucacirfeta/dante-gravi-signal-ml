"""Falsification test for macro-cluster cohesion, against TRUE native background.

Why this exists. The global clustering puts essentially every candidate into a
single macro-cluster, and we previously read that topology as a property of the
DSD survivors. A first falsification (see `family_cohesion_falsification.json`)
showed the DSD-*rejected* candidates form the same macro-cluster, so the
topology carries no information about anomaly status. That test used rejected
candidates as its control, which is conservative but not ideal: they are still
candidates, i.e. they passed initial novelty detection.

This module supplies the ideal control -- unselected native background segments,
drawn with the SAME selection the native index uses (CAT1-clean, candidate
windows excluded by +-96 s) and encoded through the SAME production MIL path as
the candidates, so the comparison is genuinely like-for-like.

Two things must be identical to the candidate path or the comparison is void:

  1. Chromatic domain. The stored candidate vectors live in the cividis domain;
     encoding background from a raw Q-transform would repeat bug B-DSD-1 /
     COINC-2 and depress every similarity. We reuse the verified production
     encoding (cividis -> score_spectrogram -> mil_vector).
  2. Pooling. Candidates are Top-k=68 MIL aggregates, one 384-d vector per
     32 s segment. Clustering raw *patch tokens* (what the native index
     persists via --raw_sample_size) against candidate MIL vectors would
     compare different objects. We pool identically here.

Single-linkage chaining is strongly sample-size dependent, so populations are
always compared at matched n over several random draws.

Run-agnostic: nothing here is O4a-specific.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import matplotlib
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from src.core.patch_scorer import PatchScorer
from src.core.preprocessor import generate_qtransform
from src.core.utils import setup_logger, get_reference_dir
from src.pipeline_v2_production.build_native_index import (
    _candidate_exclusions, iter_clean_segments,
)

logger = setup_logger(__name__)

SEGMENT_LENGTH = 32.0
D_CUT = 0.25              # = 1 - rho_trans, rho_trans = 0.75
EXCLUSION_PAD = 96.0      # same as the native index build


def _mil_vector(scorer: PatchScorer, tsw) -> np.ndarray:
    """Production MIL encoding of a whitened 32 s window (cividis domain)."""
    q = generate_qtransform(tsw)
    rgb = (matplotlib.colormaps['cividis'](np.clip(q, 0.0, 1.0))[..., :3]
           * 255).astype(np.uint8)
    res = scorer.score_spectrogram([rgb], threshold=0.0)[0]
    return np.asarray(res['mil_vector'], dtype=np.float32).ravel()


def _make_scorer(run: str) -> PatchScorer:
    """Same reference index and construction as the production scoring path."""
    return PatchScorer(
        reference_index_path=str(get_reference_dir()
                                 / f'patch_compressed_index_{run.lower()}_ex.npz'),
        verify_md5=False)


def collect_background_mil(run: str, n_segments: int = 3000, seed: int = 42,
                           aggregated_dir: Path = Path('data/production/aggregated'),
                           resume: bool = True) -> np.ndarray:
    """Encode unselected native background segments through the MIL path."""
    out = Path(aggregated_dir) / f'background_mil_vectors_{run.lower()}.npy'
    if resume and out.exists():
        prev = np.load(out)
        if len(prev) >= n_segments:
            logger.info(f"reusing {len(prev)} cached background MIL vectors")
            return prev
        logger.info(f"resuming from {len(prev)} cached vectors")
    else:
        prev = np.empty((0, 384), dtype=np.float32)

    exclusions = np.array(_candidate_exclusions(run, Path(aggregated_dir)))

    def is_excluded(t_bg: float) -> bool:
        if len(exclusions) == 0:
            return False
        return bool(np.any((exclusions - EXCLUSION_PAD - 16 <= t_bg)
                           & (t_bg <= exclusions + 32 + EXCLUSION_PAD + 16)))

    scorer = _make_scorer(run)
    vecs = list(prev)
    per_det = n_segments // 2
    n_excluded = n_failed = 0

    for det_i, det in enumerate(['H1', 'L1']):
        got = 0
        # Ask for generous headroom: exclusions and fetch failures both bite.
        for seg in iter_clean_segments(run.lower(), det, per_det * 3,
                                       seed=seed + det_i):
            if got >= per_det or len(vecs) >= n_segments:
                break
            if is_excluded(seg.t_bg):
                n_excluded += 1
                continue
            try:
                tsw = seg.ts_whitened.crop(seg.t_bg - 16, seg.t_bg + 16)
                vecs.append(_mil_vector(scorer, tsw))
                got += 1
            except Exception as e:            # noqa: BLE001 - fail-soft per segment
                n_failed += 1
                logger.debug(f"[{det}] segment {seg.t_bg} failed: {e}")
                continue
            if len(vecs) % 100 == 0:
                np.save(out, np.stack(vecs))
                logger.info(f"{len(vecs)}/{n_segments} background segments encoded")

    X = np.stack(vecs)
    np.save(out, X)
    logger.info(f"collected {len(X)} background MIL vectors "
                f"({n_excluded} candidate-adjacent, {n_failed} failed) -> {out}")
    return X


def _load_candidate_mil(production_dir: Path, aggregated_dir: Path, run_name: str):
    """Candidate MIL vectors keyed by (gps, detector), joined to the taxonomy."""
    vec = {}
    for f in sorted(Path(production_dir).glob('*/novelties_*.h5')):
        det = f.stem.rsplit('_', 1)[1]
        with h5py.File(f, 'r') as h:
            if 'novelties' not in h or 'mil_vectors' not in h['novelties']:
                continue
            g = h['novelties']
            for t, v in zip(g['gps_times'][:], g['mil_vectors'][:]):
                vec[(int(round(t)), det)] = v
    m = pd.read_csv(Path(aggregated_dir) / f'Master_Taxonomy_{run_name}.csv')
    m['key'] = list(zip(m.gps_start.round().astype(int), m.detector))
    m = m[m.key.map(lambda k: k in vec)]
    return m, vec


def cluster_profile(X: np.ndarray) -> dict:
    """Single-linkage cosine HAC cut at D_CUT; cluster size profile."""
    Xn = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)
    Z = linkage(pdist(Xn, metric='cosine'), method='single')
    sizes = np.sort(np.bincount(fcluster(Z, t=D_CUT, criterion='distance'))[1:])[::-1]
    return {
        'n': int(len(X)),
        'n_clusters': int(len(sizes)),
        'largest': int(sizes[0]),
        'largest_frac': float(sizes[0] / len(X)),
        'n_singletons': int((sizes == 1).sum()),
    }


def run(run_name: str = 'O4a', n_segments: int = 3000, n_draws: int = 5,
        seed: int = 42,
        aggregated_dir: str | Path = 'data/production/aggregated',
        production_dir: str | Path = 'data/production') -> dict:
    agg = Path(aggregated_dir)

    bg = collect_background_mil(run_name, n_segments, seed, agg)
    m, vec = _load_candidate_mil(Path(production_dir), agg, run_name)

    groups = {'NATIVE_BACKGROUND': bg}
    for cls in ['ROBUST', 'AMBIGUOUS', 'BACKGROUND']:
        sel = m[m.robustness_class == cls]
        if len(sel):
            groups[cls] = np.stack([vec[k] for k in sel.key])

    out = {'run': run_name, 'D_cut': D_CUT, 'rho_trans': 1 - D_CUT,
           'full': {}, 'size_matched': {}}
    for cls, X in groups.items():
        out['full'][cls] = cluster_profile(X)
        logger.info(f"FULL {cls:18s} {out['full'][cls]}")

    n_match = min(len(X) for X in groups.values())
    out['n_matched'] = int(n_match)
    for cls, X in groups.items():
        profs = []
        for s in range(n_draws):
            idx = np.random.default_rng(s).choice(len(X), n_match, replace=False)
            profs.append(cluster_profile(X[idx]))
        lf = np.array([p['largest_frac'] for p in profs])
        nc = np.array([p['n_clusters'] for p in profs])
        out['size_matched'][cls] = {
            'n': int(n_match),
            'largest_frac_mean': float(lf.mean()),
            'largest_frac_std': float(lf.std()),
            'n_clusters_mean': float(nc.mean()),
            'n_clusters_std': float(nc.std()),
        }
        logger.info(f"MATCHED {cls:18s} largest={lf.mean():.3%} +/- {lf.std():.3%} "
                    f"clusters={nc.mean():.1f}")

    dest = agg / f'background_cohesion_{run_name.lower()}.json'
    dest.write_text(json.dumps(out, indent=1))
    logger.info(f"saved -> {dest}")
    return out


if __name__ == '__main__':
    p = argparse.ArgumentParser(
        description='Macro-cluster cohesion vs. true native background')
    p.add_argument('--run', default='O4a')
    p.add_argument('--n_segments', type=int, default=3000)
    p.add_argument('--n_draws', type=int, default=5)
    p.add_argument('--seed', type=int, default=42)
    a = p.parse_args()
    run(a.run, a.n_segments, a.n_draws, a.seed)
