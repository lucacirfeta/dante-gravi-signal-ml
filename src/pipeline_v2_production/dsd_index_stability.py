"""Are the DSD survivors an artifact of which background built the dictionary?

The native index is a K-means dictionary over a *sample* of the run's own
background. If which candidates survive the DSD depends on that sample, the
survivor population -- the central object of the survey -- is partly an artifact
of a random draw rather than a property of the candidates.

The test builds several independent native indices from disjoint bootstrap draws
of the background pool (raw_qgram, vetoed background -- matching
``build_native_index``), and re-scores the same candidates against each. The
answer is read from three threshold-independent statistics:

* **Score rank correlation** across draws -- if a candidate scores high against
  one draw and high against another, the ordering is a property of the
  candidate, not of the reference.
* **Per-candidate score std** across draws -- how much a single candidate's
  score wobbles when the reference is resampled.
* **ROBUST vs rejected separation** under the rebuilt indices -- if survivors
  still score above rejected candidates against a fresh index, the boundary is
  a property of the candidates.

All three avoid a threshold on purpose. Reproducing the *production* survive/
reject threshold is subtle -- production calibrates it on un-vetoed
(glitch-inclusive) background while it builds the index on vetoed background
(LAB_NOTEBOOK section 19) -- so the verdict metrics are reported only as
diagnostics, not as production-faithful decisions. The rank correlation is the
headline result and needs no threshold.

The sample concentrates near the upper DSD threshold, where the
survivor/non-survivor distinction is most fragile.  The contrast population is
the highest-scoring non-ROBUST set (normally AMBIGUOUS), not ``BACKGROUND``:
after the coherent Q64/Q64 calibration the uncertainty interval is wide enough
that the closest non-survivors are correctly labelled AMBIGUOUS.

Candidate patch tokens are not stored, so candidates are re-encoded. Catalogues
before 2026-07-24 label the padded crop, so the analysis window is
[gps + 4, gps + 36] (see the reproducibility note). Encoding is cached.

Usage
-----
    python -m src.pipeline_v2_production.dsd_index_stability --pilot
    python -m src.pipeline_v2_production.dsd_index_stability --n-candidates 60

Writes
``data/production/aggregated/dsd_index_stability_{run}_{representation}.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.index_contract import load_taxonomy_view, qrange_tag
from src.core.utils import (
    load_config,
    normalize_spectrogram,
    record_environment,
    setup_logger,
)
from src.pipeline_v2_production.dsd_absorption_threshold import _build_index
from src.pipeline_v3_multiscale.norm_leakage.common import (
    PatchEncoder, iter_clean_segments, raw_qgram, spectrogram_to_rgb, topk_score)

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
PROD = Path("data/production")
SEGMENT_LENGTH = 32.0
WINDOW_OFFSET = 4.0          # catalogue GPS labels the padded crop
TOP_K = 68


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_key_digest(keys: np.ndarray) -> str:
    payload = "\n".join(str(value) for value in keys.tolist()).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _encode_candidates(
    cands: pd.DataFrame,
    qrange: tuple[int, int],
    encoder: PatchEncoder | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """DINO tokens and pixel features from the same candidate Q-grams."""
    import warnings

    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import whiten_context, extract_clean_subwindow
    from src.pipeline_v2_production.pca_baseline import (
        _features,
        _spectral_energy,
    )

    enc = encoder or PatchEncoder()
    toks, pixel_features, energy, kept = [], [], [], []
    rgb_batch = []

    def flush() -> None:
        if rgb_batch:
            toks.extend(enc.encode_batch(rgb_batch))
            rgb_batch.clear()

    for _, c in cands.iterrows():
        w0 = float(c.gps_start) + WINDOW_OFFSET
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ts = fetch_strain_data(c.detector, w0 - 4.0, w0 + SEGMENT_LENGTH + 4.0,
                                       edge_tolerance=4.0)
                tw, _ = whiten_context(ts, w0, w0 + SEGMENT_LENGTH, pad=4.0)
                clean = extract_clean_subwindow(tw, w0, w0 + SEGMENT_LENGTH)
                # The candidate and rebuilt-background dictionaries must use
                # the same raw Q-gram representation. The historical test mixed
                # generate_qtransform candidates with raw_qgram backgrounds.
                spec = raw_qgram(clean, qrange=qrange)
            rgb_batch.append(
                spectrogram_to_rgb(normalize_spectrogram(spec))
            )
            pixel_features.append(_features(spec))
            energy.append(_spectral_energy(spec))
            kept.append(True)
            if len(rgb_batch) >= 8:
                flush()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"candidate {c.gps_start} failed: {e}")
            kept.append(False)
    flush()
    return (
        np.asarray(toks, dtype=np.float32),
        np.asarray(pixel_features, dtype=np.float32),
        np.asarray(energy, dtype=np.float32),
        np.asarray(kept),
    )


def _encode_background_products(
    encoder: PatchEncoder,
    segments,
    *,
    qrange: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Encode DINO and PCA products once from each identical raw Q-gram."""
    from src.pipeline_v2_production.pca_baseline import (
        _features,
        _spectral_energy,
    )

    toks, pixel_features, energy = [], [], []
    rgb_batch = []

    def flush() -> None:
        if rgb_batch:
            toks.extend(encoder.encode_batch(rgb_batch))
            rgb_batch.clear()

    for segment in segments:
        try:
            spec = raw_qgram(
                segment.ts_whitened.crop(
                    segment.t_bg - SEGMENT_LENGTH / 2,
                    segment.t_bg + SEGMENT_LENGTH / 2,
                ),
                qrange=qrange,
            )
            rgb_batch.append(
                spectrogram_to_rgb(normalize_spectrogram(spec))
            )
            pixel_features.append(_features(spec))
            energy.append(_spectral_energy(spec))
            if len(rgb_batch) >= 8:
                flush()
        except Exception as exc:
            raise RuntimeError(
                f"Failed to encode shared P5/P10 background "
                f"{segment.t_bg}"
            ) from exc
    flush()
    return (
        np.asarray(toks, dtype=np.float32),
        np.asarray(pixel_features, dtype=np.float32),
        np.asarray(energy, dtype=np.float32),
    )


