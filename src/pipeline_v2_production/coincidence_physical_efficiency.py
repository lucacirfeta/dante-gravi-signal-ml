"""Coherent recovery efficiency (epsilon_coh) of the PHYSICAL coincidence test.

Why a second injection module. `coincidence_injection_test.py` measures the
recovery of the *superseded* statistic (Top-k MIL embedding similarity against
tau_coh). That statistic was retired under audit COINC-3 because injected
coincident signals land inside its own null. Its efficiency numbers therefore
say nothing about the test actually used in the paper.

This module measures the efficiency of the statistic in force: the normalized
cross-correlation of the whitened, band-passed strains, scanned over the
light-travel lag window (`coincidence_physical.py`). It answers the question a
referee will ask about the null coincidence result -- "would you have seen a
real coincidence?" -- across the morphological space rather than for one class.

Method. For each morphology and amplitude, the SAME waveform is injected into
independent clean H1 and L1 background with a physically allowed relative lag
drawn uniformly from the light-travel window; both segments are whitened,
band-passed to the injected band and cross-correlated exactly as in production.
Recovery is the fraction exceeding tau_cc, the pooled null threshold measured on
real candidates (read from `coincidence_physical_{run}.json`, not hard-coded).

The null control injects into H1 only, leaving L1 clean: a genuine anomaly with
no counterpart, which is what a non-coincident candidate looks like.

Run-agnostic: thresholds and data directories resolve by run name.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import numpy as np
import torch
from tqdm import tqdm

from src.core.data_loader import fetch_local_or_remote_strain
from src.core.injection import InjectionEngine, SyntheticGlitchGenerator
from src.core.preprocessor import whiten_context, extract_clean_subwindow
from src.core.utils import setup_logger
from src.pipeline_v2_production.coincidence_injection_test import _discover
from src.pipeline_v2_production.coincidence_physical import (
    LAG_MARGIN_S, LIGHT_TRAVEL_S, _bandpass, _max_normxcorr,
)

logger = setup_logger(__name__)

SAMPLE_RATE = 4096
SEGMENT_LENGTH = 32

# Broad morphological coverage: short/impulsive, swept, narrowband, structured.
DEFAULT_MORPHOLOGIES = (
    "Blip", "AsymBlip", "KoiFish", "Whistle", "ScatteredLight",
    "NarrowChirp", "HarmonicComb", "ZSweep", "Butterfly", "NoiseBlob",
)


def _tau_cc(run: str, aggregated_dir: Path) -> float:
    """Pooled null threshold measured on real candidates for this run."""
    p = Path(aggregated_dir) / f"coincidence_physical_{run.lower()}.json"
    thr = json.loads(p.read_text())["summary"]["cc_null_max_p99"]
    logger.info(f"[{run}] tau_cc = {thr:.4f} (from {p.name})")
    return float(thr)


def _whitened_with_injection(detector: str, seg_start: int,
                             glitch: np.ndarray | None,
                             t_shift_s: float = 0.0):
    """Clean strain, optional injection at window centre (+ lag), whitened."""
    seg_end = seg_start + SEGMENT_LENGTH
    ts = fetch_local_or_remote_strain(
        detector, seg_start - 4.0, seg_end + 4.0, edge_tolerance=4.0)
    snr = 0.0
    if glitch is not None:
        injector = InjectionEngine(sample_rate=SAMPLE_RATE)
        snr = float(injector.compute_snr(ts.crop(seg_start, seg_end), glitch))
        ts = injector.inject(ts, glitch,
                             seg_start + SEGMENT_LENGTH / 2.0 + t_shift_s)
    tw, _ = whiten_context(ts, seg_start, seg_end, pad=4.0)
    return extract_clean_subwindow(tw, seg_start, seg_end), snr


def _cc_pair(h_start: int, l_start: int, glitch, band, rng,
             coincident: bool = True,
             half_window_s: float = 0.5) -> tuple[float, float] | None:
    """Cross-correlation of an injected pair. Returns (cc, mean SNR) or None.

    Production (`coincidence_physical.analyze_candidate`) localizes the
    transient inside its 32 s window and correlates only a +-half_window_s
    excerpt. Correlating the full window instead would dilute a short glitch
    by a factor ~32/2*half_window and understate the efficiency -- the same
    signal-dilution effect the multi-scale architecture exists to defeat. We
    localize identically here; the injection time is known exactly (window
    centre), which is the noise-free equivalent of the Top-k patch localization
    used on real candidates.
    """
    # A real coincidence arrives with a lag bounded by the light travel time.
    lag = float(rng.uniform(-LIGHT_TRAVEL_S, LIGHT_TRAVEL_S)) if coincident else 0.0
    try:
        th, sh = _whitened_with_injection("H1", h_start, glitch)
        tl, sl = _whitened_with_injection(
            "L1", l_start, glitch if coincident else None, t_shift_s=lag)
    except Exception as e:                    # noqa: BLE001 - fail-soft per trial
        logger.debug(f"pair ({h_start},{l_start}) skipped: {e}")
        return None
    fs = float(SAMPLE_RATE)
    x = _bandpass(np.asarray(th.value, dtype=float), fs, *band)
    y = _bandpass(np.asarray(tl.value, dtype=float), fs, *band)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y))):
        return None
    # Excerpt around the (known) transient position, as production does.
    c = len(x) // 2
    half = int(round(half_window_s * fs))
    lo, hi = max(0, c - half), min(len(x), c + half)
    x, y = x[lo:hi], y[lo:min(len(y), hi)]
    n = min(len(x), len(y))
    if n < 16:
        return None
    cc = _max_normxcorr(x[:n], y[:n], fs, LIGHT_TRAVEL_S + LAG_MARGIN_S)
    return cc, 0.5 * (sh + sl)


def run(run_name: str = "O4a", morphologies=DEFAULT_MORPHOLOGIES,
        amplitudes=None, n_trials: int = 24, n_null: int = 120, seed: int = 42,
        band: tuple[float, float] = (20.0, 1024.0),
        aggregated_dir: str | Path = "data/production/aggregated") -> dict:
    agg = Path(aggregated_dir)
    rng = np.random.default_rng(seed)
    tau = _tau_cc(run_name, agg)
    if amplitudes is None:
        amplitudes = np.logspace(-22, -20.5, 4)

    h1, l1 = _discover("H1"), _discover("L1")
    logger.info(f"segments: H1={len(h1)}, L1={len(l1)}")
    if len(h1) < 5 or len(l1) < 5:
        raise RuntimeError("Insufficient local strain segments for both detectors.")

    gen = SyntheticGlitchGenerator(sample_rate=SAMPLE_RATE)

    # ---- NULL: anomaly in H1 only, clean L1 (a non-coincident candidate) ----
    nulls = []
    pbar = tqdm(total=n_null, desc="null (H1 anomaly vs clean L1)")
    attempts = 0
    while len(nulls) < n_null and attempts < n_null * 4:
        attempts += 1
        g = gen.generate("Blip", 10 ** rng.uniform(-21.5, -20.5), duration=1.0)
        r = _cc_pair(int(rng.choice(h1)), int(rng.choice(l1)), g, band, rng,
                     coincident=False)
        if r is None:
            continue
        nulls.append(r[0])
        pbar.update(1)
    pbar.close()
    nulls = np.array(nulls) if nulls else np.array([np.nan])
    logger.info(f"NULL cc: mean={np.nanmean(nulls):.3f} max={np.nanmax(nulls):.3f} "
                f"| exceeding tau_cc: {float(np.nanmean(nulls > tau)):.1%}")

    rows = []
    for morph in morphologies:
        for amp in amplitudes:
            ccs, snrs, attempts = [], [], 0
            pbar = tqdm(total=n_trials, desc=f"{morph} {amp:.1e}", leave=False)
            while len(ccs) < n_trials and attempts < n_trials * 4:
                attempts += 1
                try:
                    glitch = gen.generate(morph, amp, duration=1.0)
                except Exception as e:        # noqa: BLE001 - unknown morphology
                    logger.warning(f"{morph}: {e}")
                    break
                r = _cc_pair(int(rng.choice(h1)), int(rng.choice(l1)),
                             glitch, band, rng, coincident=True)
                if r is None:
                    continue
                ccs.append(r[0])
                snrs.append(r[1])
                pbar.update(1)
            pbar.close()
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if not ccs:
                continue
            ccs = np.array(ccs)
            rows.append({
                "morphology": morph, "amplitude": float(amp),
                "snr_mean": float(np.mean(snrs)), "snr_std": float(np.std(snrs)),
                "cc_mean": float(ccs.mean()), "cc_median": float(np.median(ccs)),
                "cc_max": float(ccs.max()),
                "epsilon_coh": float(np.mean(ccs > tau)),
                "n": int(len(ccs)),
                # Per-injection values so recovery can be re-thresholded if
                # tau_cc changes, without re-running the campaign.
                "cc_values": [float(c) for c in ccs],
            })
            logger.info(f"{morph} amp={amp:.1e} SNR~{rows[-1]['snr_mean']:.0f} "
                        f"cc_mean={ccs.mean():.3f} eps_coh={rows[-1]['epsilon_coh']:.1%}")
            (agg / f"coincidence_physical_efficiency_{run_name.lower()}.json").write_text(
                json.dumps({"tau_cc": tau, "band": list(band),
                            "null_cc_mean": float(np.nanmean(nulls)),
                            "null_cc_max": float(np.nanmax(nulls)),
                            "null_exceeding_frac": float(np.nanmean(nulls > tau)),
                            "rows": rows}, indent=1))

    out = {"run": run_name, "tau_cc": tau, "band": list(band),
           "null_n": int(len(nulls)),
           "null_cc_mean": float(np.nanmean(nulls)),
           "null_cc_max": float(np.nanmax(nulls)),
           "null_exceeding_frac": float(np.nanmean(nulls > tau)),
           "rows": rows}
    dest = agg / f"coincidence_physical_efficiency_{run_name.lower()}.json"
    dest.write_text(json.dumps(out, indent=1))
    logger.info(f"saved -> {dest}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="epsilon_coh of the physical coincidence statistic")
    p.add_argument("--run", default="O4a")
    p.add_argument("--n_trials", type=int, default=24)
    p.add_argument("--n_null", type=int, default=120)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Fast pilot: 2 morphologies, few trials.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, morphologies=("Blip", "Whistle"),
            amplitudes=np.logspace(-21.5, -20.5, 2),
            n_trials=4, n_null=6, seed=a.seed)
    else:
        run(a.run, n_trials=a.n_trials, n_null=a.n_null, seed=a.seed)
