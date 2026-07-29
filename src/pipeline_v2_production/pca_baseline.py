"""What does the frozen DINOv2 encoder buy over a dumb classical baseline?

DANTE scores novelty with a frozen vision transformer pre-trained on natural
images -- an encoder that has never seen a gravitational-wave spectrogram (B2:
"the encoder is not GW-native"). This test measures what that transfer buys, and
what it costs, against the simplest honest alternative: a classical anomaly
detector that works directly on the spectrogram pixels.

The baseline is a PCA subspace novelty detector -- the textbook method. Fit a
principal-component subspace on the same vetoed O4a background DANTE uses; a
candidate's anomaly is its *reconstruction residual*, the energy in its
spectrogram that the background subspace cannot represent. A second, even
simpler baseline is raw spectral energy. Neither has any learned or transferred
representation; they are what a first-year method would flag.

Both baselines score the *same* near-threshold candidate pool as the index-
stability test (P5), so the two are directly comparable. The question is read
from three numbers:

* **Rank correlation** between each classical score and DANTE's stored
  coherent ``dsd_score``. High correlation means a dumb pixel method already ranks
  candidates the way DANTE does -- the transfer buys little. Low correlation
  means DANTE responds to structure the classical method is blind to.
* **ROBUST vs rejected separation** under each classical score -- does the
  baseline, on its own, put survivors above rejected candidates?
* **AUC** of each classical score at the ROBUST/rejected split.

The outcome is a *measurement*, not a fix. It bounds the value of the natural-
image transfer; it does not reduce its cost (B2). Either answer is publishable
and honest, and neither paper currently states it.

To stay trap-free after the raw_qgram/generate_qtransform confusion that derailed
P5, this test uses ``raw_qgram`` for BOTH background and candidates -- one
spectrogram function on both sides. It never recomputes DANTE's score; it
correlates against the stored value, so the pixel pipeline being internally
self-consistent is all that is required. Catalogues before 2026-07-24 label the
padded crop, so the candidate window is [gps + 4, gps + 36].

Usage
-----
    python -m src.pipeline_v2_production.pca_baseline --pilot
    python -m src.pipeline_v2_production.pca_baseline --n-candidates 40

Writes
``data/production/aggregated/pca_baseline_{run}_{representation}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.index_contract import load_taxonomy_view, qrange_tag
from src.core.utils import load_config, record_environment, setup_logger
from src.pipeline_v2_production.dsd_index_stability import (
    _candidate_key_digest,
    _sample,
    _sha256_file,
)
from src.pipeline_v3_multiscale.norm_leakage.common import (
    iter_clean_segments, raw_qgram)

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
SEGMENT_LENGTH = 32.0
WINDOW_OFFSET = 4.0          # catalogue GPS labels the padded crop
FEAT_SIZE = 32              # spectrogram downsampled to 32x32 = 1024-d feature
VAR_KEPT = 0.90            # PCA subspace retains 90% of background variance


def _features(spec: np.ndarray) -> np.ndarray:
    """raw_qgram power (256x256) -> log1p, downsample to FEAT_SIZE^2, flatten.

    log1p compresses the power dynamic range the way a human eye (and the
    production colormap) does, so the PCA subspace is not dominated by a single
    loud pixel. The classical detector sees the same morphology a person would.
    """
    from scipy.ndimage import zoom

    # Q-transform power is physically >= 0; the few small negatives here are
    # linear-interpolation undershoot from raw_qgram's zoom, not signal. Clip
    # before log1p, which would otherwise return NaN for any pixel < -1 and
    # poison the whole feature vector.
    arr = np.clip(np.asarray(spec, dtype=np.float64), 0.0, None)
    lg = np.log1p(arr)
    f = FEAT_SIZE / lg.shape[0], FEAT_SIZE / lg.shape[1]
    return zoom(lg, f, order=1).ravel()


def _spectral_energy(spec: np.ndarray) -> float:
    """Total Q-transform power -- the crudest possible novelty proxy."""
    return float(np.clip(np.asarray(spec, dtype=np.float64), 0.0, None).sum())


def _encode_candidates(
    cands: pd.DataFrame,
    qrange: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pixel features + spectral energy for each candidate, [gps+4, gps+36]."""
    import warnings

    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import whiten_context, extract_clean_subwindow

    feats, energy, kept = [], [], []
    for _, c in cands.iterrows():
        w0 = float(c.gps_start) + WINDOW_OFFSET
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ts = fetch_strain_data(c.detector, w0 - 4.0,
                                       w0 + SEGMENT_LENGTH + 4.0, edge_tolerance=4.0)
                tw, _ = whiten_context(ts, w0, w0 + SEGMENT_LENGTH, pad=4.0)
                clean = extract_clean_subwindow(tw, w0, w0 + SEGMENT_LENGTH)
                spec = raw_qgram(clean, qrange=qrange)
            feats.append(_features(spec))
            energy.append(_spectral_energy(spec))
            kept.append(True)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"candidate {c.gps_start} failed: {e}")
            kept.append(False)
    return (np.asarray(feats, dtype=np.float32),
            np.asarray(energy, dtype=np.float32),
            np.asarray(kept))