def _sample(
    tax: pd.DataFrame,
    n_each: int,
    thresholds: dict,
) -> pd.DataFrame:
    """Near-threshold ROBUST and non-ROBUST candidates, both detectors."""
    picks = []
    for det in ("H1", "L1"):
        thr = float(thresholds[det]["ci_upper"])
        d = tax[tax.detector == det]
        rob = d[
            (d.dsd_class == "ROBUST")
            & (d.dsd_score < thr + 0.04)
        ].nsmallest(n_each, "dsd_score")
        rej = d[
            d.dsd_class.ne("ROBUST")
            & (d.dsd_score <= thr)
        ].nlargest(n_each, "dsd_score")
        picks += [rob, rej]
    out = pd.concat(picks).drop_duplicates(["detector", "gps_start"]).reset_index(drop=True)
    return out


# Production native index: 1295 background segments, K=1216 (~1458 tokens per
# centroid). The rebuilt indices must match that scale, or their score scale is
# compressed and does not reproduce the DSD decision boundary -- a smaller index
# scores every candidate above its threshold, survivors and rejected alike.
PRODUCTION_N_BACKGROUND = 1300


def run(run_name: str = "O4a", n_candidates: int = 40,
        n_background: int = PRODUCTION_N_BACKGROUND,
        n_holdout_bg: int = 300, n_draws: int = 4, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    qrange = tuple(
        int(value) for value in load_config()["preprocessing"]["qrange"]
    )
    tax, taxonomy_contract = load_taxonomy_view(
        AGG,
        run_name,
        index_qrange=qrange,
        query_qrange=qrange,
    )
    tax["gps_start"] = tax.gps_start.astype(int)
    threshold_path = AGG / (
        f"dsd_thresholds_{run_name.lower()}_"
        f"{taxonomy_contract.representation}.json"
    )
    if not threshold_path.exists():
        raise RuntimeError(
            f"Coherent DSD thresholds are missing: {threshold_path}"
        )
    threshold_record = json.loads(threshold_path.read_text(encoding="utf-8"))
    if (
        threshold_record.get("representation", {}).get("variant")
        != taxonomy_contract.representation
    ):
        raise RuntimeError("DSD threshold representation mismatch")
    thresholds = threshold_record["thresholds"]

    cands = _sample(tax, n_candidates, thresholds)
    logger.info(f"{len(cands)} candidates "
                f"({(cands.dsd_class=='ROBUST').sum()} ROBUST, "
                f"{(cands.dsd_class!='ROBUST').sum()} non-ROBUST)")

    candidate_keys = np.asarray(
        [
            f"{detector}:{gps}"
            for detector, gps in zip(cands.detector, cands.gps_start)
        ]
    )
    candidate_key_sha256 = _candidate_key_digest(candidate_keys)
    candidate_cache = AGG / (
        f"dsd_index_stability_candidate_tokens_{run_name.lower()}_"
        f"{taxonomy_contract.cache_tag}_{qrange_tag(qrange)}_"
        f"n{n_candidates}_s{seed}_{candidate_key_sha256[:12]}.npz"
    )
    background_cache = AGG / (
        f"dsd_index_stability_background_tokens_{run_name.lower()}_"
        f"{taxonomy_contract.cache_tag}_{qrange_tag(qrange)}_"
        f"n{n_background}_h{n_holdout_bg}_s{seed}.npz"
    )
    background_ledger = background_cache.with_name(
        f"{background_cache.stem}_ledger.csv"
    )

    encoder = None
    if candidate_cache.exists():
        logger.info(
            "loading cached candidate tokens from %s",
            candidate_cache.name,
        )
        z = np.load(candidate_cache, allow_pickle=False)
        cand_tok, kept = z["cand"], z["kept"]
        candidate_pixel_features = z["pca_feat"]
        candidate_energy = z["pca_energy"]
        if (
            tuple(int(value) for value in z["qrange"].tolist()) != qrange
            or str(z["representation"].item())
            != taxonomy_contract.representation
            or not np.array_equal(z["candidate_keys"], candidate_keys)
            or str(z["candidate_keys_sha256"].item())
            != candidate_key_sha256
            or len(candidate_pixel_features) != len(cand_tok)
            or len(candidate_energy) != len(cand_tok)
        ):
            raise RuntimeError(
                f"Candidate token cache contract mismatch: {candidate_cache}"
            )
        cands = cands[kept].reset_index(drop=True)
    else:
        logger.info(
            "encoding candidates (true [gps+4, gps+36] window, Q=%s)",
            qrange,
        )
        encoder = PatchEncoder()
        (
            cand_tok,
            candidate_pixel_features,
            candidate_energy,
            kept,
        ) = _encode_candidates(cands, qrange, encoder)
        cands = cands[kept].reset_index(drop=True)
        if not all(
            np.isfinite(array).all()
            for array in (
                cand_tok,
                candidate_pixel_features,
                candidate_energy,
            )
        ):
            raise RuntimeError(
                "Shared P5/P10 candidate products contain non-finite values"
            )
        np.savez_compressed(
            candidate_cache,
            cand=cand_tok,
            pca_feat=candidate_pixel_features,
            pca_energy=candidate_energy,
            kept=kept,
            candidate_keys=candidate_keys,
            candidate_keys_sha256=np.asarray(candidate_key_sha256),
            qrange=np.asarray(qrange),
            representation=np.asarray(taxonomy_contract.representation),
        )
        logger.info("cached candidate tokens to %s", candidate_cache.name)

    if background_cache.exists():
        logger.info(
            "loading cached background tokens from %s",
            background_cache.name,
        )
        if not background_ledger.exists():
            raise RuntimeError(
                f"Background token cache lacks ledger: {background_ledger}"
            )
        z_bg = np.load(background_cache, allow_pickle=False)
        bg_tok, hold_tok = z_bg["bg"], z_bg["hold"]
        background_pixel_features = z_bg["pca_bg_feat"]
        background_energy = z_bg["pca_bg_energy"]
        ledger = pd.read_csv(background_ledger)
        expected_roles = (
            ["index_pool"] * n_background
            + ["held_out"] * n_holdout_bg
        )
        if (
            tuple(int(value) for value in z_bg["qrange"].tolist()) != qrange
            or str(z_bg["representation"].item())
            != taxonomy_contract.representation
            or str(z_bg["detector"].item()) != "L1"
            or len(bg_tok) != n_background
            or len(hold_tok) != n_holdout_bg
            or len(background_pixel_features) != n_background
            or len(background_energy) != n_background
            or len(ledger) != n_background + n_holdout_bg
            or ledger["role"].astype(str).tolist() != expected_roles
            or not np.array_equal(
                ledger["t_bg"].to_numpy(dtype=float),
                z_bg["t_bg"].astype(float),
            )
            or str(z_bg["ledger_sha256"].item())
            != _sha256_file(background_ledger)
        ):
            raise RuntimeError(
                f"Background token cache contract mismatch: {background_cache}"
            )
    else:
        if encoder is None:
            encoder = PatchEncoder()
        logger.info(f"collecting {n_background + n_holdout_bg} background segments")
        segs = list(iter_clean_segments(run_name.lower(), "L1",
                                        n_background + n_holdout_bg + 40, seed=seed))
        if len(segs) < n_background + n_holdout_bg:
            raise RuntimeError(
                "Insufficient clean segments for P5 background and holdout"
            )
        logger.info("encoding background pool + held-out background")
        (
            bg_tok,
            background_pixel_features,
            background_energy,
        ) = _encode_background_products(
            encoder,
            segs[:n_background],
            qrange=qrange,
        )
        hold_tok, _, _ = _encode_background_products(
            encoder,
            segs[n_background:n_background + n_holdout_bg],
            qrange=qrange,
        )
        background_times = np.asarray(
            [
                segment.t_bg
                for segment in segs[: n_background + n_holdout_bg]
            ],
            dtype=np.float64,
        )
        if len(np.unique(background_times)) != len(background_times):
            raise RuntimeError("P5 background ledger contains duplicate GPS")
        ledger = pd.DataFrame(
            {
                "ordinal": np.arange(len(background_times), dtype=int),
                "role": (
                    ["index_pool"] * n_background
                    + ["held_out"] * n_holdout_bg
                ),
                "detector": "L1",
                "t_bg": background_times,
                "segment_start": background_times - SEGMENT_LENGTH / 2,
                "segment_end": background_times + SEGMENT_LENGTH / 2,
                "run": run_name,
                "seed": seed,
            }
        )
        ledger.to_csv(background_ledger, index=False)
        ledger_sha256 = _sha256_file(background_ledger)
        np.savez_compressed(
            background_cache,
            bg=bg_tok,
            hold=hold_tok,
            pca_bg_feat=background_pixel_features,
            pca_bg_energy=background_energy,
            t_bg=background_times,
            ledger_sha256=np.asarray(ledger_sha256),
            detector=np.asarray("L1"),
            qrange=np.asarray(qrange),
            representation=np.asarray(taxonomy_contract.representation),
        )
        logger.info(
            "cached background tokens and GPS ledger to %s",
            background_cache.name,
        )

    # Independent index draws: disjoint bootstrap resamples of the background
    # pool. Each gets its own threshold from the held-out background.
    n_bg = len(bg_tok)
    cand_scores = np.zeros((n_draws, len(cand_tok)))
    survive = np.zeros((n_draws, len(cand_tok)), dtype=bool)
    thresholds = []
    for k in range(n_draws):
        idx = rng.choice(n_bg, size=n_bg, replace=True)
        cents = _build_index(bg_tok[idx], seed + k)
        hb = np.array([topk_score(t, cents, TOP_K) for t in hold_tok])
        thr = float(np.percentile(hb, 99))
        thresholds.append(thr)
        cs = np.array([topk_score(t, cents, TOP_K) for t in cand_tok])
        cand_scores[k] = cs
        survive[k] = cs > thr
        logger.info(f"draw {k}: threshold {thr:.4f}, survivors "
                    f"{int(survive[k].sum())}/{len(cs)}")

    is_rob = (cands.dsd_class == "ROBUST").to_numpy()

    # PRIMARY, threshold-independent metrics. The survive/reject verdict needs a
    # threshold, and reproducing the production threshold is subtle: production
    # calibrates it on UN-VETOED background (glitch-inclusive, P99=0.447) while
    # the index is built on VETOED background (see LAB_NOTEBOOK §19). The
    # held-out threshold here uses vetoed background and lands at ~0.10, far
    # below where the candidates sit, so the verdict metrics are not
    # production-faithful and are reported only as diagnostics. These three do
    # not depend on any threshold and answer the stability question directly:
    from scipy.stats import spearmanr
    rhos = [spearmanr(cand_scores[i], cand_scores[j]).statistic
            for i in range(n_draws) for j in range(i + 1, n_draws)]
    per_cand_std = cand_scores.std(axis=0)          # score wobble across draws
    rob_mean = float(cand_scores.mean(axis=0)[is_rob].mean())
    rej_mean = float(cand_scores.mean(axis=0)[~is_rob].mean())

    # Diagnostic verdict metrics (NOT production-faithful, see above).
    all_survive = survive.all(axis=0)
    all_reject = (~survive).all(axis=0)

    out = {
        "run": run_name,
        "representation": taxonomy_contract.representation,
        "taxonomy_path": str(taxonomy_contract.path),
        "qrange": list(qrange),
        "n_candidates": int(len(cand_tok)),
        "n_robust": int(is_rob.sum()), "n_rejected": int((~is_rob).sum()),
        "sample_class_counts": {
            str(label): int(count)
            for label, count in cands["dsd_class"].value_counts().items()
        },
        "n_draws": n_draws, "n_background": n_bg, "seed": seed,
        "candidate_token_cache": str(candidate_cache),
        "candidate_token_cache_sha256": _sha256_file(candidate_cache),
        "candidate_keys_sha256": candidate_key_sha256,
        "background_token_cache": str(background_cache),
        "background_token_cache_sha256": _sha256_file(background_cache),
        "background_ledger": str(background_ledger),
        "background_ledger_sha256": _sha256_file(background_ledger),
        # --- primary, threshold-independent ---
        "score_rank_correlation_mean": float(np.mean(rhos)),
        "score_rank_correlation_min": float(np.min(rhos)),
        "per_candidate_score_std_median": float(np.median(per_cand_std)),
        "per_candidate_score_std_max": float(per_cand_std.max()),
        "robust_mean_score": rob_mean,
        "rejected_mean_score": rej_mean,
        "robust_rejected_separation": rob_mean - rej_mean,
        # --- diagnostic only: threshold not production-faithful (§19) ---
        "_diagnostic_thresholds": thresholds,
        "_diagnostic_verdict_note": (
            "held-out thresholds use vetoed clean background, whereas the "
            "production calibration uses its frozen chronological background "
            "ledger and detector-specific B=1,000,000 bootstrap upper endpoint. "
            "The populations and decision boundaries are therefore different; "
            "verdict metrics below are diagnostic only, see LAB_NOTEBOOK "
            "section 19"),
        "_diagnostic_verdict_stable_fraction": float((all_survive | all_reject).mean()),
    }
    dest = AGG / (
        f"dsd_index_stability_{run_name.lower()}_"
        f"{taxonomy_contract.representation}.json"
    )
    dest.write_text(json.dumps(out, indent=2))
    logger.info(
        f"score rank-corr {out['score_rank_correlation_mean']:.3f} "
        f"(min {out['score_rank_correlation_min']:.3f}) | per-candidate std "
        f"median {out['per_candidate_score_std_median']:.4f} | ROBUST "
        f"{rob_mean:.3f} vs rejected {rej_mean:.3f} across independent draws")
    logger.info(f"wrote {dest}")
    record_environment(
        AGG,
        (
            f"dsd_index_stability_{run_name.lower()}_"
            f"{taxonomy_contract.representation}"
        ),
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-candidates", type=int, default=40,
                   help="Near-threshold candidates per (class, detector).")
    p.add_argument("--n-background", type=int, default=PRODUCTION_N_BACKGROUND,
                   help="Background segments per index. Must match the production "
                        "index size (~1300, K~1216) or the score scale is "
                        "compressed and the DSD boundary is not reproduced.")
    p.add_argument("--n-draws", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Fast machinery check. NOTE: its small index does NOT "
                        "reproduce the DSD boundary (everything survives); use "
                        "only to confirm the pipeline runs end to end.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, n_candidates=8, n_background=120, n_holdout_bg=60,
            n_draws=3, seed=a.seed)
    else:
        run(a.run, n_candidates=a.n_candidates, n_background=a.n_background,
            n_draws=a.n_draws, seed=a.seed)


if __name__ == "__main__":
    main()
