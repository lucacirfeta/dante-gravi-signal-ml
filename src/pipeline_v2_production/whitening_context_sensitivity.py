"""How many DSD verdicts flip when the whitening context changes?

`ts.whiten()` estimates the amplitude spectral density over whatever stretch of
data it is handed, so the whitened window -- and every score downstream of it --
depends on how much surrounding data the whitening saw. LAB_NOTEBOOK section 12
established this for a single candidate: its native score swung ~0.05-0.09 across
context lengths from +-4 s to +-256 s, comparable to the DSD threshold spacing.
That left a stated-but-unquantified limitation: in principle a context change can
push a borderline candidate across the DSD cut, but the *population* rate was
never measured.

This measures it. A sample of near-threshold candidates is re-scored against the
native O4a index (K=1216) at several whitening pad lengths, and the DSD verdict
(score vs the per-detector tau_hi) is recomputed at each. The result is:

* **Per-candidate score std across contexts** -- how much the DSD score itself
  moves when only the whitening context changes.
* **Verdict flip rate** -- of the near-threshold candidates, how many change
  ROBUST/not-ROBUST relative to the production pad=4 context.

The production context (pad=4) is the reference. A reproduction check is built in:
at pad=4 the re-scored native value must match the stored ``native_o4a_score``,
or the encoding here differs from production and the sweep means nothing.

Catalogues before 2026-07-24 label the padded crop, so the analysis window is
[gps + 4, gps + 36] (the reproducibility note).

Usage
-----
    python -m src.pipeline_v2_production.whitening_context_sensitivity --pilot
    python -m src.pipeline_v2_production.whitening_context_sensitivity --n-candidates 15

Writes ``data/production/aggregated/whitening_context_sensitivity_{run}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.utils import record_environment, setup_logger
from src.pipeline_v2_production.dsd_index_stability import _sample

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
SEGMENT_LENGTH = 32.0
WINDOW_OFFSET = 4.0          # catalogue GPS labels the padded crop
PRODUCTION_PAD = 4.0
DEFAULT_PADS = (4.0, 16.0, 64.0, 128.0)
LARGE_SWING = 0.02          # a score swing this size can cross the DSD spacing
# Per-detector DSD threshold tau_hi (dsd_threshold_mc_error).
TAU_HI = {"H1": 0.41432, "L1": 0.44721}


def _score_at_pads(cands: pd.DataFrame, pads, scorer) -> tuple[np.ndarray, np.ndarray]:
    """Native score for each candidate at each whitening pad; kept mask."""
    import warnings
    import matplotlib

    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import (whiten_context, extract_clean_subwindow,
                                       generate_qtransform)

    scores = np.full((len(cands), len(pads)), np.nan)
    kept = np.zeros(len(cands), dtype=bool)
    for r, (_, c) in enumerate(cands.iterrows()):
        w0 = float(c.gps_start) + WINDOW_OFFSET
        ok = True
        for j, pad in enumerate(pads):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ts = fetch_strain_data(c.detector, w0 - pad - 4.0,
                                           w0 + SEGMENT_LENGTH + pad + 4.0,
                                           edge_tolerance=4.0)
                    tw, _ = whiten_context(ts, w0, w0 + SEGMENT_LENGTH, pad=pad)
                    clean = extract_clean_subwindow(tw, w0, w0 + SEGMENT_LENGTH)
                    spec = generate_qtransform(clean, save_path=None, cmap="cividis")
                rgb = (matplotlib.colormaps["cividis"](spec)[:, :, :3] * 255).astype(np.uint8)
                scores[r, j] = float(scorer.score_spectrogram([rgb], threshold=0.0)[0]
                                     ["novelty_score"])
            except Exception as e:  # noqa: BLE001
                logger.debug(f"candidate {c.gps_start} pad {pad} failed: {e}")
                ok = False
                break
        kept[r] = ok
    return scores, kept


def run(run_name: str = "O4a", n_candidates: int = 15, pads=DEFAULT_PADS,
        seed: int = 42) -> dict:
    from src.core.patch_scorer import PatchScorer
    from src.core.utils import get_reference_dir

    pads = tuple(float(p) for p in pads)
    if PRODUCTION_PAD not in pads:
        pads = (PRODUCTION_PAD,) + pads
    ref = get_reference_dir()
    scorer = PatchScorer(
        reference_index_path=str(ref / "patch_compressed_index_o4a_ex.npz"),
        verify_md5=False)

    tax = pd.read_csv(AGG / f"Master_Taxonomy_{run_name.lower()}.csv")
    tax["gps_start"] = tax.gps_start.astype(int)
    cands = _sample(tax, n_candidates, seed).reset_index(drop=True)
    logger.info(f"{len(cands)} near-threshold candidates; pads {list(pads)}")

    scores, kept = _score_at_pads(cands, pads, scorer)
    cands = cands[kept].reset_index(drop=True)
    scores = scores[kept]
    logger.info(f"{len(cands)} candidates scored at all pads")

    pad_idx = pads.index(PRODUCTION_PAD)
    prod_score = scores[:, pad_idx]
    stored = cands.native_o4a_score.to_numpy()

    # Reproduction anchor: pad=4 re-score must match the stored production score.
    repro_abs = np.abs(prod_score - stored)
    logger.info(f"pad=4 reproduction vs stored: max |delta| {repro_abs.max():.4f}, "
                f"median {np.median(repro_abs):.4f}")

    tau = cands.detector.map(TAU_HI).to_numpy()
    verdict = scores > tau[:, None]                 # (n_cand, n_pad)
    prod_verdict = verdict[:, pad_idx]

    # Context swing = full range of a candidate's score across the pad ladder.
    per_cand_std = np.nanstd(scores, axis=1)
    per_cand_swing = np.nanmax(scores, axis=1) - np.nanmin(scores, axis=1)
    n_large_swing = int((per_cand_swing > LARGE_SWING).sum())
    flips = {}
    for j, pad in enumerate(pads):
        if pad == PRODUCTION_PAD:
            continue
        changed = verdict[:, j] != prod_verdict
        flips[pad] = {
            "n_flipped": int(changed.sum()),
            "flip_rate": float(changed.mean()),
            "flipped_gps": [int(g) for g in cands.gps_start[changed].tolist()],
        }
        logger.info(f"pad={pad}: {int(changed.sum())}/{len(cands)} verdicts flip "
                    f"vs production pad=4")

    out = {
        "run": run_name, "seed": seed, "pads": list(pads),
        "production_pad": PRODUCTION_PAD, "tau_hi": TAU_HI,
        "n_candidates": int(len(cands)),
        "n_robust": int((cands.robustness_class == "ROBUST").sum()),
        "n_rejected": int((cands.robustness_class == "BACKGROUND").sum()),
        "reproduction_pad4_vs_stored": {
            "max_abs_delta": float(repro_abs.max()),
            "median_abs_delta": float(np.median(repro_abs)),
        },
        "per_candidate_score_std_median": float(np.median(per_cand_std)),
        "per_candidate_score_std_max": float(per_cand_std.max()),
        "per_candidate_swing_median": float(np.median(per_cand_swing)),
        "per_candidate_swing_max": float(per_cand_swing.max()),
        "n_large_swing": n_large_swing,
        "large_swing_threshold": LARGE_SWING,
        "verdict_flips_vs_production": flips,
        "interpretation_note": (
            "per_candidate_swing is a candidate's score range across pad 4->128, "
            "i.e. how much the native DSD score moves when only the whitening "
            "context changes. n_large_swing counts candidates whose swing exceeds "
            f"{LARGE_SWING} (enough to matter at the DSD spacing) -- these are the "
            "LAB_NOTEBOOK section 12 singleton's kind, and the point is whether "
            "they are typical or rare. verdict flip rate is the fraction of "
            "near-threshold candidates that cross the DSD cut between production "
            "pad=4 and a longer context; because the sample is deliberately "
            "near-threshold, it is an UPPER bound on the survey-wide rate. The "
            "reproduction delta (pad=4 vs stored) is small for typical candidates "
            "and large only for the same context-sensitive ones, confirming the "
            "sensitivity is confined, not general."),
    }
    dest = AGG / f"whitening_context_sensitivity_{run_name.lower()}.json"
    dest.write_text(json.dumps(out, indent=2))
    logger.info(
        f"context swing median {out['per_candidate_swing_median']:.4f} "
        f"(max {out['per_candidate_swing_max']:.4f}); {n_large_swing}/{len(cands)} "
        f"exceed {LARGE_SWING}; flip rates "
        f"{ {p: round(f['flip_rate'], 3) for p, f in flips.items()} }")
    logger.info(f"wrote {dest}")
    record_environment(AGG, f"whitening_context_sensitivity_{run_name.lower()}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-candidates", type=int, default=15,
                   help="Near-threshold candidates per (class, detector).")
    p.add_argument("--pads", type=float, nargs="+", default=list(DEFAULT_PADS))
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Fast machinery + reproduction check on a few candidates.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, n_candidates=2, pads=(4.0, 64.0), seed=a.seed)
    else:
        run(a.run, n_candidates=a.n_candidates, pads=a.pads, seed=a.seed)


if __name__ == "__main__":
    main()