def _encode_background(
    segs,
    qrange: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Pixel features + spectral energy for the vetoed background pool."""
    feats, energy = [], []
    for s in segs:
        spec = raw_qgram(s.ts_whitened, qrange=qrange)
        feats.append(_features(spec))
        energy.append(_spectral_energy(spec))
    return (np.asarray(feats, dtype=np.float32),
            np.asarray(energy, dtype=np.float32))


def _pca_residual(bg: np.ndarray, cand: np.ndarray) -> tuple[np.ndarray, int]:
    """Reconstruction residual of each candidate against the background subspace.

    Fit PCA on the background, keep enough components for VAR_KEPT of variance,
    then score each candidate by the L2 norm of what the subspace cannot
    reconstruct. This is the classic subspace (SPE) novelty detector: high
    residual = morphology absent from the background.
    """
    from sklearn.decomposition import PCA

    pca = PCA(n_components=VAR_KEPT, svd_solver="full").fit(bg)
    proj = pca.transform(cand)
    recon = pca.inverse_transform(proj)
    resid = np.linalg.norm(cand - recon, axis=1)
    return resid, int(pca.n_components_)


def _auc(score: np.ndarray, is_rob: np.ndarray) -> float:
    """AUC == Mann-Whitney U / (n_rob * n_rej): P(a ROBUST scores above rejected)."""
    from scipy.stats import mannwhitneyu

    rob, rej = score[is_rob], score[~is_rob]
    if len(rob) == 0 or len(rej) == 0:
        return float("nan")
    u = mannwhitneyu(rob, rej, alternative="two-sided").statistic
    return float(u / (len(rob) * len(rej)))


def _compare(score: np.ndarray, dante: np.ndarray, is_rob: np.ndarray,
             det: np.ndarray) -> dict:
    """Rank correlation with DANTE + ROBUST/rejected separation and AUC.

    Reports AUC per detector as well, so a separation that is really a detector
    confound (energy standing in for which interferometer) is visible rather
    than hidden inside the pooled number.
    """
    from scipy.stats import spearmanr

    rob, rej = score[is_rob], score[~is_rob]
    return {
        "rank_correlation_with_dante": float(spearmanr(score, dante).statistic),
        "robust_mean": float(rob.mean()), "rejected_mean": float(rej.mean()),
        "auc_robust_vs_rejected": _auc(score, is_rob),
        "auc_by_detector": {d: _auc(score[det == d], is_rob[det == d])
                            for d in ("H1", "L1")},
    }


def run(run_name: str = "O4a", n_candidates: int = 40,
        n_background: int = 1300, seed: int = 42) -> dict:
    qrange = tuple(
        int(value) for value in load_config()["preprocessing"]["qrange"]
    )
    tax, contract = load_taxonomy_view(
        AGG,
        run_name,
        index_qrange=qrange,
        query_qrange=qrange,
    )
    tax["gps_start"] = tax.gps_start.astype(int)
    threshold_path = AGG / (
        f"dsd_thresholds_{run_name.lower()}_{contract.representation}.json"
    )
    threshold_record = json.loads(threshold_path.read_text(encoding="utf-8"))
    if (
        threshold_record.get("representation", {}).get("variant")
        != contract.representation
    ):
        raise RuntimeError("DSD threshold representation mismatch")

    cands = _sample(
        tax,
        n_candidates,
        threshold_record["thresholds"],
    )
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
        f"pca_baseline_candidate_feats_{run_name.lower()}_"
        f"{contract.cache_tag}_{qrange_tag(qrange)}_"
        f"n{n_candidates}_s{seed}_{candidate_key_sha256[:12]}.npz"
    )
    background_cache = AGG / (
        f"pca_baseline_background_feats_{run_name.lower()}_"
        f"{contract.cache_tag}_{qrange_tag(qrange)}_"
        f"n{n_background}_s{seed}.npz"
    )
    background_ledger = background_cache.with_name(
        f"{background_cache.stem}_ledger.csv"
    )
    p5_candidate_cache = AGG / (
        f"dsd_index_stability_candidate_tokens_{run_name.lower()}_"
        f"{contract.cache_tag}_{qrange_tag(qrange)}_"
        f"n{n_candidates}_s{seed}_{candidate_key_sha256[:12]}.npz"
    )
    p5_background_cache = AGG / (
        f"dsd_index_stability_background_tokens_{run_name.lower()}_"
        f"{contract.cache_tag}_{qrange_tag(qrange)}_"
        f"n{n_background}_h300_s{seed}.npz"
    )
    p5_background_ledger = p5_background_cache.with_name(
        f"{p5_background_cache.stem}_ledger.csv"
    )
    if candidate_cache.exists():
        logger.info(
            "loading cached candidate features from %s",
            candidate_cache.name,
        )
        z = np.load(candidate_cache, allow_pickle=False)
        cand_feat, cand_energy, kept = z["cand_feat"], z["cand_energy"], z["kept"]
        if (
            tuple(int(value) for value in z["qrange"].tolist()) != qrange
            or str(z["representation"].item()) != contract.representation
            or not np.array_equal(z["candidate_keys"], candidate_keys)
            or str(z["candidate_keys_sha256"].item())
            != candidate_key_sha256
        ):
            raise RuntimeError(
                f"PCA candidate feature cache contract mismatch: "
                f"{candidate_cache}"
            )
        cands = cands[kept].reset_index(drop=True)
    elif p5_candidate_cache.exists():
        logger.info(
            "deriving candidate pixel cache from shared P5 products in %s",
            p5_candidate_cache.name,
        )
        shared = np.load(p5_candidate_cache, allow_pickle=False)
        required_shared = {"pca_feat", "pca_energy"}
        if not required_shared.issubset(shared.files):
            raise RuntimeError(
                "P5 candidate cache predates shared P5/P10 feature encoding"
            )
        cand_feat = shared["pca_feat"]
        cand_energy = shared["pca_energy"]
        kept = shared["kept"]
        if (
            tuple(int(value) for value in shared["qrange"].tolist())
            != qrange
            or str(shared["representation"].item())
            != contract.representation
            or not np.array_equal(shared["candidate_keys"], candidate_keys)
            or str(shared["candidate_keys_sha256"].item())
            != candidate_key_sha256
            or len(cand_feat) != int(kept.sum())
            or len(cand_energy) != int(kept.sum())
        ):
            raise RuntimeError("Shared P5 candidate feature contract mismatch")
        cands = cands[kept].reset_index(drop=True)
        np.savez_compressed(
            candidate_cache,
            cand_feat=cand_feat,
            cand_energy=cand_energy,
            kept=kept,
            candidate_keys=candidate_keys,
            candidate_keys_sha256=np.asarray(candidate_key_sha256),
            qrange=np.asarray(qrange),
            representation=np.asarray(contract.representation),
            derived_from=np.asarray(str(p5_candidate_cache)),
            derived_from_sha256=np.asarray(
                _sha256_file(p5_candidate_cache)
            ),
        )
    else:
        logger.info(
            "encoding candidate spectrograms "
            "(raw_qgram Q=%s, [gps+4, gps+36])",
            qrange,
        )
        cand_feat, cand_energy, kept = _encode_candidates(cands, qrange)
        cands = cands[kept].reset_index(drop=True)
        for name, arr in (
            ("cand_feat", cand_feat),
            ("cand_energy", cand_energy),
        ):
            if not np.isfinite(arr).all():
                raise ValueError(
                    f"{name} has non-finite values; refusing to cache "
                    "poisoned features (see _features clip)."
                )
        np.savez_compressed(
            candidate_cache,
            cand_feat=cand_feat,
            cand_energy=cand_energy,
            kept=kept,
            candidate_keys=candidate_keys,
            candidate_keys_sha256=np.asarray(candidate_key_sha256),
            qrange=np.asarray(qrange),
            representation=np.asarray(contract.representation),
        )
        logger.info(
            "cached candidate features to %s",
            candidate_cache.name,
        )

    if background_cache.exists():
        logger.info(
            "loading cached background features from %s",
            background_cache.name,
        )
        if not background_ledger.exists():
            raise RuntimeError(
                f"PCA background feature cache lacks ledger: "
                f"{background_ledger}"
            )
        z_bg = np.load(background_cache, allow_pickle=False)
        bg_feat = z_bg["bg_feat"]
        ledger = pd.read_csv(background_ledger)
        if (
            tuple(int(value) for value in z_bg["qrange"].tolist()) != qrange
            or str(z_bg["representation"].item())
            != contract.representation
            or str(z_bg["detector"].item()) != "L1"
            or len(bg_feat) != n_background
            or len(ledger) != n_background
            or not np.array_equal(
                ledger["t_bg"].to_numpy(dtype=float),
                z_bg["t_bg"].astype(float),
            )
            or str(z_bg["ledger_sha256"].item())
            != _sha256_file(background_ledger)
        ):
            raise RuntimeError(
                f"PCA background feature cache contract mismatch: "
                f"{background_cache}"
            )
    elif p5_background_cache.exists():
        logger.info(
            "deriving PCA background cache from shared P5 products in %s",
            p5_background_cache.name,
        )
        if not p5_background_ledger.exists():
            raise RuntimeError(
                "Shared P5 background products lack their GPS ledger"
            )
        shared_bg = np.load(p5_background_cache, allow_pickle=False)
        required_shared = {"pca_bg_feat", "pca_bg_energy", "t_bg"}
        if not required_shared.issubset(shared_bg.files):
            raise RuntimeError(
                "P5 background cache predates shared P5/P10 feature encoding"
            )
        shared_ledger = pd.read_csv(p5_background_ledger)
        bg_feat = shared_bg["pca_bg_feat"]
        bg_energy = shared_bg["pca_bg_energy"]
        background_times = shared_bg["t_bg"][:n_background].astype(float)
        if (
            tuple(int(value) for value in shared_bg["qrange"].tolist())
            != qrange
            or str(shared_bg["representation"].item())
            != contract.representation
            or str(shared_bg["detector"].item()) != "L1"
            or str(shared_bg["ledger_sha256"].item())
            != _sha256_file(p5_background_ledger)
            or len(bg_feat) != n_background
            or len(bg_energy) != n_background
            or len(shared_ledger) < n_background
            or not np.array_equal(
                shared_ledger["t_bg"].to_numpy(dtype=float)[:n_background],
                background_times,
            )
            or not shared_ledger["role"].astype(str).iloc[
                :n_background
            ].eq("index_pool").all()
        ):
            raise RuntimeError("Shared P5 background feature contract mismatch")
        ledger = pd.DataFrame(
            {
                "ordinal": np.arange(n_background, dtype=int),
                "role": "pca_fit",
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
            bg_feat=bg_feat,
            bg_energy=bg_energy,
            t_bg=background_times,
            ledger_sha256=np.asarray(ledger_sha256),
            detector=np.asarray("L1"),
            qrange=np.asarray(qrange),
            representation=np.asarray(contract.representation),
            derived_from=np.asarray(str(p5_background_cache)),
            derived_from_sha256=np.asarray(
                _sha256_file(p5_background_cache)
            ),
        )
    else:
        logger.info(f"collecting {n_background} vetoed background segments")
        segs = list(iter_clean_segments(run_name.lower(), "L1", n_background, seed=seed))
        if len(segs) != n_background:
            raise RuntimeError(
                f"Only {len(segs)}/{n_background} clean P10 backgrounds "
                "were available"
            )
        logger.info("encoding background spectrograms (raw_qgram)")
        bg_feat, bg_energy = _encode_background(segs, qrange)
        for name, arr in (("bg_feat", bg_feat), ("bg_energy", bg_energy)):
            if not np.isfinite(arr).all():
                raise ValueError(
                    f"{name} has non-finite values; refusing to cache "
                    "poisoned features (see _features clip)."
                )
        background_times = np.asarray(
            [segment.t_bg for segment in segs],
            dtype=np.float64,
        )
        if len(np.unique(background_times)) != len(background_times):
            raise RuntimeError("P10 background ledger contains duplicate GPS")
        ledger = pd.DataFrame(
            {
                "ordinal": np.arange(n_background, dtype=int),
                "role": "pca_fit",
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
            bg_feat=bg_feat,
            bg_energy=bg_energy,
            t_bg=background_times,
            ledger_sha256=np.asarray(ledger_sha256),
            detector=np.asarray("L1"),
            qrange=np.asarray(qrange),
            representation=np.asarray(contract.representation),
        )
        logger.info(
            "cached background features and GPS ledger to %s",
            background_cache.name,
        )

    is_rob = (cands.dsd_class == "ROBUST").to_numpy()
    dante = cands.dsd_score.to_numpy()
    det = cands.detector.to_numpy()

    resid, n_comp = _pca_residual(bg_feat, cand_feat)
    logger.info(f"PCA subspace: {n_comp} components for {VAR_KEPT:.0%} variance")

    out = {
        "run": run_name,
        "representation": contract.representation,
        "taxonomy_path": str(contract.path),
        "qrange": list(qrange),
        "n_candidates": int(len(cand_feat)),
        "n_robust": int(is_rob.sum()), "n_rejected": int((~is_rob).sum()),
        "sample_class_counts": {
            str(label): int(count)
            for label, count in cands["dsd_class"].value_counts().items()
        },
        "n_background": int(len(bg_feat)), "seed": seed,
        "feature_dim": int(cand_feat.shape[1]),
        "pca_components": n_comp, "pca_variance_kept": VAR_KEPT,
        "candidate_feature_cache": str(candidate_cache),
        "candidate_feature_cache_sha256": _sha256_file(candidate_cache),
        "candidate_keys_sha256": candidate_key_sha256,
        "background_feature_cache": str(background_cache),
        "background_feature_cache_sha256": _sha256_file(background_cache),
        "background_ledger": str(background_ledger),
        "background_ledger_sha256": _sha256_file(background_ledger),
        "pca_reconstruction_residual": _compare(resid, dante, is_rob, det),
        "spectral_energy": _compare(cand_energy.astype(np.float64), dante, is_rob, det),
        "interpretation_note": (
            "rank_correlation_with_dante near 1 means a pixel-only method already "
            "ranks candidates as DANTE does (the natural-image transfer buys "
            "little ordering power); near 0 means DANTE responds to structure the "
            "classical detector is blind to. auc_robust_vs_rejected near 0.5 means "
            "the classical score alone cannot tell survivors from rejected. This "
            "bounds the transfer's value; it does not reduce its cost (B2)."),
    }
    dest = AGG / (
        f"pca_baseline_{run_name.lower()}_{contract.representation}.json"
    )
    dest.write_text(json.dumps(out, indent=2))
    pr = out["pca_reconstruction_residual"]
    se = out["spectral_energy"]
    logger.info(
        f"PCA-residual: rank-corr {pr['rank_correlation_with_dante']:.3f}, "
        f"AUC {pr['auc_robust_vs_rejected']:.3f} | spectral-energy: rank-corr "
        f"{se['rank_correlation_with_dante']:.3f}, AUC {se['auc_robust_vs_rejected']:.3f}")
    logger.info(f"wrote {dest}")
    record_environment(
        AGG,
        f"pca_baseline_{run_name.lower()}_{contract.representation}",
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-candidates", type=int, default=40,
                   help="Near-threshold candidates per (class, detector).")
    p.add_argument("--n-background", type=int, default=1300,
                   help="Vetoed background segments the PCA subspace is fit on.")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--pilot", action="store_true",
                   help="Fast machinery check on a small pool and background.")
    a = p.parse_args()
    if a.pilot:
        run(a.run, n_candidates=8, n_background=120, seed=a.seed)
    else:
        run(a.run, n_candidates=a.n_candidates, n_background=a.n_background,
            seed=a.seed)


if __name__ == "__main__":
    main()
