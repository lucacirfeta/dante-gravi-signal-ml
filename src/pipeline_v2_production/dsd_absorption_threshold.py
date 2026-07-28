"""At what prevalence does the DSD stop seeing a glitch morphology?

The Domain Shift Defense re-scores every candidate against a dictionary built
*from the run's own background*. That is what makes it robust to drift, and it
is also its blind spot: a morphology common enough to occupy dense regions of
feature space is learned by the dictionary and re-scored as background **by
construction**. The pipeline is therefore least sensitive to exactly the
pervasive instrumental couplings that matter most for detector characterization.

This is not a bug and no tuning removes it — it is what unsupervised novelty
detection *is*. What can be done is to measure it: inject one synthetic
morphology into the background at a controlled prevalence, rebuild the native
index from that contaminated background, and ask whether a *held-out* instance
of the same morphology still scores as anomalous. Sweeping the prevalence gives
an absorption threshold: "DANTE detects this morphology while it stays below
prevalence p; above it, the morphology is absorbed."

Design notes
------------
* Encoding is the expensive step, so background and injected segments are
  encoded **once** and only the K-means is repeated per prevalence.
* Injection is into the *whitened* segment. Whitened noise is approximately unit
  variance, so the injected peak amplitude is directly interpretable as an
  SNR-like scale, and the recurring pattern in the spectrogram — which is what
  the dictionary can learn — is faithful.
* The dictionary size tracks the production ratio (~1457 patch tokens per
  centroid) rather than the production K, so a smaller experiment keeps the same
  granularity.
* Both the scored injections and the scored background are **held out** of the
  dictionary, so absorption is not measured on the data that built it.

Usage
-----
    python -m src.pipeline_v2_production.dsd_absorption_threshold --pilot
    python -m src.pipeline_v2_production.dsd_absorption_threshold \
        --morphology Blip --n-background 300

Writes a Q-range-versioned
``data/production/aggregated/dsd_absorption_{morphology}_{qrange}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.core.index_contract import qrange_tag
from src.core.utils import (
    load_config,
    normalize_spectrogram,
    record_environment,
    setup_logger,
)
from src.pipeline_v3_multiscale.norm_leakage.common import (
    PatchEncoder, iter_clean_segments, raw_qgram, spectrogram_to_rgb, topk_score,
)

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
TOKENS_PER_SEGMENT = 1369
PRODUCTION_TOKENS_PER_CENTROID = 1295 * TOKENS_PER_SEGMENT / 1216  # ~1458
TOP_K = 68


def _inject(ts_whitened, glitch: np.ndarray, rng) -> np.ndarray:
    """Add a glitch into a whitened 32 s segment at a random position.

    Returns the strain array. Whitened noise is ~unit variance, so the glitch
    amplitude is already on an interpretable scale and needs no rescaling.
    """
    x = np.asarray(ts_whitened.value, dtype=float).copy()
    n = len(glitch)
    if n >= len(x):
        return x
    # Keep the injection clear of the edges, which the bandpass distorts.
    lo = int(0.15 * len(x))
    hi = int(0.85 * len(x)) - n
    start = int(rng.integers(lo, max(lo + 1, hi)))
    x[start:start + n] += glitch
    return x


def _encode_segments(
    encoder,
    segments,
    glitch_fn=None,
    rng=None,
    qrange=(4, 64),
) -> np.ndarray:
    """Encode segments to (n_segments, 1369, 384) patch tokens."""
    out = []
    for seg in segments:
        try:
            ts = seg.ts_whitened
            if glitch_fn is not None:
                from gwpy.timeseries import TimeSeries
                arr = _inject(ts, glitch_fn(), rng)
                ts = TimeSeries(arr, t0=ts.t0, dt=ts.dt)
            spec = normalize_spectrogram(
                raw_qgram(
                    ts.crop(seg.t_bg - 16, seg.t_bg + 16),
                    qrange=qrange,
                )
            )
            out.append(encoder.encode_rgb(spectrogram_to_rgb(spec)))
        except Exception as e:  # noqa: BLE001 - a dropped segment is not fatal
            logger.debug(f"segment {seg.t_bg} failed: {e}")
    return np.asarray(out, dtype=np.float32)


def _build_index(tokens: np.ndarray, seed: int) -> np.ndarray:
    """K-means dictionary over stacked patch tokens, K set by the production ratio."""
    from sklearn.cluster import MiniBatchKMeans

    flat = tokens.reshape(-1, tokens.shape[-1])
    k = max(16, int(round(len(flat) / PRODUCTION_TOKENS_PER_CENTROID)))
    km = MiniBatchKMeans(n_clusters=k, batch_size=4096, compute_labels=False,
                         random_state=seed, n_init="auto")
    km.fit(flat)
    c = km.cluster_centers_
    return c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-12)


def run(morphology: str = "Blip", amplitude: float = 6.0, duration: float = 1.0,
        n_background: int = 300, n_holdout_bg: int = 150, n_holdout_inj: int = 60,
        prevalences=(0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40),
        run_name: str = "O4a", seed: int = 42,
        qrange: tuple[int, int] | None = None) -> dict:
    from src.core.injection import SyntheticGlitchGenerator

    rng = np.random.default_rng(seed)
    if qrange is None:
        qrange = tuple(
            int(value)
            for value in load_config()["preprocessing"]["qrange"]
        )
    qrange = tuple(int(value) for value in qrange)
    gen = SyntheticGlitchGenerator(sample_rate=4096)
    encoder = PatchEncoder()

    def make_glitch():
        return gen.generate(morphology, amplitude, duration=duration)

    n_pool = n_background + n_holdout_bg + n_holdout_inj + int(max(prevalences) * n_background) + 20
    logger.info(f"collecting {n_pool} clean segments (this is the slow part)")
    segs = list(iter_clean_segments(run_name.lower(), "L1", n_pool, seed=seed))
    if len(segs) < n_background + n_holdout_bg + n_holdout_inj:
        raise RuntimeError(f"only {len(segs)} clean segments available")
    logger.info(f"collected {len(segs)} segments")

    i = 0
    bg_pool = segs[i:i + n_background]; i += n_background
    hold_bg = segs[i:i + n_holdout_bg]; i += n_holdout_bg
    hold_inj_src = segs[i:i + n_holdout_inj]; i += n_holdout_inj
    inj_pool_src = segs[i:]

    # Encoding is ~90% of the runtime and depends only on (morphology, amplitude,
    # duration, n_background, seed). Cache it so re-running the sweep with a
    # different prevalence grid, control arm or metric costs seconds.
    cache = AGG / (
        f"dsd_absorption_tokens_{morphology.lower()}_"
        f"{qrange_tag(qrange)}_a{amplitude:g}_"
        f"n{n_background}_s{seed}.npz"
    )
    if cache.exists():
        logger.info(f"loading cached patch tokens from {cache.name}")
        z_ = np.load(cache)
        bg_tokens, inj_tokens = z_["bg"], z_["inj"]
        hold_bg_tok, hold_inj_tok = z_["hold_bg"], z_["hold_inj"]
    else:
        logger.info("encoding background pool")
        bg_tokens = _encode_segments(
            encoder,
            bg_pool,
            qrange=qrange,
        )
        logger.info("encoding injected pool")
        inj_tokens = _encode_segments(
            encoder,
            inj_pool_src,
            make_glitch,
            rng,
            qrange=qrange,
        )
        logger.info("encoding held-out background")
        hold_bg_tok = _encode_segments(
            encoder,
            hold_bg,
            qrange=qrange,
        )
        logger.info("encoding held-out injections")
        hold_inj_tok = _encode_segments(
            encoder,
            hold_inj_src,
            make_glitch,
            rng,
            qrange=qrange,
        )
        np.savez_compressed(cache, bg=bg_tokens, inj=inj_tokens,
                            hold_bg=hold_bg_tok, hold_inj=hold_inj_tok)
        logger.info(f"cached patch tokens to {cache.name}")

    rows = []
    for p in prevalences:
        n_inj = int(round(p * n_background))
        if n_inj > len(inj_tokens):
            logger.warning(f"prevalence {p:.0%} needs {n_inj} injected segments, "
                           f"only {len(inj_tokens)} encoded — skipped")
            continue
        mix = np.concatenate([bg_tokens[:n_background - n_inj], inj_tokens[:n_inj]]) \
            if n_inj else bg_tokens[:n_background]
        cents = _build_index(mix, seed)

        # CONTROL. At high prevalence the index contains fewer background
        # segments, so a drop in separation could be a sample-size effect rather
        # than absorption. Build a second index from the same NUMBER of segments
        # but all background: if its separation stays flat while the mixed one
        # falls, the fall is caused by the morphology entering the dictionary.
        ctrl_cents = _build_index(bg_tokens[:n_background - n_inj], seed) if n_inj else cents

        s_inj = np.array([topk_score(t, cents, TOP_K) for t in hold_inj_tok])
        s_bg = np.array([topk_score(t, cents, TOP_K) for t in hold_bg_tok])
        c_inj = np.array([topk_score(t, ctrl_cents, TOP_K) for t in hold_inj_tok])
        c_bg = np.array([topk_score(t, ctrl_cents, TOP_K) for t in hold_bg_tok])
        z_ctrl = float((c_inj.mean() - c_bg.mean()) / (c_bg.std(ddof=1) + 1e-12))
        thr = float(np.percentile(s_bg, 99))
        flagged = float(np.mean(s_inj > thr))
        # Absolute scores are not comparable across prevalences: each index has
        # its own scale. The z-score of the injections against THAT index's own
        # background is, and it does not depend on a percentile estimated from a
        # finite hold-out, so it is the primary metric here.
        z = float((s_inj.mean() - s_bg.mean()) / (s_bg.std(ddof=1) + 1e-12))
        rows.append({
            "prevalence": float(p), "n_injected_in_index": n_inj,
            "K": int(cents.shape[0]),
            "score_injected_mean": float(s_inj.mean()),
            "score_injected_median": float(np.median(s_inj)),
            "score_background_p99": thr,
            "score_background_mean": float(s_bg.mean()),
            "score_background_std": float(s_bg.std(ddof=1)),
            "z_injected_vs_background": z,
            "z_control_same_size_all_background": z_ctrl,
            "flagged_fraction": flagged,
            "separation": float(s_inj.mean() - thr),
        })
        logger.info(f"prevalence {p:6.1%} | K={cents.shape[0]:4d} | "
                    f"inj {s_inj.mean():.4f} bg {s_bg.mean():.4f} | "
                    f"z={z:+6.2f} (control {z_ctrl:+6.2f}) | flagged {flagged:.0%}")

    out = {
        "run": run_name,
        "qrange": list(qrange),
        "morphology": morphology,
        "amplitude": amplitude,
        "duration_s": duration, "n_background": n_background,
        "n_holdout_bg": len(hold_bg_tok), "n_holdout_inj": len(hold_inj_tok),
        "seed": seed, "top_k": TOP_K, "rows": rows,
    }
    AGG.mkdir(parents=True, exist_ok=True)
    dest = AGG / (
        f"dsd_absorption_{morphology.lower()}_"
        f"{qrange_tag(qrange)}.json"
    )
    dest.write_text(json.dumps(out, indent=2))
    logger.info(f"wrote {dest}")
    record_environment(
        AGG,
        f"dsd_absorption_{morphology.lower()}_{qrange_tag(qrange)}",
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--morphology", default="Blip")
    p.add_argument("--amplitude", type=float, default=6.0)
    p.add_argument("--duration", type=float, default=1.0)
    p.add_argument("--n-background", type=int, default=300)
    p.add_argument("--run", default="O4a")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Small fast run to validate the machinery end to end.")
    a = p.parse_args()
    if a.pilot:
        run(morphology=a.morphology, amplitude=a.amplitude, duration=a.duration,
            n_background=40, n_holdout_bg=12, n_holdout_inj=12,
            prevalences=(0.0, 0.10, 0.40), run_name=a.run, seed=a.seed)
    else:
        run(morphology=a.morphology, amplitude=a.amplitude, duration=a.duration,
            n_background=a.n_background, run_name=a.run, seed=a.seed)


if __name__ == "__main__":
    main()
