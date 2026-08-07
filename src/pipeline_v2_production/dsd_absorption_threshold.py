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
import hashlib
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
    CleanSegment, PatchEncoder, iter_clean_segments, raw_qgram,
    spectrogram_to_rgb, topk_score,
)

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
TOKENS_PER_SEGMENT = 1369
PRODUCTION_TOKENS_PER_CENTROID = 1295 * TOKENS_PER_SEGMENT / 1216  # ~1458
TOP_K = 68


def _safe_tag(value: float) -> str:
    """Return a filename-safe, stable representation of a float."""
    return f"{value:g}".replace("-", "m").replace(".", "p")


def _source_hashes() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    paths = [
        Path(__file__).resolve(),
        root / "src" / "core" / "injection.py",
        root / "src" / "core" / "preprocessor.py",
        root
        / "src"
        / "pipeline_v3_multiscale"
        / "norm_leakage"
        / "common.py",
    ]
    return {
        str(path.relative_to(root)).replace("\\", "/"):
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def _experiment_identity(
    *,
    run_name: str,
    detector: str,
    morphology: str,
    amplitude: float,
    duration: float,
    n_background: int,
    n_holdout_bg: int,
    n_holdout_inj: int,
    prevalences,
    seed: int,
    qrange: tuple[int, int],
) -> dict:
    """Fields that determine encoded samples and therefore cache validity."""
    return {
        "schema_version": 2,
        "run": run_name,
        "detector": detector,
        "qrange": list(qrange),
        "morphology": morphology,
        "amplitude": float(amplitude),
        "duration_s": float(duration),
        "n_background": int(n_background),
        "n_holdout_bg": int(n_holdout_bg),
        "n_holdout_inj": int(n_holdout_inj),
        "max_prevalence": float(max(prevalences)),
        "seed": int(seed),
        "sample_rate_hz": 4096,
        "source_sha256": _source_hashes(),
    }


def _identity_digest(identity: dict) -> str:
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _artifact_stem(identity: dict) -> str:
    """Human-readable stem plus a digest of the complete experiment identity."""
    return (
        f"dsd_absorption_{identity['morphology'].lower()}_"
        f"{qrange_tag(tuple(identity['qrange']))}_"
        f"{identity['run'].lower()}_{identity['detector'].lower()}_"
        f"a{_safe_tag(identity['amplitude'])}_"
        f"d{_safe_tag(identity['duration_s'])}_"
        f"n{identity['n_background']}_s{identity['seed']}_"
        f"{_identity_digest(identity)}"
    )


def _background_cache_identity(identity: dict) -> dict:
    """Identity shared by morphologies using the same clean segment split."""
    excluded = {"morphology", "amplitude", "duration_s"}
    value = {key: item for key, item in identity.items() if key not in excluded}
    value["cache_role"] = "background"
    return value


def _whitened_segment_cache_identity(identity: dict, n_pool: int) -> dict:
    value = _background_cache_identity(identity)
    value["cache_role"] = "whitened_segments"
    value["n_pool"] = int(n_pool)
    return value


def _whitened_segment_cache_path(
    identity: dict, *, run_name: str, detector: str, n_pool: int, seed: int
) -> Path:
    segment_identity = _whitened_segment_cache_identity(identity, n_pool)
    digest = _identity_digest(segment_identity)
    return AGG / (
        f"dsd_absorption_whitened_segments_{run_name.lower()}_"
        f"{detector.lower()}_n{n_pool}_s{seed}_{digest}.npz"
    )


def _load_or_collect_whitened_segments(
    *,
    run_name: str,
    detector: str,
    n_pool: int,
    seed: int,
    identity: dict,
) -> tuple[list[CleanSegment], Path]:
    """Cache the deterministic whitened split once for all morphologies."""
    from gwpy.timeseries import TimeSeries

    segment_identity = _whitened_segment_cache_identity(identity, n_pool)
    cache = _whitened_segment_cache_path(
        identity,
        run_name=run_name,
        detector=detector,
        n_pool=n_pool,
        seed=seed,
    )
    if cache.exists():
        with np.load(cache, allow_pickle=False) as value:
            cached_identity = json.loads(str(value["identity_json"].item()))
            gps = value["gps"]
            strain = value["strain"]
        if (
            cached_identity != segment_identity
            or gps.shape != (n_pool,)
            or strain.shape != (n_pool, 32 * 4096)
            or not np.all(np.isfinite(gps))
            or not np.all(np.isfinite(strain))
            or len(np.unique(gps)) != n_pool
        ):
            raise RuntimeError(f"invalid whitened-segment cache: {cache}")
        segments = [
            CleanSegment(
                t_bg=float(t_bg),
                ts_whitened=TimeSeries(
                    values.astype(np.float64),
                    t0=float(t_bg) - 16.0,
                    sample_rate=4096,
                ),
            )
            for t_bg, values in zip(gps, strain)
        ]
        logger.info("loaded %d whitened segments from %s", n_pool, cache.name)
        return segments, cache

    logger.info("collecting %d clean segments (this is the slow part)", n_pool)
    segments = list(
        iter_clean_segments(run_name.lower(), detector, n_pool, seed=seed)
    )
    if len(segments) != n_pool:
        raise RuntimeError(f"only {len(segments)}/{n_pool} clean segments available")
    gps = np.asarray([segment.t_bg for segment in segments], dtype=np.float64)
    strain = np.stack(
        [
            np.asarray(segment.ts_whitened.value, dtype=np.float32)
            for segment in segments
        ]
    )
    if (
        strain.shape != (n_pool, 32 * 4096)
        or not np.all(np.isfinite(strain))
        or len(np.unique(gps)) != n_pool
    ):
        raise RuntimeError("invalid whitened segment population")
    partial = cache.with_suffix(".partial.npz")
    np.savez(
        partial,
        gps=gps,
        strain=strain,
        identity_json=json.dumps(segment_identity, sort_keys=True),
    )
    partial.replace(cache)
    logger.info("cached whitened segments to %s", cache.name)
    return segments, cache


def _seeded_glitch(generator, morphology: str, amplitude: float,
                     duration: float, rng: np.random.Generator) -> np.ndarray:
    """Generate reproducibly even though the legacy generator uses np.random."""
    state = np.random.get_state()
    try:
        np.random.seed(int(rng.integers(0, np.iinfo(np.uint32).max)))
        return generator.generate(morphology, amplitude, duration=duration)
    finally:
        np.random.set_state(state)


def _validate_encoded_counts(
    bg_tokens: np.ndarray,
    inj_tokens: np.ndarray,
    hold_bg_tok: np.ndarray,
    hold_inj_tok: np.ndarray,
    *,
    n_background: int,
    n_holdout_bg: int,
    n_holdout_inj: int,
    max_prevalence: float,
) -> None:
    """Reject partial encodings; missing samples must never become evidence."""
    expected = {
        "background": n_background,
        "index_injected": int(max_prevalence * n_background) + 20,
        "holdout_background": n_holdout_bg,
        "holdout_injected": n_holdout_inj,
    }
    observed = {
        "background": len(bg_tokens),
        "index_injected": len(inj_tokens),
        "holdout_background": len(hold_bg_tok),
        "holdout_injected": len(hold_inj_tok),
    }
    mismatches = {
        name: {"expected": expected[name], "observed": observed[name]}
        for name in expected
        if observed[name] != expected[name]
    }
    if mismatches:
        raise RuntimeError(f"partial absorption encoding: {mismatches}")


def _valid_token_array(tokens: np.ndarray, expected_n: int) -> bool:
    return (
        tokens.shape == (expected_n, 1369, 384)
        and np.all(np.isfinite(tokens))
    )


def _bootstrap_z_interval(
    injected: np.ndarray,
    background: np.ndarray,
    *,
    seed: int,
    n_boot: int = 2000,
) -> list[float]:
    """Percentile CI for the standardized mean separation."""
    rng = np.random.default_rng(seed)
    inj_idx = rng.integers(0, len(injected), size=(n_boot, len(injected)))
    bg_idx = rng.integers(0, len(background), size=(n_boot, len(background)))
    inj_mean = injected[inj_idx].mean(axis=1)
    bg_draws = background[bg_idx]
    bg_mean = bg_draws.mean(axis=1)
    bg_std = bg_draws.std(axis=1, ddof=1)
    z = (inj_mean - bg_mean) / (bg_std + 1e-12)
    return [float(value) for value in np.quantile(z, [0.025, 0.975])]


def _wilson_interval(successes: int, total: int, z: float = 1.959964) -> list[float]:
    """Two-sided 95% Wilson score interval for a binomial fraction."""
    if total <= 0:
        raise ValueError("total must be positive")
    p = successes / total
    denom = 1.0 + z * z / total
    centre = (p + z * z / (2.0 * total)) / denom
    half = (
        z
        * np.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))
        / denom
    )
    return [float(max(0.0, centre - half)), float(min(1.0, centre + half))]


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
        run_name: str = "O4a", detector: str = "L1", seed: int = 42,
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

    def make_glitch():
        return _seeded_glitch(gen, morphology, amplitude, duration, rng)

    identity = _experiment_identity(
        run_name=run_name,
        detector=detector,
        morphology=morphology,
        amplitude=amplitude,
        duration=duration,
        n_background=n_background,
        n_holdout_bg=n_holdout_bg,
        n_holdout_inj=n_holdout_inj,
        prevalences=prevalences,
        seed=seed,
        qrange=qrange,
    )
    stem = _artifact_stem(identity)

    # Background tokens are shared across morphologies with the same sampling
    # contract. Injected tokens retain the complete morphology identity. A
    # valid pair skips strain acquisition as well as encoding.
    AGG.mkdir(parents=True, exist_ok=True)
    bg_identity = _background_cache_identity(identity)
    bg_digest = _identity_digest(bg_identity)
    background_cache = AGG / (
        f"dsd_absorption_background_tokens_{run_name.lower()}_"
        f"{detector.lower()}_{qrange_tag(qrange)}_"
        f"n{n_background}_hb{n_holdout_bg}_hi{n_holdout_inj}_"
        f"p{_safe_tag(float(max(prevalences)))}_s{seed}_{bg_digest}.npz"
    )
    injected_cache = (
        AGG
        / stem.replace("dsd_absorption_", "dsd_absorption_injected_tokens_", 1)
    ).with_suffix(".npz")

    background_valid = False
    injected_valid = False
    background_gps = None
    injected_gps = None
    if background_cache.exists():
        with np.load(background_cache, allow_pickle=False) as encoded:
            cached_identity = (
                json.loads(str(encoded["identity_json"].item()))
                if "identity_json" in encoded.files
                else None
            )
            bg_candidate = encoded["bg"]
            hold_bg_candidate = encoded["hold_bg"]
            background_valid = (
                cached_identity == bg_identity
                and _valid_token_array(bg_candidate, n_background)
                and _valid_token_array(hold_bg_candidate, n_holdout_bg)
            )
            if background_valid:
                bg_tokens = bg_candidate
                hold_bg_tok = hold_bg_candidate
                background_gps = json.loads(str(encoded["gps_json"].item()))
        if not background_valid:
            logger.warning(
                "ignoring background cache with mismatched identity: %s",
                background_cache,
            )
    if injected_cache.exists():
        with np.load(injected_cache, allow_pickle=False) as encoded:
            cached_identity = (
                json.loads(str(encoded["identity_json"].item()))
                if "identity_json" in encoded.files
                else None
            )
            inj_candidate = encoded["inj"]
            hold_inj_candidate = encoded["hold_inj"]
            expected_injected = int(max(prevalences) * n_background) + 20
            injected_valid = (
                cached_identity == identity
                and _valid_token_array(inj_candidate, expected_injected)
                and _valid_token_array(hold_inj_candidate, n_holdout_inj)
            )
            if injected_valid:
                inj_tokens = inj_candidate
                hold_inj_tok = hold_inj_candidate
                injected_gps = json.loads(str(encoded["gps_json"].item()))
        if not injected_valid:
            logger.warning(
                "ignoring injected cache with mismatched identity: %s",
                injected_cache,
            )
    if background_valid and injected_valid:
        if background_gps != injected_gps:
            raise RuntimeError("absorption token caches disagree on GPS split")
        gps_groups = background_gps
        logger.info(
            "loading validated shared background and injected token caches"
        )

    n_pool = (
        n_background + n_holdout_bg + n_holdout_inj
        + int(max(prevalences) * n_background) + 20
    )
    segment_cache = _whitened_segment_cache_path(
        identity,
        run_name=run_name,
        detector=detector,
        n_pool=n_pool,
        seed=seed,
    )
    if background_valid and injected_valid and not segment_cache.is_file():
        raise RuntimeError(
            "validated token caches lack their whitened-segment provenance cache"
        )
    if not (background_valid and injected_valid):
        segs, loaded_segment_cache = _load_or_collect_whitened_segments(
            run_name=run_name,
            detector=detector,
            n_pool=n_pool,
            seed=seed,
            identity=identity,
        )
        if loaded_segment_cache != segment_cache:
            raise RuntimeError("whitened segment cache path mismatch")
        logger.info(f"collected {len(segs)} segments")

        i = 0
        bg_pool = segs[i:i + n_background]; i += n_background
        hold_bg = segs[i:i + n_holdout_bg]; i += n_holdout_bg
        hold_inj_src = segs[i:i + n_holdout_inj]; i += n_holdout_inj
        inj_pool_src = segs[i:]
        gps_groups = {
            "background": [float(seg.t_bg) for seg in bg_pool],
            "holdout_background": [float(seg.t_bg) for seg in hold_bg],
            "holdout_injected_source": [
                float(seg.t_bg) for seg in hold_inj_src
            ],
            "index_injected_source": [
                float(seg.t_bg) for seg in inj_pool_src
            ],
        }
        if background_valid and background_gps != gps_groups:
            raise RuntimeError(
                "shared background cache does not match deterministic GPS split"
            )
        if injected_valid and injected_gps != gps_groups:
            raise RuntimeError(
                "injected cache does not match deterministic GPS split"
            )
        encoder = PatchEncoder()
        if not background_valid:
            logger.info("encoding shared background pool")
            bg_tokens = _encode_segments(
                encoder,
                bg_pool,
                qrange=qrange,
            )
            logger.info("encoding shared held-out background")
            hold_bg_tok = _encode_segments(
                encoder,
                hold_bg,
                qrange=qrange,
            )
            if (
                not _valid_token_array(bg_tokens, n_background)
                or not _valid_token_array(hold_bg_tok, n_holdout_bg)
            ):
                raise RuntimeError("partial shared-background encoding")
            np.savez_compressed(
                background_cache,
                bg=bg_tokens,
                hold_bg=hold_bg_tok,
                identity_json=json.dumps(bg_identity, sort_keys=True),
                gps_json=json.dumps(gps_groups, sort_keys=True),
            )
            logger.info(
                "cached shared background tokens to %s", background_cache.name
            )
        if not injected_valid:
            logger.info("encoding injected index pool")
            inj_tokens = _encode_segments(
                encoder,
                inj_pool_src,
                make_glitch,
                rng,
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
            expected_injected = int(max(prevalences) * n_background) + 20
            if (
                not _valid_token_array(inj_tokens, expected_injected)
                or not _valid_token_array(hold_inj_tok, n_holdout_inj)
            ):
                raise RuntimeError("partial injected encoding")
            np.savez_compressed(
                injected_cache,
                inj=inj_tokens,
                hold_inj=hold_inj_tok,
                identity_json=json.dumps(identity, sort_keys=True),
                gps_json=json.dumps(gps_groups, sort_keys=True),
            )
            logger.info(
                "cached injected tokens to %s", injected_cache.name
            )

    _validate_encoded_counts(
        bg_tokens,
        inj_tokens,
        hold_bg_tok,
        hold_inj_tok,
        n_background=n_background,
        n_holdout_bg=n_holdout_bg,
        n_holdout_inj=n_holdout_inj,
        max_prevalence=float(max(prevalences)),
    )

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
        n_flagged = int(np.sum(s_inj > thr))
        flagged = float(n_flagged / len(s_inj))
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
            "z_injected_vs_background_ci95": _bootstrap_z_interval(
                s_inj,
                s_bg,
                seed=seed + 1009 * (n_inj + 1),
            ),
            "z_control_same_size_all_background": z_ctrl,
            "flagged_fraction": flagged,
            "flagged_count": n_flagged,
            "flagged_total": int(len(s_inj)),
            "flagged_fraction_wilson95": _wilson_interval(
                n_flagged, len(s_inj)
            ),
            "separation": float(s_inj.mean() - thr),
            "raw_scores": {
                "injected_mixed_index": [
                    float(value) for value in s_inj
                ],
                "background_mixed_index": [
                    float(value) for value in s_bg
                ],
                "injected_same_size_control": [
                    float(value) for value in c_inj
                ],
                "background_same_size_control": [
                    float(value) for value in c_bg
                ],
            },
        })
        logger.info(f"prevalence {p:6.1%} | K={cents.shape[0]:4d} | "
                    f"inj {s_inj.mean():.4f} bg {s_bg.mean():.4f} | "
                    f"z={z:+6.2f} (control {z_ctrl:+6.2f}) | flagged {flagged:.0%}")

    out = {
        "schema_version": 2,
        "run": run_name,
        "detector": detector,
        "qrange": list(qrange),
        "morphology": morphology,
        "amplitude": amplitude,
        "duration_s": duration, "n_background": n_background,
        "n_holdout_bg": len(hold_bg_tok), "n_holdout_inj": len(hold_inj_tok),
        "seed": seed,
        "top_k": TOP_K,
        "cache_identity": identity,
        "token_caches": {
            "background": str(background_cache),
            "injected": str(injected_cache),
        },
        "whitened_segment_cache": str(segment_cache),
        "gps_groups": gps_groups,
        "rows": rows,
    }
    dest = AGG / f"{stem}.json"
    dest.write_text(json.dumps(out, indent=2))
    logger.info(f"wrote {dest}")
    record_environment(AGG, stem)
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--morphology", default="Blip")
    p.add_argument("--amplitude", type=float, default=6.0)
    p.add_argument("--duration", type=float, default=1.0)
    p.add_argument("--n-background", type=int, default=300)
    p.add_argument("--run", default="O4a")
    p.add_argument("--detector", default="L1")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--qrange", nargs=2, type=int, metavar=("QMIN", "QMAX"),
                   help="Override the configured Q range.")
    p.add_argument("--pilot", action="store_true",
                   help="Small fast run to validate the machinery end to end.")
    a = p.parse_args()
    if a.pilot:
        run(morphology=a.morphology, amplitude=a.amplitude, duration=a.duration,
            n_background=40, n_holdout_bg=12, n_holdout_inj=12,
            prevalences=(0.0, 0.10, 0.40), run_name=a.run,
            detector=a.detector, seed=a.seed,
            qrange=tuple(a.qrange) if a.qrange else None)
    else:
        run(morphology=a.morphology, amplitude=a.amplitude, duration=a.duration,
            n_background=a.n_background, run_name=a.run,
            detector=a.detector, seed=a.seed,
            qrange=tuple(a.qrange) if a.qrange else None)


if __name__ == "__main__":
    main()
