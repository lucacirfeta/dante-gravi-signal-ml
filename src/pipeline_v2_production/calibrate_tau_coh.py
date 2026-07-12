"""Run-agnostic EVT calibration of the cross-detector cohesion threshold.

For any observing run, estimates the null distribution of H1/L1 MIL-vector
cosine similarity on TIME-SHIFTED background pairs (no physical coincidence
possible) and derives tau_coh at a target false-coincidence probability via
Peaks-Over-Threshold (GPD tail fit above the empirical p90).

Statistical note: the project-wide ban on GEV concerns block-maxima fits on
ViT patch scores, whose overlapping receptive fields violate independence.
Here each observation is ONE cosine similarity between two disjoint,
guard-separated, time-shifted windows: pairs are independent by
construction, so a POT tail fit is legitimate. The empirical quantile is
reported alongside as a non-parametric cross-check.

Output: an entry in config/cross_detector_threshold.json
  {run: {tau_coh, xi, sigma, p90, n_pairs, method, calibrated: true}}
consumed by cross_detector_veto, which REFUSES uncalibrated entries.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.core.utils import setup_logger, normalize_spectrogram
from src.pipeline_v3_multiscale.norm_leakage.common import (
    PatchEncoder, iter_clean_segments, raw_qgram, spectrogram_to_rgb,
)

logger = setup_logger(__name__)

CFG_PATH = Path("config/cross_detector_threshold.json")
MIN_SHIFT_S = 128.0  # time shift between H1/L1 windows: kills real coincidence


def _mil_vector(encoder, seg) -> np.ndarray:
    spec = normalize_spectrogram(raw_qgram(
        seg.ts_whitened.crop(seg.t_bg - 16, seg.t_bg + 16)))
    tokens = encoder.encode_rgb(spectrogram_to_rgb(spec))
    v = tokens.mean(axis=0)
    return v / (np.linalg.norm(v) + 1e-12)


def calibrate(run: str, n_pairs: int = 500, seed: int = 42,
              target_p: float = 1e-3) -> dict:
    import scipy.stats as st

    encoder = PatchEncoder()
    logger.info(f"[{run}] Collecting {n_pairs} background segments per detector...")
    h1 = [( s.t_bg, _mil_vector(encoder, s))
          for s in iter_clean_segments(run.lower(), "H1", n_pairs, seed=seed)]
    l1 = [( s.t_bg, _mil_vector(encoder, s))
          for s in iter_clean_segments(run.lower(), "L1", n_pairs, seed=seed + 1)]

    rng = np.random.default_rng(seed)
    sims = []
    for (t_h, v_h) in h1:
        # random partner, re-drawn until the time shift breaks coincidence
        for _ in range(20):
            t_l, v_l = l1[rng.integers(0, len(l1))]
            if abs(t_h - t_l) >= MIN_SHIFT_S:
                sims.append(float(np.dot(v_h, v_l)))
                break
    sims = np.array(sims)
    if len(sims) < 200:
        raise RuntimeError(f"Only {len(sims)} valid null pairs — refusing to "
                           "calibrate a tail threshold on so few points.")

    p90 = float(np.percentile(sims, 90))
    exceed = sims[sims > p90] - p90
    xi, loc, sigma = st.genpareto.fit(exceed, floc=0.0)
    # tau at target exceedance probability p: P(S > tau) = 0.10 * P_GPD(exc)
    q = 1.0 - target_p / 0.10
    tau_evt = float(p90 + st.genpareto.ppf(q, xi, loc=0.0, scale=sigma))
    tau_emp = float(np.percentile(sims, 100 * (1 - target_p)))
    # conservative: the larger of tail-fit and empirical quantile
    tau = max(tau_evt, tau_emp)

    entry = {"tau_coh": round(tau, 4), "xi": round(float(xi), 4),
             "sigma": round(float(sigma), 4), "p90": round(p90, 4),
             "tau_evt": round(tau_evt, 4), "tau_empirical": round(tau_emp, 4),
             "n_pairs": int(len(sims)), "target_p": target_p, "seed": seed,
             "method": "POT-GPD over p90, time-shifted null pairs",
             "calibrated": True}

    cfg = json.loads(CFG_PATH.read_text()) if CFG_PATH.exists() else {}
    cfg[run] = entry
    CFG_PATH.write_text(json.dumps(cfg, indent=2))
    logger.info(f"[{run}] tau_coh={tau:.4f} (EVT {tau_evt:.4f} / empirical "
                f"{tau_emp:.4f}, xi={xi:.3f}) -> {CFG_PATH}")
    return entry


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=str, required=True)
    p.add_argument("--n_pairs", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    calibrate(a.run, n_pairs=a.n_pairs, seed=a.seed)
