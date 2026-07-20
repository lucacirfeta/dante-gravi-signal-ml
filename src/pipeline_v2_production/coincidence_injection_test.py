"""P3 --- Dual-detector coincidence-veto power test.

    !!! MEASURES THE RETIRED STATISTIC — NOT A SUBSTITUTE FOR epsilon_coh !!!
    This module measures recovery of the Top-k MIL embedding similarity against
    tau_coh. That statistic was retired under audit COINC-3, so these numbers do
    NOT characterise the coincidence test the pipeline actually applies. For the
    recovery efficiency of the statistic in force, use
    `coincidence_physical_efficiency.py` — and note that it must localize the
    transient to the same +-0.5 s window production uses, or short morphologies
    are diluted to zero recovery. Kept here to reproduce the superseded analysis.


The cross-detector coincidence veto (calibrate_tau_coh.py, cross_detector_veto.py)
flags a candidate as coincident when the cosine similarity between the H1 and L1
MIL vectors exceeds tau_coh = 0.975. The zero-detection result over the O4a pool
tells us nothing about the veto's POWER unless we know that a genuine coincident
signal --- the SAME waveform in both detectors on top of independent noise ---
actually produces similarity > tau_coh.

This module measures that power directly: it injects one synthetic waveform into
BOTH detectors (independent clean background), encodes each through the production
MIL path (cividis Q-gram -> DINOv2 -> Top-k MIL vector), and records the
cross-detector similarity as a function of injected SNR. A null control (no
injection, random H1/L1 clean pairs) is measured first and validated against the
known background distribution (mean ~0.33, max ~0.53 from veto_similarity_cache).

Reusable for any run: the native index and data directories resolve by run name,
exactly like build_native_index.py.
"""

from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path

import matplotlib
import numpy as np
import torch
from tqdm import tqdm

from src.core.data_loader import fetch_local_or_remote_strain
from src.core.injection import InjectionEngine, SyntheticGlitchGenerator
from src.core.patch_scorer import PatchScorer
from src.core.preprocessor import (
    whiten_context, extract_clean_subwindow, generate_qtransform,
)
from src.core.utils import setup_logger, get_reference_dir

logger = setup_logger(__name__)

SAMPLE_RATE = 4096
SEGMENT_LENGTH = 32
_CFG = Path("config/cross_detector_threshold.json")


def _tau_coh(run: str) -> float:
    """Read the calibrated coincidence threshold for this run from config."""
    cfg = json.loads(_CFG.read_text())
    return float(cfg[run]["tau_coh"])


def _mil_vector(scorer: PatchScorer, detector: str, seg_start: int,
                glitch: np.ndarray | None):
    """Fetch clean strain, optionally inject a glitch, return (L2 MIL vector, SNR)."""
    seg_end = seg_start + SEGMENT_LENGTH
    ts_super = fetch_local_or_remote_strain(
        detector, seg_start - 4.0, seg_end + 4.0, edge_tolerance=4.0)
    snr = 0.0
    if glitch is not None:
        injector = InjectionEngine(sample_rate=SAMPLE_RATE)
        t_inject = seg_start + SEGMENT_LENGTH / 2.0
        snr = float(injector.compute_snr(
            ts_super.crop(seg_start, seg_end), glitch))
        ts_super = injector.inject(ts_super, glitch, t_inject)
    ts_w, _ = whiten_context(ts_super, seg_start, seg_end, pad=4.0)
    ts_bp = extract_clean_subwindow(ts_w, seg_start, seg_end)
    q = generate_qtransform(ts_bp, output_size=(256, 256))
    rgb = (matplotlib.colormaps["cividis"](np.clip(q, 0.0, 1.0))[..., :3]
           * 255).astype(np.uint8)
    res = scorer.score_spectrogram([rgb], threshold=0.0)[0]
    v = np.asarray(res["mil_vector"], dtype=np.float64)
    return v / (np.linalg.norm(v) + 1e-12), snr


def _discover(detector: str) -> list[int]:
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


