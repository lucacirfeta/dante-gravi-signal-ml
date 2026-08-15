"""Separate DSD background-draw, K-means-seed and K-value uncertainty.

The production-sized Q64 background and candidate token caches are reused.
The original near-boundary stress sample is complemented by a deterministic
simple random sample from the complete O4a candidate population.  All
endpoints are threshold-independent; no rebuilt-index score is converted into
a production verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.index_contract import load_taxonomy_view  # noqa: E402
from src.core.utils import load_config, normalize_spectrogram  # noqa: E402
from src.pipeline_v2_production.dsd_index_stability import (  # noqa: E402
    AGG,
    SEGMENT_LENGTH,
    TOP_K,
    WINDOW_OFFSET,
    _candidate_key_digest,
)
from src.pipeline_v3_multiscale.norm_leakage.common import (  # noqa: E402
    PatchEncoder,
    raw_qgram,
    spectrogram_to_rgb,
)


PRODUCTION_K = 1216
KM_SEEDS = (42, 314159, 271828, 161803, 57721)
DRAW_SEEDS = (101, 211, 307, 401, 503, 601, 701, 809)
K_VALUES = (512, 1024, 1216, 2048)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def stable_candidate_priority(seed: int, detector: str, gps: int) -> str:
    return hashlib.sha256(f"{seed}|{detector}|{gps}".encode("utf-8")).hexdigest()


def sample_unconditioned(
    taxonomy: pd.DataFrame,
    *,
    n_per_detector: int,
    seed: int,
    excluded_keys: set[str],
) -> pd.DataFrame:
    """Simple random sample within detector, without score/class conditioning."""
    picks = []
    for detector in ("H1", "L1"):
        frame = taxonomy[taxonomy["detector"] == detector].copy()
        frame["gps_start"] = frame["gps_start"].astype(int)
        frame["_key"] = [
            f"{detector}:{gps}" for gps in frame["gps_start"].to_numpy()
        ]
        frame = frame[~frame["_key"].isin(excluded_keys)]
        frame["_priority"] = [
            stable_candidate_priority(seed, detector, int(gps))
            for gps in frame["gps_start"].to_numpy()
        ]
        frame = frame.sort_values(["_priority", "gps_start"])
        if len(frame) < n_per_detector:
            raise RuntimeError(
                f"{detector}: only {len(frame)}/{n_per_detector} candidates"
            )
        picks.append(frame.head(n_per_detector))
    return pd.concat(picks, ignore_index=True).drop(columns=["_priority", "_key"])


def encode_candidates_fail_closed(
    candidates: pd.DataFrame,
    *,
    qrange: tuple[int, int],
    representation: str,
    seed: int,
    batch_size: int,
) -> tuple[np.ndarray, Path, np.ndarray]:
    """Encode every frozen candidate; one failure invalidates the population."""
    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import extract_clean_subwindow, whiten_context

    keys = np.asarray(
        [
            f"{detector}:{int(gps)}"
            for detector, gps in zip(
                candidates["detector"], candidates["gps_start"]
            )
        ]
    )
    digest = _candidate_key_digest(keys)
    cache = (
        Path(AGG)
        / f"cqg_robustness_unconditioned_tokens_o4a_{representation}_"
        f"q4-64_n{len(candidates)}_s{seed}_{digest[:12]}.npz"
    )
    identity = {
        "schema_version": 1,
        "representation": representation,
        "qrange": list(qrange),
        "seed": seed,
        "candidate_keys_sha256": digest,
        "source_sha256": {
            "scripts/run_cqg_robustness_replicates.py": sha256(
                Path(__file__).resolve()
            ),
            "src/core/preprocessor.py": sha256(
                ROOT / "src" / "core" / "preprocessor.py"
            ),
            "src/pipeline_v3_multiscale/norm_leakage/common.py": sha256(
                ROOT
                / "src"
                / "pipeline_v3_multiscale"
                / "norm_leakage"
                / "common.py"
            ),
        },
    }
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as value:
            cached_identity = json.loads(str(value["identity_json"].item()))
            tokens = value["tokens"]
            cached_keys = value["candidate_keys"]
        if (
            cached_identity == identity
            and np.array_equal(cached_keys, keys)
            and tokens.shape == (len(candidates), 1369, 384)
            and np.all(np.isfinite(tokens))
        ):
            return tokens, cache, keys

    images = []
    failures = []
    for row in candidates.itertuples(index=False):
        w0 = float(row.gps_start) + WINDOW_OFFSET
        try:
            ts = fetch_strain_data(
                row.detector,
                w0 - 4.0,
                w0 + SEGMENT_LENGTH + 4.0,
                cache_raw=True,
                edge_tolerance=4.0,
            )
            whitened, _ = whiten_context(
                ts, w0, w0 + SEGMENT_LENGTH, pad=4.0
            )
            clean = extract_clean_subwindow(
                whitened, w0, w0 + SEGMENT_LENGTH
            )
            spec = raw_qgram(clean, qrange=qrange)
            images.append(
                spectrogram_to_rgb(normalize_spectrogram(spec))
            )
        except Exception as exc:  # fail closed after preserving full ledger
            failures.append(
                {
                    "detector": row.detector,
                    "gps_start": int(row.gps_start),
                    "error": repr(exc),
                }
            )
    if failures:
        raise RuntimeError(f"unconditioned candidate encoding failed: {failures}")
    encoder = PatchEncoder()
    tokens = np.concatenate(
        [
            encoder.encode_batch(images[start : start + batch_size])
            for start in range(0, len(images), batch_size)
        ]
    ).astype(np.float32)
    if tokens.shape != (len(candidates), 1369, 384) or not np.all(
        np.isfinite(tokens)
    ):
        raise RuntimeError(f"invalid unconditioned tokens: {tokens.shape}")
    Path(AGG).mkdir(parents=True, exist_ok=True)
    partial = cache.with_suffix(".partial.npz")
    np.savez_compressed(
        partial,
        tokens=tokens,
        candidate_keys=keys,
        identity_json=json.dumps(identity, sort_keys=True),
    )
    partial.replace(cache)
    return tokens, cache, keys


def model_identity(
    *,
    background_sha256: str,
    population_hashes: dict[str, str],
    k: int,
    km_seed: int,
    draw_seed: int | None,
    n_background: int,
) -> dict:
    return {
        "schema_version": 1,
        "representation": "idxq4-64_queryq4-64",
        "background_sha256": background_sha256,
        "population_hashes": population_hashes,
        "k": int(k),
        "km_seed": int(km_seed),
        "draw_seed": draw_seed,
        "n_background": int(n_background),
        "top_k": TOP_K,
        "source_sha256": sha256(Path(__file__).resolve()),
    }


def fit_or_load_model(
    background: np.ndarray,
    populations: dict[str, np.ndarray],
    *,
    identity: dict,
    pilot: bool,
) -> tuple[dict[str, np.ndarray], Path]:
    """Fit one weighted native dictionary and checkpoint scores/centroids."""
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    suffix = "_pilot" if pilot else ""
    cache = Path(AGG) / f"cqg_robustness_model{suffix}_{digest[:16]}.npz"
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as value:
            cached_identity = json.loads(str(value["identity_json"].item()))
            scores = {
                name: value[f"scores_{name}"] for name in populations
            }
        if (
            cached_identity == identity
            and all(
                scores[name].shape == (len(populations[name]),)
                and np.all(np.isfinite(scores[name]))
                for name in populations
            )
        ):
            return scores, cache

    from sklearn.cluster import MiniBatchKMeans

    n_segments, n_patches, width = background.shape
    flat = background.reshape(-1, width)
    draw_seed = identity["draw_seed"]
    if draw_seed is None:
        segment_weights = np.ones(n_segments, dtype=np.float64)
    else:
        sampled = np.random.default_rng(draw_seed).integers(
            0, n_segments, size=n_segments
        )
        segment_weights = np.bincount(
            sampled, minlength=n_segments
        ).astype(np.float64)
    sample_weight = np.repeat(segment_weights, n_patches)
    model = MiniBatchKMeans(
        n_clusters=identity["k"],
        batch_size=4096,
        compute_labels=False,
        random_state=identity["km_seed"],
        n_init="auto",
    )
    model.fit(flat, sample_weight=sample_weight)
    centroids = model.cluster_centers_.astype(np.float32)
    centroids /= np.maximum(
        np.linalg.norm(centroids, axis=1, keepdims=True), 1e-12
    )
    scores = {
        name: topk_scores(tokens, centroids)
        for name, tokens in populations.items()
    }
    partial = cache.with_suffix(".partial.npz")
    np.savez_compressed(
        partial,
        centroids=centroids,
        identity_json=json.dumps(identity, sort_keys=True),
        **{f"scores_{name}": values for name, values in scores.items()},
    )
    partial.replace(cache)
    return scores, cache


def topk_scores(tokens: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    scores = np.empty(len(tokens), dtype=np.float64)
    for index, segment in enumerate(tokens):
        nearest = (1.0 - segment @ centroids.T).min(axis=1)
        selected = np.argpartition(nearest, -TOP_K)[-TOP_K:]
        scores[index] = nearest[selected].mean()
    return scores


def summarize_score_matrix(
    matrix: np.ndarray, *, seed: int, n_boot: int = 1000
) -> dict:
    """Rank/stability summary with candidate-resampling uncertainty."""
    from scipy.stats import spearmanr

    matrix = np.asarray(matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        raise ValueError("score matrix must be (models>=2, candidates)")

    def statistics(values: np.ndarray) -> tuple[float, float, float]:
        rhos = [
            float(spearmanr(values[i], values[j]).statistic)
            for i in range(len(values))
            for j in range(i + 1, len(values))
        ]
        std = values.std(axis=0)
        return float(np.mean(rhos)), float(np.min(rhos)), float(np.median(std))

    rho_mean, rho_min, std_median = statistics(matrix)
    rng = np.random.default_rng(seed)
    boot = np.empty((n_boot, 3), dtype=float)
    for index in range(n_boot):
        draw = rng.integers(0, matrix.shape[1], size=matrix.shape[1])
        boot[index] = statistics(matrix[:, draw])
    return {
        "n_models": int(matrix.shape[0]),
        "n_candidates": int(matrix.shape[1]),
        "pairwise_spearman_mean": rho_mean,
        "pairwise_spearman_min": rho_min,
        "per_candidate_score_std_median": std_median,
        "bootstrap_ci95": {
            "pairwise_spearman_mean": [
                float(value)
                for value in np.quantile(boot[:, 0], [0.025, 0.975])
            ],
            "pairwise_spearman_min": [
                float(value)
                for value in np.quantile(boot[:, 1], [0.025, 0.975])
            ],
            "per_candidate_score_std_median": [
                float(value)
                for value in np.quantile(boot[:, 2], [0.025, 0.975])
            ],
        },
        "bootstrap_replicates": n_boot,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-unconditioned-per-detector", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    qrange = tuple(
        int(value) for value in load_config()["preprocessing"]["qrange"]
    )
    taxonomy, contract = load_taxonomy_view(
        Path(AGG), "O4a", index_qrange=qrange, query_qrange=qrange
    )
    near_cache = (
        Path(AGG)
        / "dsd_index_stability_candidate_tokens_o4a_"
        "idxq4-64_queryq4-64_q4-64_n40_s42_82a03c4b09a0.npz"
    )
    background_cache = (
        Path(AGG)
        / "dsd_index_stability_background_tokens_o4a_"
        "idxq4-64_queryq4-64_q4-64_n1300_h300_s42.npz"
    )
    with np.load(near_cache, allow_pickle=False) as value:
        near_tokens = value["cand"]
        near_keys = value["candidate_keys"]
    with np.load(background_cache, allow_pickle=False) as value:
        background = value["bg"]
    if args.pilot:
        background = background[:120]
        near_tokens = near_tokens[:24]
        populations = {"near_boundary": near_tokens}
        population_hashes = {
            "near_boundary": hashlib.sha256(
                near_keys[:24].tobytes()
            ).hexdigest()
        }
        axes = {
            "background_draw": [
                {"k": 64, "km_seed": 42, "draw_seed": value}
                for value in DRAW_SEEDS[:2]
            ],
            "kmeans_seed": [
                {"k": 64, "km_seed": value, "draw_seed": None}
                for value in KM_SEEDS[:2]
            ],
            "k_value": [
                {"k": value, "km_seed": 42, "draw_seed": None}
                for value in (32, 64)
            ],
        }
        unconditioned = None
        unconditioned_cache = None
        unconditioned_keys = None
    else:
        unconditioned = sample_unconditioned(
            taxonomy,
            n_per_detector=args.n_unconditioned_per_detector,
            seed=args.seed,
            excluded_keys=set(near_keys.astype(str)),
        )
        unconditioned_tokens, unconditioned_cache, unconditioned_keys = (
            encode_candidates_fail_closed(
                unconditioned,
                qrange=qrange,
                representation=contract.representation,
                seed=args.seed,
                batch_size=args.batch_size,
            )
        )
        populations = {
            "near_boundary": near_tokens,
            "unconditioned": unconditioned_tokens,
        }
        population_hashes = {
            "near_boundary": hashlib.sha256(near_keys.tobytes()).hexdigest(),
            "unconditioned": _candidate_key_digest(unconditioned_keys),
        }
        axes = {
            "background_draw": [
                {
                    "k": PRODUCTION_K,
                    "km_seed": 42,
                    "draw_seed": value,
                }
                for value in DRAW_SEEDS
            ],
            "kmeans_seed": [
                {
                    "k": PRODUCTION_K,
                    "km_seed": value,
                    "draw_seed": None,
                }
                for value in KM_SEEDS
            ],
            "k_value": [
                {"k": value, "km_seed": 42, "draw_seed": None}
                for value in K_VALUES
            ],
        }

    background_hash = sha256(background_cache)
    result_axes = {}
    model_artifacts = []
    for axis_index, (axis, configurations) in enumerate(axes.items()):
        score_lists = {name: [] for name in populations}
        for configuration in configurations:
            identity = model_identity(
                background_sha256=background_hash,
                population_hashes=population_hashes,
                n_background=len(background),
                **configuration,
            )
            scores, model_cache = fit_or_load_model(
                background,
                populations,
                identity=identity,
                pilot=args.pilot,
            )
            for name in populations:
                score_lists[name].append(scores[name])
            model_artifacts.append(
                {
                    "axis": axis,
                    "configuration": configuration,
                    "path": repo_relative(model_cache),
                    "sha256": sha256(model_cache),
                }
            )
        result_axes[axis] = {
            "configurations": configurations,
            "populations": {
                name: summarize_score_matrix(
                    np.stack(values),
                    seed=args.seed + 1000 * (axis_index + 1),
                )
                for name, values in score_lists.items()
            },
        }

    result = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "cqg_dsd_robustness_replicates",
        "scope": (
            "Threshold-independent score/rank sensitivity. Rebuilt-index "
            "scores are not production-calibrated verdicts."
        ),
        "representation": contract.representation,
        "qrange": list(qrange),
        "background": {
            "n_segments": int(len(background)),
            "path": repo_relative(background_cache),
            "sha256": background_hash,
        },
        "near_boundary": {
            "n": int(len(near_tokens)),
            "path": repo_relative(near_cache),
            "sha256": sha256(near_cache),
        },
        "unconditioned": (
            {
                "n": int(len(unconditioned)),
                "class_counts": {
                    str(name): int(count)
                    for name, count in unconditioned["dsd_class"]
                    .value_counts()
                    .items()
                },
                "candidate_keys": unconditioned_keys.astype(str).tolist(),
                "token_cache": repo_relative(unconditioned_cache),
                "token_cache_sha256": sha256(unconditioned_cache),
            }
            if unconditioned is not None
            else None
        ),
        "axes": result_axes,
        "model_artifacts": model_artifacts,
        "source_sha256": sha256(Path(__file__).resolve()),
    }
    suffix = "_pilot" if args.pilot else ""
    destination = Path(AGG) / f"cqg_robustness_replicates{suffix}.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"WROTE {destination} SHA256={sha256(destination)}")


if __name__ == "__main__":
    main()
