"""Run-agnostic calibration of the cross-detector cohesion threshold tau_coh.

The cross-detector veto (cross_detector_veto.py) flags a candidate as
coincident when the cosine similarity between the candidate's Top-k MIL vector
(v1) and the partner detector's Top-k MIL vector (v2) exceeds tau_coh. This
calibrator therefore builds the null on the SAME statistic the veto applies:

  null = similarity( candidate-anomaly Top-k MIL,  partner-detector background
                     Top-k MIL )

i.e. an anomaly in one detector against a NON-coincident partner window in the
other. This is the correct null hypothesis ("the candidate has no coincident
counterpart"). Two earlier versions of this file mis-specified the null and
mis-matched the vector definition (audit COINC-1, see below), which inflated
tau_coh to a value the applied Top-k similarity can never reach, leaving the
veto without discriminating power.

  audit COINC-1 (fixed here):
    * vector: was tokens.mean(axis=0) (mean over ALL 1369 patches); the veto
      applies score_spectrogram's Top-k=68 MIL vector. Now matched.
    * null pairs: was background-vs-background; the applied comparison is
      anomaly-vs-background. Now matched.
    * threshold: now a FAMILY-WISE quantile over the whole candidate pool,
      so zero surrogates are expected to fire across the run, and injected
      coincident signals (identical waveform in both detectors) --- whose
      Top-k similarity is ~0.9 --- clear it with margin.

Output: an entry in config/cross_detector_threshold.json, consumed by
cross_detector_veto, which REFUSES uncalibrated entries.
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

import h5py
import matplotlib
import numpy as np

from src.core.data_loader import fetch_local_or_remote_strain
from src.core.patch_scorer import PatchScorer
from src.core.preprocessor import (
    whiten_context, extract_clean_subwindow, generate_qtransform,
)
from src.core.utils import setup_logger, get_reference_dir

logger = setup_logger(__name__)

CFG_PATH = Path("config/cross_detector_threshold.json")
SEGMENT_LENGTH = 32


def _bg_topk_vector(scorer: PatchScorer, detector: str, seg_start: int) -> np.ndarray:
    """Top-k MIL vector of a clean background window (matches the veto path)."""
    seg_end = seg_start + SEGMENT_LENGTH
    ts = fetch_local_or_remote_strain(detector, seg_start - 4.0, seg_end + 4.0,
                                      edge_tolerance=4.0)
    ts_w, _ = whiten_context(ts, seg_start, seg_end, pad=4.0)
    ts_bp = extract_clean_subwindow(ts_w, seg_start, seg_end)
    q = generate_qtransform(ts_bp, output_size=(256, 256))
    rgb = (matplotlib.colormaps["cividis"](np.clip(q, 0.0, 1.0))[..., :3]
           * 255).astype(np.uint8)
    v = np.asarray(scorer.score_spectrogram([rgb], threshold=0.0)[0]["mil_vector"],
                   dtype=np.float64)
    return v / (np.linalg.norm(v) + 1e-12)


def _candidate_anomaly_vectors(production_dir: Path, max_n: int, seed: int):
    """Real flagged-candidate Top-k MIL vectors (anomalies) from production HDF5."""
    rng = np.random.default_rng(seed)
    files = sorted(glob.glob(str(production_dir / "*" / "novelties_*_*.h5")))
    vecs = []
    for f in files:
        try:
            with h5py.File(f, "r") as hf:
                mv = hf["novelties/mil_vectors"][:]
            for v in mv:
                v = np.asarray(v, dtype=np.float64)
                vecs.append(v / (np.linalg.norm(v) + 1e-12))
        except Exception:
            continue
    vecs = np.array(vecs)
    if len(vecs) > max_n:
        vecs = vecs[rng.choice(len(vecs), max_n, replace=False)]
    return vecs


def _discover(detector: str):
    from src.pipeline_v2_production.dsd_injection_test import _DATA_DIRECTORIES
    starts = []
    for d in _DATA_DIRECTORIES:
        if not Path(d).exists():
            continue
        for f in Path(d).rglob(f"{detector}_*.hdf5"):
            parts = f.stem.split("_")
            if len(parts) >= 3:
                try:
                    a, b = int(parts[1]), int(parts[2])
                    starts += list(range(a, b - SEGMENT_LENGTH, SEGMENT_LENGTH))
                except ValueError:
                    pass
    return starts


def calibrate(run: str, n_anomaly: int = 800, n_background: int = 200,
              seed: int = 42, family_alpha: float = 0.1,
              production_dir: str | Path = "data/production") -> dict:
    import scipy.stats as st
    from tqdm import tqdm

    rng = np.random.default_rng(seed)
    idx = get_reference_dir() / f"patch_compressed_index_{run.lower()}_ex.npz"
    scorer = PatchScorer(reference_index_path=str(idx), verify_md5=False)

    # 1. Anomaly Top-k vectors (real flagged candidates).
    anomalies = _candidate_anomaly_vectors(Path(production_dir), n_anomaly, seed)
    logger.info(f"[{run}] anomaly vectors: {len(anomalies)}")

    # 2. Partner-detector background Top-k vectors (per detector).
    bg = {}
    for det in ["H1", "L1"]:
        starts = _discover(det)
        picks = rng.choice(starts, size=min(n_background, len(starts)), replace=False)
        vs = []
        for s in tqdm(picks, desc=f"bg {det}", leave=False):
            try:
                vs.append(_bg_topk_vector(scorer, det, int(s)))
            except Exception as e:
                logger.debug(f"[{det}] bg {s} skipped: {e}")
        bg[det] = np.array(vs)
        logger.info(f"[{run}] {det} background vectors: {len(bg[det])}")

    # 3. Null: each anomaly vs a random partner-detector background window.
    #    (anomaly detector is unknown per stored vector; compare against both
    #    detector backgrounds, which is conservative and symmetric.)
    allbg = np.vstack([bg["H1"], bg["L1"]])
    sims = (anomalies @ allbg.T).ravel()
    if len(sims) < 2000:
        raise RuntimeError(f"Only {len(sims)} null pairs — too few to calibrate.")

    # 4. Family-wise threshold: POT-GPD to a whole-pool exceedance target, so
    #    < family_alpha surrogates are expected to fire across the candidate pool.
    n_pool = len(anomalies)
    target_p = family_alpha / max(n_pool, 1)
    p90 = float(np.percentile(sims, 90))
    exceed = sims[sims > p90] - p90
    xi, loc, sigma = st.genpareto.fit(exceed, floc=0.0)
    q = 1.0 - target_p / 0.10
    tau_evt = float(p90 + st.genpareto.ppf(min(q, 1 - 1e-12), xi, loc=0.0, scale=sigma))
    tau_emp = float(sims.max())
    tau = float(max(tau_evt, tau_emp))  # never below the observed null max

    entry = {"tau_coh": round(tau, 4), "xi": round(float(xi), 4),
             "sigma": round(float(sigma), 4), "p90": round(p90, 4),
             "tau_evt": round(tau_evt, 4), "null_max": round(tau_emp, 4),
             "null_mean": round(float(sims.mean()), 4),
             "n_anomaly": int(n_pool), "n_background": int(len(allbg)),
             "n_null_pairs": int(len(sims)), "family_alpha": family_alpha,
             "seed": seed,
             "method": "family-wise POT-GPD on Top-k anomaly-vs-background null",
             "vector": "topk_mil", "calibrated": True}

    cfg = json.loads(CFG_PATH.read_text()) if CFG_PATH.exists() else {}
    cfg[run] = entry
    CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CFG_PATH.write_text(json.dumps(cfg, indent=2))
    logger.info(f"[{run}] tau_coh={tau:.4f} (EVT {tau_evt:.4f} / null_max "
                f"{tau_emp:.4f}, xi={xi:.3f}, null_mean {sims.mean():.3f}) "
                f"-> {CFG_PATH}")
    return entry


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=str, required=True)
    p.add_argument("--n_anomaly", type=int, default=800)
    p.add_argument("--n_background", type=int, default=200)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--family_alpha", type=float, default=0.1)
    a = p.parse_args()
    calibrate(a.run, n_anomaly=a.n_anomaly, n_background=a.n_background,
              seed=a.seed, family_alpha=a.family_alpha)
