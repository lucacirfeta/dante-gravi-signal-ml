"""Physical cross-detector coincidence test (primary) with a morphological
patch-overlap check (complementary).

Motivation (audit COINC-3). The original coincidence veto compared the Top-$k$
MIL *aggregate* vectors of the two detectors. That statistic cannot separate a
true coincidence from the null: (a) any two Top-k aggregates already share a
generic "loud patch" structure, giving a high floor (~0.56 mean once the
COINC-2 colormap mismatch is fixed), and (b) for a short transient inside a
32 s window, which 68 of 1369 patches enter the Top-k is largely set by the
*independent* noise in each detector, so the same waveform does not produce the
same patch selection. Measured coincident injections land at ~0.9, inside the
null tail (max ~0.94): the distributions overlap and no threshold separates
them.

This module replaces that statistic with the standard physical one and keeps a
morphological cross-check:

  B (PRIMARY, physical): localize the transient inside the 32 s window using the
    stored Top-k patch columns, band-pass both detectors to the candidate's
    band, and scan the normalized cross-correlation over physically allowed
    lags (|dt| <= light travel time between the sites + margin). Answers "is
    this the same event in both detectors?".

  A (COMPLEMENTARY, morphological): intersection-over-union of the Top-k patch
    sets of candidate and partner on the time-frequency grid. Answers "is it
    the same shape?".

Both are calibrated against an empirical null built by time-shifting the
partner far beyond the light-travel window, which destroys any real
coincidence while preserving each detector's noise character.

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
from scipy.signal import butter, sosfiltfilt

from src.core.data_loader import fetch_local_or_remote_strain
from src.core.patch_scorer import PatchScorer
from src.core.preprocessor import (
    whiten_context, extract_clean_subwindow, generate_qtransform,
)
from src.core.utils import setup_logger, get_reference_dir

logger = setup_logger(__name__)

SEGMENT_LENGTH = 32.0
PATCH_GRID = 37                  # 37x37 = 1369 patches
SPEC_FRANGE = (20.0, 2048.0)     # q-transform frequency span
LIGHT_TRAVEL_S = 0.010002        # LHO <-> LLO
LAG_MARGIN_S = 0.002             # tolerance on top of light travel
NULL_SHIFTS_S = (1.0, 2.0, 4.0, 8.0, -1.0, -2.0, -4.0, -8.0)


def _patch_time_band(top_k_idx: np.ndarray) -> tuple[float, float, float]:
    """Localize a trigger from its Top-k patch indices.

    Returns (t_offset_s within the 32 s window, f_lo, f_hi) using the median
    patch column for time and the patch row span for the frequency band.
    """
    cols = np.asarray(top_k_idx) % PATCH_GRID
    rows = np.asarray(top_k_idx) // PATCH_GRID
    t_off = float((np.median(cols) + 0.5) / PATCH_GRID * SEGMENT_LENGTH)
    # q-transform frequency axis is log-spaced over SPEC_FRANGE
    lo_f, hi_f = np.log10(SPEC_FRANGE[0]), np.log10(SPEC_FRANGE[1])
    r_lo, r_hi = np.percentile(rows, [10, 90])
    f_lo = 10 ** (lo_f + (r_lo / PATCH_GRID) * (hi_f - lo_f))
    f_hi = 10 ** (lo_f + ((r_hi + 1) / PATCH_GRID) * (hi_f - lo_f))
    # widen and clamp: the band only suppresses out-of-band noise
    f_lo = max(SPEC_FRANGE[0], f_lo / 1.5)
    f_hi = min(SPEC_FRANGE[1] * 0.95, f_hi * 1.5)
    if f_hi <= f_lo * 1.1:
        f_lo, f_hi = SPEC_FRANGE[0], SPEC_FRANGE[1] * 0.95
    return t_off, float(f_lo), float(f_hi)


def _whitened(detector: str, gps: float):
    ts = fetch_local_or_remote_strain(detector, gps - 4.0, gps + SEGMENT_LENGTH + 4.0,
                                      cache_raw=False, edge_tolerance=4.0)
    tw, _ = whiten_context(ts, gps, gps + SEGMENT_LENGTH, pad=4.0)
    return extract_clean_subwindow(tw, gps, gps + SEGMENT_LENGTH)


def _bandpass(x: np.ndarray, fs: float, f_lo: float, f_hi: float) -> np.ndarray:
    nyq = fs / 2.0
    lo, hi = max(f_lo / nyq, 1e-4), min(f_hi / nyq, 0.99)
    if hi <= lo:
        return x
    sos = butter(4, [lo, hi], btype='band', output='sos')
    return sosfiltfilt(sos, x)


def _max_normxcorr(x: np.ndarray, y: np.ndarray, fs: float,
                   max_lag_s: float) -> float:
    """Max |normalized cross-correlation| of x,y over |lag| <= max_lag_s."""
    x = x - x.mean()
    y = y - y.mean()
    nx, ny = np.linalg.norm(x), np.linalg.norm(y)
    if nx == 0 or ny == 0:
        return 0.0
    max_lag = int(round(max_lag_s * fs))
    best = 0.0
    n = min(len(x), len(y))
    x, y = x[:n], y[:n]
    for lag in range(-max_lag, max_lag + 1):
        if lag < 0:
            a, b = x[-lag:], y[:n + lag]
        elif lag > 0:
            a, b = x[:n - lag], y[lag:]
        else:
            a, b = x, y
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na == 0 or nb == 0:
            continue
        best = max(best, abs(float(np.dot(a, b) / (na * nb))))
    return best


def _topk_idx(scorer: PatchScorer, detector: str, gps: float):
    """Top-k patch indices of a detector window (cividis domain, as production)."""
    tsw = _whitened(detector, gps)
    q = generate_qtransform(tsw)
    rgb = (matplotlib.colormaps['cividis'](np.clip(q, 0.0, 1.0))[..., :3]
           * 255).astype(np.uint8)
    res = scorer.score_spectrogram([rgb], threshold=0.0)[0]
    return np.asarray(res['top_k_indices']).ravel()


def analyze_candidate(scorer, det: str, partner: str, gps: float,
                      top_k_idx: np.ndarray, half_window_s: float = 0.5,
                      with_iou: bool = True):
    """Return the physical (B) and morphological (A) coincidence statistics."""
    t_off, f_lo, f_hi = _patch_time_band(top_k_idx)

    ts_d = _whitened(det, gps)
    ts_p = _whitened(partner, gps)
    fs = float(1.0 / ts_d.dt.value)

    def seg(ts, extra_shift=0.0):
        c = t_off + extra_shift
        lo = max(0.0, c - half_window_s)
        hi = min(SEGMENT_LENGTH, c + half_window_s)
        a = int(lo * fs)
        b = int(hi * fs)
        v = np.asarray(ts.value)[a:b]
        return _bandpass(v, fs, f_lo, f_hi)

    x = seg(ts_d)
    y = seg(ts_p)
    max_lag = LIGHT_TRAVEL_S + LAG_MARGIN_S
    cc_on = _max_normxcorr(x, y, fs, max_lag)

    # empirical null: partner shifted far beyond the light-travel window
    cc_null = []
    for sh in NULL_SHIFTS_S:
        if 0.0 <= t_off + sh - half_window_s and t_off + sh + half_window_s <= SEGMENT_LENGTH:
            cc_null.append(_max_normxcorr(x, seg(ts_p, sh), fs, max_lag))

    out = {
        'gps': float(gps), 'detector': det, 'partner': partner,
        't_offset_s': t_off, 'f_lo': f_lo, 'f_hi': f_hi,
        'cc_onsource': float(cc_on),
        'cc_null_mean': float(np.mean(cc_null)) if cc_null else None,
        'cc_null_max': float(np.max(cc_null)) if cc_null else None,
        'n_null': len(cc_null),
    }

    # A: morphological patch overlap (IoU) against the partner encoding
    out['patch_iou'] = None
    if with_iou:
        try:
            p_idx = _topk_idx(scorer, partner, gps)
            a, b = set(np.asarray(top_k_idx).tolist()), set(p_idx.tolist())
            out['patch_iou'] = len(a & b) / max(1, len(a | b))
        except Exception as e:
            logger.debug(f'patch IoU failed for {gps} {det}: {e}')
    return out


def run(run_name: str = 'O4a', n_candidates: int = 200, seed: int = 42,
        aggregated_dir: str | Path = 'data/production/aggregated',
        production_dir: str | Path = 'data/production',
        with_iou: bool = True, resume: bool = True):
    """Apply the coincidence test. n_candidates=0 means the FULL pool.

    Results are checkpointed so a long run can be resumed; the output JSON is
    self-describing and readable standalone.
    """
    from tqdm import tqdm

    agg, prod = Path(aggregated_dir), Path(production_dir)
    tax = pd.read_csv(agg / f'Master_Taxonomy_{run_name}.csv')
    rng = np.random.default_rng(seed)
    if n_candidates and len(tax) > n_candidates:
        tax = tax.iloc[rng.choice(len(tax), n_candidates, replace=False)]

    out_path = agg / f'coincidence_physical_{run_name.lower()}.json'
    rows = []
    seen = set()
    if resume and out_path.exists():
        try:
            prev = json.loads(out_path.read_text()).get('events', [])
            rows = list(prev)
            seen = {(e['gps'], e['detector']) for e in prev}
            logger.info(f'resuming: {len(seen)} events already measured')
        except Exception:
            rows, seen = [], set()

    scorer = PatchScorer(
        reference_index_path=str(get_reference_dir()
                                 / f'patch_compressed_index_{run_name.lower()}_ex.npz'),
        verify_md5=False)

    todo = [r for _, r in tax.iterrows()
            if (float(r['gps_start']), r['detector']) not in seen]
    for i, r in enumerate(tqdm(todo, desc='physical coincidence')):
        det, gps, sess = r['detector'], float(r['gps_start']), r['session_id']
        partner = 'L1' if det == 'H1' else 'H1'
        try:
            with h5py.File(prod / str(sess) / f'novelties_{sess}_{det}.h5', 'r') as f:
                gt = f['novelties/gps_times'][:]
                tk = f['novelties/top_k_idx'][:]
            m = np.where(gt == gps)[0]
            if not len(m):
                continue
            rows.append(analyze_candidate(scorer, det, partner, gps, tk[m[0]],
                                          with_iou=with_iou))
        except Exception as e:
            logger.debug(f'skip {gps} {det}: {e}')
        if (i + 1) % 100 == 0:
            out_path.write_text(json.dumps({'partial': True, 'events': rows}, indent=1))

    df = pd.DataFrame(rows)
    on = df['cc_onsource'].values
    nul = df['cc_null_max'].dropna().values
    thr = float(np.percentile(nul, 99)) if len(nul) else float('nan')
    summary = {
        'run': run_name, 'n': int(len(df)),
        'cc_onsource_mean': float(on.mean()), 'cc_onsource_max': float(on.max()),
        'cc_null_max_p99': thr,
        'n_exceeding': int((on > thr).sum()) if np.isfinite(thr) else None,
        'patch_iou_mean': float(df['patch_iou'].dropna().mean()) if df['patch_iou'].notna().any() else None,
        'light_travel_s': LIGHT_TRAVEL_S, 'lag_margin_s': LAG_MARGIN_S,
    }
    out = agg / f'coincidence_physical_{run_name.lower()}.json'
    out.write_text(json.dumps({'summary': summary, 'events': rows}, indent=1))
    logger.info(json.dumps(summary, indent=2))
    logger.info(f'saved {out}')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Physical cross-detector coincidence test')
    p.add_argument('--run', default='O4a')
    p.add_argument('--n', type=int, default=200, help='0 = full pool')
    p.add_argument('--no-iou', action='store_true')
    p.add_argument('--no-resume', action='store_true')
    p.add_argument('--seed', type=int, default=42)
    a = p.parse_args()
    run(a.run, n_candidates=a.n, seed=a.seed,
        with_iou=not a.no_iou, resume=not a.no_resume)
