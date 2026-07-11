"""Parallel strain-cache warmer for the norm-leakage experiment.

Purely infrastructural: replays the deterministic candidate stream of
iter_clean_segments (same RNG seed, same DQ gates — guard-time and
excess-power vetoes are intentionally NOT replicated, so the prefetched
set is a superset of what the scorer will consume) and downloads the
strain into the local HDF5 cache with 4 threads (gwosc_fetch_threads
hard cap from config.yaml — do not raise, GWOSC rate limit).

Does not compute a single score: statistics are untouched. The consumer
(iter_clean_segments) hits the cache instead of the network.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from src.core.utils import setup_logger
from src.pipeline_v3_multiscale.norm_leakage.common import DETECTOR, RUN_WINDOWS

logger = setup_logger(__name__)

FETCH_THREADS = 4  # config.yaml performance.gwosc_fetch_threads — hard cap


def prefetch(run: str, n_candidates: int, seed: int, detector: str = DETECTOR):
    from gwosc.timeline import get_segments
    from tenacity import retry, wait_exponential, stop_after_attempt
    from src.core.data_loader import fetch_strain_data

    @retry(wait=wait_exponential(multiplier=1, min=2, max=10),
           stop=stop_after_attempt(5))
    def _segs(flag, s, e):
        return get_segments(flag, s, e)

    lo, hi = RUN_WINDOWS[run]
    burst = _segs(f"{detector}_BURST_CAT1", lo, hi)
    data = _segs(f"{detector}_DATA", lo, hi)

    rng = np.random.default_rng(seed)
    targets = []
    attempts = 0
    # generous attempt budget: mirror of iter_clean_segments' budget shape
    while len(targets) < n_candidates and attempts < n_candidates * 400:
        attempts += 1
        t_bg = float(rng.integers(lo + 64, hi - 64))
        w0, w1 = t_bg - 16, t_bg + 16
        if not any(s[0] <= w0 and s[1] >= w1 for s in burst):
            continue
        if not any(s[0] <= w0 and s[1] >= w1 for s in data):
            continue
        targets.append((w0 - 4.0, w1 + 4.0))

    logger.info(f"[{run}/seed={seed}] Prefetching {len(targets)} windows "
                f"with {FETCH_THREADS} threads...")

    def _fetch(win):
        s, e = win
        try:
            fetch_strain_data(detector, s, e, cache_raw=True, edge_tolerance=4.0)
            return True
        except Exception as exc:
            logger.debug(f"prefetch failed [{s}, {e}]: {exc}")
            return False

    ok = 0
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as pool:
        futures = [pool.submit(_fetch, w) for w in targets]
        for i, fut in enumerate(as_completed(futures), 1):
            ok += bool(fut.result())
            if i % 50 == 0:
                logger.info(f"[{run}/seed={seed}] {i}/{len(targets)} "
                            f"({ok} cached)")
    logger.info(f"[{run}/seed={seed}] Prefetch done: {ok}/{len(targets)} cached.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", choices=["o3a", "o4a"], required=True)
    p.add_argument("--n", type=int, required=True,
                   help="candidate count — use ~1.5x the consumer's n to "
                        "cover guard/veto rejections")
    p.add_argument("--seed", type=int, required=True,
                   help="MUST match the consumer's segment seed")
    p.add_argument("--detector", type=str, default=DETECTOR)
    a = p.parse_args()
    prefetch(a.run, a.n, a.seed, a.detector)