def run(run_name: str = "O4a", morphologies=("Blip", "ScatteredLight"),
        amplitudes=None, n_trials: int = 40, n_null: int = 60, seed: int = 42):
    if amplitudes is None:
        amplitudes = np.logspace(-22, -20.5, 6)
    rng = np.random.default_rng(seed)
    tau_coh = _tau_coh(run_name)
    logger.info(f"[{run_name}] using calibrated tau_coh = {tau_coh:.4f}")

    idx_path = get_reference_dir() / f"patch_compressed_index_{run_name.lower()}_ex.npz"
    scorer = PatchScorer(reference_index_path=str(idx_path), verify_md5=False)

    h1 = _discover("H1")
    l1 = _discover("L1")
    logger.info(f"segments: H1={len(h1)}, L1={len(l1)}")
    if len(h1) < 5 or len(l1) < 5:
        raise RuntimeError("Insufficient local strain segments for both detectors.")

    def safe_vec(det, pool, glitch):
        """Draw a random segment, skipping those with gaps/NaNs, return (v, snr)."""
        for _ in range(12):
            try:
                return _mil_vector(scorer, det, int(rng.choice(pool)), glitch)
            except Exception as e:
                logger.debug(f"[{det}] segment skipped: {e}")
        return None, None

    gen = SyntheticGlitchGenerator(sample_rate=SAMPLE_RATE)

    # ---- NULL control: NON-coincident anomaly. A glitch is injected into ONE
    # detector only (H1) so its Top-k MIL vector is a genuine anomaly, and it is
    # compared against a CLEAN partner (L1) background. This matches the veto's
    # applied statistic (candidate-anomaly vs partner-background) and should
    # reproduce the empirical veto cache (~0.33 mean, ~0.53 max). Comparing two
    # clean backgrounds would be the WRONG null (candidates are never clean
    # background) and sits much higher on the Top-k scale.
    null_sims = []
    pbar = tqdm(total=n_null, desc="null (anomaly vs bg)")
    while len(null_sims) < n_null:
        g = gen.generate("Blip", 10 ** rng.uniform(-21.5, -20.5), duration=1.0)
        vh, _ = safe_vec("H1", h1, g)      # anomaly in H1
        vl, _ = safe_vec("L1", l1, None)   # clean background in L1
        if vh is None or vl is None:
            break
        null_sims.append(float(np.dot(vh, vl)))
        pbar.update(1)
    pbar.close()
    null_sims = np.array(null_sims)
    logger.info(f"NULL similarity: mean={null_sims.mean():.3f} "
                f"max={null_sims.max():.3f} (expect ~0.33 / ~0.53)")

    rows = []
    for morph in morphologies:
        for amp in amplitudes:
            sims, snrs = [], []
            pbar = tqdm(total=n_trials, desc=f"{morph} {amp:.1e}", leave=False)
            attempts = 0
            while len(sims) < n_trials and attempts < n_trials * 4:
                attempts += 1
                glitch = gen.generate(morph, amp, duration=1.0)
                vh, sh = safe_vec("H1", h1, glitch)
                vl, sl = safe_vec("L1", l1, glitch)
                if vh is None or vl is None:
                    continue
                sims.append(float(np.dot(vh, vl)))
                snrs.append(0.5 * (sh + sl))
                pbar.update(1)
            pbar.close()
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            if not sims:
                continue
            sims = np.array(sims)
            rows.append({
                "morphology": morph, "amplitude": float(amp),
                "snr_mean": float(np.mean(snrs)), "snr_std": float(np.std(snrs)),
                "sim_mean": float(sims.mean()), "sim_max": float(sims.max()),
                "recovery_rate": float(np.mean(sims > tau_coh)),
                "n": int(len(sims)),
            })
            logger.info(f"{morph} amp={amp:.1e} SNR~{rows[-1]['snr_mean']:.0f} "
                        f"sim_mean={sims.mean():.3f} sim_max={sims.max():.3f} "
                        f"recovery(>{tau_coh:.3f})={rows[-1]['recovery_rate']:.2f}")

    out = {
        "tau_coh": tau_coh,
        "null_mean": float(null_sims.mean()), "null_max": float(null_sims.max()),
        "null_p90": float(np.percentile(null_sims, 90)), "n_null": int(len(null_sims)),
        "bins": rows,
    }
    dest = Path("data/production/aggregated") / f"coincidence_injection_{run_name.lower()}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(dest, "w"), indent=2)
    logger.info(f"saved {dest}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Dual-detector coincidence-veto power test")
    p.add_argument("--run", default="O4a")
    p.add_argument("--n_trials", type=int, default=40)
    p.add_argument("--n_null", type=int, default=60)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Fast pilot: 1 morphology, 3 amplitudes, few trials.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, morphologies=("Blip",),
            amplitudes=np.logspace(-21.5, -20.5, 3),
            n_trials=8, n_null=12, seed=a.seed)
    else:
        run(a.run, n_trials=a.n_trials, n_null=a.n_null, seed=a.seed)
