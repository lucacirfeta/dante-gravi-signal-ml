"""Production-path background domain-shift validation for CQG.

Clean, vetoed O3b and O4a strain is processed with the same Q64 rendering and
frozen DINOv2 patch encoder. For each detector, early sampled segments build
equally sized native dictionaries and later segments are held out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "production" / "aggregated"
QRANGE = (4, 64)
TOP_K = 68
TOKENS_PER_CENTROID = 1458.0
CACHE_SCHEMA_VERSION = 3
LEGACY_CACHE_SCHEMA_VERSION = 2

LEGACY_V2_SOURCE_SHA256 = {
    "scripts/validate_cross_run_domain_shift.py": "2a56c705a43ce5ed4c8c4f1c9ed3b74eceae75b533f9237a7132d7f89cb468c0",
    "src/core/data_loader.py": "ce114c522002c380a24ef6d619c7597c2d1feffd383d2e9da1e378ddfb0b204f",
    "src/core/preprocessor.py": "e31a9b618482cfb4db09048f350bd9084849ff27cf1f88dd94088bf912736fc2",
    "src/pipeline_v3_multiscale/norm_leakage/common.py": "ecc93a1de771c0810c0e4ebfea0e939a2a8760986a209862c00bf16e342ad9ad",
}
G0_LEGACY_EQUIVALENT_RUNTIME_SHA256 = {
    "src/core/data_loader.py": "ce114c522002c380a24ef6d619c7597c2d1feffd383d2e9da1e378ddfb0b204f",
    "src/core/model_loader.py": "831d871fc14bd71462e36024e7a21b89bb050861e2edc9a83f105243731f1ec9",
    "src/core/preprocessor.py": "e31a9b618482cfb4db09048f350bd9084849ff27cf1f88dd94088bf912736fc2",
    "src/pipeline_v3_multiscale/norm_leakage/common.py": "2baa97362564d02cf6fff6048abb4e8854116569dabc2f474e5bd6a730830725",
}
G0_DINOV2_CONTRACT = {
    "revision": "7b187bd4df8efce2cbcbbb67bd01532c19bf4c9c",
    "source_python_tree_sha256": "ca377bf21900d316a2c17dbff04b0e01d44770fe2706becb94a79ac3b60b74ef",
    "weights_sha256": "f433177089a681826f849f194ece3bb48f4d63fb38d32fc837e3dc7a4e5641fb",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cache_identity(run: str, detector: str, n: int, seed: int) -> dict:
    """Complete identity for production-path token reuse."""
    sources = [
        Path(__file__).resolve(),
        ROOT / "src" / "pipeline_v3_multiscale" / "norm_leakage" / "common.py",
        ROOT / "src" / "core" / "preprocessor.py",
        ROOT / "src" / "core" / "data_loader.py",
        ROOT / "src" / "core" / "model_loader.py",
    ]
    from src.core.artifact_manager import model_contract_summary

    model_contract = model_contract_summary()
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "run": run,
        "detector": detector,
        "n": int(n),
        "seed": int(seed),
        "qrange": list(QRANGE),
        "top_k": TOP_K,
        "encoder": {
            "artifact_id": model_contract["artifact_id"],
            "repository": model_contract["repository"],
            "revision": model_contract["revision"],
            "source_python_tree_sha256": model_contract[
                "source_python_tree_sha256"
            ],
            "weights_sha256": model_contract["weights_sha256"],
        },
        "source_sha256": {
            str(path.relative_to(ROOT)).replace("\\", "/"): sha256(path)
            for path in sources
        },
    }


def legacy_v2_cache_identity(
    run: str, detector: str, n: int, seed: int
) -> dict:
    return {
        "schema_version": LEGACY_CACHE_SCHEMA_VERSION,
        "run": run,
        "detector": detector,
        "n": int(n),
        "seed": int(seed),
        "qrange": list(QRANGE),
        "top_k": TOP_K,
        "encoder": "facebook/dinov2-small patch tokens",
        "source_sha256": dict(LEGACY_V2_SOURCE_SHA256),
    }


def legacy_v2_runtime_equivalence_is_valid() -> bool:
    observed = {
        path: sha256(ROOT / path)
        for path in G0_LEGACY_EQUIVALENT_RUNTIME_SHA256
    }
    if observed != G0_LEGACY_EQUIVALENT_RUNTIME_SHA256:
        return False
    from src.core.artifact_manager import model_contract_summary

    model = model_contract_summary()
    return all(
        model.get(key) == value for key, value in G0_DINOV2_CONTRACT.items()
    )


def cache_identity_is_compatible(
    identity: dict,
    run: str,
    detector: str,
    n: int,
    seed: int,
) -> bool:
    if identity == cache_identity(run, detector, n, seed):
        return True
    return (
        identity == legacy_v2_cache_identity(run, detector, n, seed)
        and legacy_v2_runtime_equivalence_is_valid()
    )


def _cache_path(
    run: str, detector: str, n: int, seed: int, schema_version: int
) -> Path:
    return OUT / (
        f"cqg_domain_tokens_{run}_{detector}_q4-64_"
        f"n{n}_s{seed}_v{schema_version}.npz"
    )


def compatible_cache_record(
    run: str, detector: str, n: int, seed: int
) -> tuple[Path, dict] | None:
    for schema_version in (CACHE_SCHEMA_VERSION, LEGACY_CACHE_SCHEMA_VERSION):
        cache = _cache_path(run, detector, n, seed, schema_version)
        if not cache.is_file():
            continue
        with np.load(cache, allow_pickle=False) as value:
            if "identity_json" not in value.files:
                continue
            identity = json.loads(str(value["identity_json"].item()))
        if cache_identity_is_compatible(identity, run, detector, n, seed):
            return cache, identity
    return None


def unit_rows(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-12)


def topk_scores(tokens: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    out = np.empty(len(tokens), dtype=np.float64)
    for i, segment in enumerate(tokens):
        nearest = (1.0 - segment @ centroids.T).min(axis=1)
        idx = np.argpartition(nearest, -TOP_K)[-TOP_K:]
        out[i] = nearest[idx].mean()
    return out


def time_block_ids(gps: np.ndarray, labels: np.ndarray, n_blocks: int = 5) -> np.ndarray:
    """Assign chronological quantile blocks independently inside each run."""

    blocks = np.empty(len(gps), dtype=int)
    for label in np.unique(labels):
        idx = np.flatnonzero(labels == label)
        ordered = idx[np.argsort(gps[idx])]
        for rank, item in enumerate(ordered):
            blocks[item] = min(n_blocks - 1, rank * n_blocks // len(ordered))
    return blocks


def probe_auc(
    features: np.ndarray,
    labels: np.ndarray,
    gps: np.ndarray,
    *,
    n_blocks: int = 5,
    seed: int = 42,
    shuffle: bool = False,
) -> dict:
    """Time-blocked run-classification probe with out-of-fold predictions."""

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    y = np.asarray(labels, dtype=int).copy()
    if shuffle:
        np.random.default_rng(seed).shuffle(y)
    blocks = time_block_ids(np.asarray(gps), np.asarray(labels), n_blocks)
    pred = np.full(len(y), np.nan, dtype=float)
    fold_auc: list[float] = []
    for fold in range(n_blocks):
        test = blocks == fold
        train = ~test
        if len(np.unique(y[train])) < 2 or len(np.unique(y[test])) < 2:
            continue
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=1.0,
                class_weight="balanced",
                max_iter=2000,
                random_state=seed,
            ),
        )
        model.fit(features[train], y[train])
        pred[test] = model.predict_proba(features[test])[:, 1]
        fold_auc.append(float(roc_auc_score(y[test], pred[test])))
    valid = np.isfinite(pred)
    if len(np.unique(y[valid])) < 2:
        raise RuntimeError("probe produced no two-class out-of-fold population")
    observed_auc = float(roc_auc_score(y[valid], pred[valid]))
    bootstrap_rng = np.random.default_rng(seed + 7919)
    by_class = [np.flatnonzero(valid & (y == value)) for value in (0, 1)]
    boot_auc = np.empty(2000, dtype=float)
    for i in range(len(boot_auc)):
        draw = np.concatenate(
            [
                bootstrap_rng.choice(index, size=len(index), replace=True)
                for index in by_class
            ]
        )
        boot_auc[i] = roc_auc_score(y[draw], pred[draw])
    return {
        "auc_oof": observed_auc,
        "auc_oof_bootstrap_ci95": [
            float(value) for value in np.quantile(boot_auc, [0.025, 0.975])
        ],
        "auc_bootstrap_replicates": int(len(boot_auc)),
        "fold_auc": fold_auc,
        "n_oof": int(valid.sum()),
        "n_blocks": n_blocks,
        "shuffle": shuffle,
    }


def bootstrap_mean_difference(
    a: np.ndarray, b: np.ndarray, *, seed: int, n_boot: int = 2000
) -> dict:
    """Bootstrap mean(b)-mean(a) with a percentile interval."""

    rng = np.random.default_rng(seed)
    values = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        values[i] = (
            rng.choice(b, size=len(b), replace=True).mean()
            - rng.choice(a, size=len(a), replace=True).mean()
        )
    return {
        "difference": float(np.mean(b) - np.mean(a)),
        "ci95": [float(x) for x in np.quantile(values, [0.025, 0.975])],
        "bootstrap_replicates": n_boot,
    }


def encode_run_detector(
    run: str, detector: str, n: int, seed: int, batch_size: int
) -> tuple[np.ndarray, np.ndarray]:
    """Return GPS and production-path Q64 patch tokens, using a cache."""

    cache = _cache_path(run, detector, n, seed, CACHE_SCHEMA_VERSION)
    identity = cache_identity(run, detector, n, seed)
    record = compatible_cache_record(run, detector, n, seed)
    if record is not None:
        cache, cached_identity = record
        with np.load(cache, allow_pickle=False) as value:
            gps = value["gps"]
            tokens = value["tokens"]
        if (
            cache_identity_is_compatible(
                cached_identity, run, detector, n, seed
            )
            and gps.shape == (n,)
            and tokens.shape == (n, 1369, 384)
            and np.all(np.isfinite(gps))
            and np.all(np.isfinite(tokens))
            and len(np.unique(gps)) == n
        ):
            return gps, tokens

    from src.core.utils import normalize_spectrogram
    from src.pipeline_v3_multiscale.norm_leakage.common import (
        PatchEncoder,
        iter_clean_segments,
        raw_qgram,
        spectrogram_to_rgb,
    )

    segments = list(iter_clean_segments(run, detector, n, seed=seed))
    if len(segments) != n:
        raise RuntimeError(f"{run}/{detector}: obtained {len(segments)}/{n} segments")
    encoder = PatchEncoder()
    all_tokens: list[np.ndarray] = []
    for start in range(0, n, batch_size):
        chunk = segments[start : start + batch_size]
        images = [
            spectrogram_to_rgb(
                normalize_spectrogram(
                    raw_qgram(
                        segment.ts_whitened.crop(
                            segment.t_bg - 16, segment.t_bg + 16
                        ),
                        qrange=QRANGE,
                    )
                )
            )
            for segment in chunk
        ]
        all_tokens.append(encoder.encode_batch(images))
    gps = np.asarray([segment.t_bg for segment in segments], dtype=np.float64)
    tokens = np.concatenate(all_tokens).astype(np.float32)
    if tokens.shape != (n, 1369, 384) or not np.all(np.isfinite(tokens)):
        raise RuntimeError(
            f"{run}/{detector}: invalid encoded token shape/values {tokens.shape}"
        )
    if len(np.unique(gps)) != n:
        raise RuntimeError(f"{run}/{detector}: duplicate GPS in clean sample")
    OUT.mkdir(parents=True, exist_ok=True)
    partial = cache.with_suffix(".partial.npz")
    np.savez_compressed(
        partial,
        gps=gps,
        tokens=tokens,
        identity_json=json.dumps(identity, sort_keys=True),
    )
    partial.replace(cache)
    return gps, tokens


def build_dictionary(tokens: np.ndarray, k: int, seed: int) -> np.ndarray:
    from sklearn.cluster import MiniBatchKMeans

    flat = tokens.reshape(-1, tokens.shape[-1])
    model = MiniBatchKMeans(
        n_clusters=k,
        batch_size=4096,
        compute_labels=False,
        random_state=seed,
        n_init="auto",
    )
    model.fit(flat)
    return unit_rows(model.cluster_centers_.astype(np.float32))


def analyse_detector(detector: str, n: int, seed: int, batch_size: int) -> dict:
    from scipy.stats import ks_2samp, wasserstein_distance

    datasets: dict[str, dict] = {}
    for run in ("o3b", "o4a"):
        gps, tokens = encode_run_detector(run, detector, n, seed, batch_size)
        order = np.argsort(gps)
        cut = max(2, int(round(0.60 * n)))
        datasets[run] = {
            "gps": gps,
            "tokens": tokens,
            "train_idx": order[:cut],
            "test_idx": order[cut:],
        }

    k = max(
        16,
        int(round(cut * datasets["o3b"]["tokens"].shape[1] / TOKENS_PER_CENTROID)),
    )
    indices = {
        run: build_dictionary(value["tokens"][value["train_idx"]], k, seed)
        for run, value in datasets.items()
    }
    scores: dict[str, dict[str, np.ndarray]] = {}
    for run, value in datasets.items():
        held = value["tokens"][value["test_idx"]]
        scores[run] = {
            index_run: topk_scores(held, centroids)
            for index_run, centroids in indices.items()
        }

    s3, s4 = scores["o3b"]["o3b"], scores["o4a"]["o3b"]
    ks = ks_2samp(s3, s4)
    direct = {
        "o3b_mean": float(s3.mean()),
        "o4a_mean": float(s4.mean()),
        "mean_difference": bootstrap_mean_difference(s3, s4, seed=seed),
        "ks_d": float(ks.statistic),
        "ks_p": float(ks.pvalue),
        "wasserstein": float(wasserstein_distance(s3, s4)),
    }

    o4_cross, o4_native = scores["o4a"]["o3b"], scores["o4a"]["o4a"]
    paired = o4_native - o4_cross
    boot = np.random.default_rng(seed).choice(
        paired, size=(2000, len(paired)), replace=True
    ).mean(axis=1)
    adaptation = {
        "o4a_cross_index_mean": float(o4_cross.mean()),
        "o4a_native_index_mean": float(o4_native.mean()),
        "paired_native_minus_cross_mean": float(paired.mean()),
        "paired_native_minus_cross_ci95": [
            float(x) for x in np.quantile(boot, [0.025, 0.975])
        ],
    }

    features = np.concatenate(
        [
            unit_rows(datasets[run]["tokens"].mean(axis=1))
            for run in ("o3b", "o4a")
        ]
    )
    labels = np.r_[np.zeros(n, dtype=int), np.ones(n, dtype=int)]
    gps = np.concatenate([datasets["o3b"]["gps"], datasets["o4a"]["gps"]])
    probe = probe_auc(features, labels, gps, seed=seed)
    shuffled = [
        probe_auc(features, labels, gps, seed=seed + i + 1, shuffle=True)["auc_oof"]
        for i in range(20)
    ]
    probe["shuffle_auc_mean"] = float(np.mean(shuffled))
    probe["shuffle_auc_interval_95"] = [
        float(x) for x in np.quantile(shuffled, [0.025, 0.975])
    ]
    probe["feature_norm_range"] = [
        float(np.linalg.norm(features, axis=1).min()),
        float(np.linalg.norm(features, axis=1).max()),
    ]

    return {
        "detector": detector,
        "n_per_run": n,
        "train_per_run": cut,
        "test_per_run": n - cut,
        "dictionary_k": k,
        "qrange": list(QRANGE),
        "top_k": TOP_K,
        "seed": seed,
        "gps_splits": {
            run: {
                "train": [
                    float(value)
                    for value in datasets[run]["gps"][datasets[run]["train_idx"]]
                ],
                "held_out": [
                    float(value)
                    for value in datasets[run]["gps"][datasets[run]["test_idx"]]
                ],
            }
            for run in ("o3b", "o4a")
        },
        "score_samples": {
            run: {
                index_run: [float(value) for value in run_scores]
                for index_run, run_scores in score_by_index.items()
            }
            for run, score_by_index in scores.items()
        },
        "direct_shift_same_o3b_index": direct,
        "native_adaptation": adaptation,
        "run_probe": probe,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-per-run-detector", type=int, default=100)
    parser.add_argument("--detectors", nargs="+", default=["H1", "L1"])
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--pilot", action="store_true")
    args = parser.parse_args()
    n = 12 if args.pilot else args.n_per_run_detector

    result = {
        "schema_version": 2,
        "status": "complete",
        "experiment": "cqg_cross_run_domain_shift",
        "runs": ["O3b", "O4a"],
        "representation": "idxq4-64_queryq4-64",
        "n_per_run_detector": n,
        "detectors": {},
        "leakage_controls": {
            "features": "L2-normalized segment-mean patch embeddings only",
            "excluded": ["GPS", "detector", "filename", "image extrema", "norm"],
            "split": "chronological blocks assigned independently within run",
        },
        "source_sha256": cache_identity(
            "o3b", args.detectors[0], n, args.seed
        )["source_sha256"],
    }
    for detector in args.detectors:
        result["detectors"][detector] = analyse_detector(
            detector, n, args.seed, args.batch_size
        )

    OUT.mkdir(parents=True, exist_ok=True)
    result["token_caches"] = []
    for detector in args.detectors:
        for run in ("o3b", "o4a"):
            record = compatible_cache_record(run, detector, n, args.seed)
            if record is None:
                raise RuntimeError(
                    f"No compatible token cache after analysis: {run}/{detector}"
                )
            cache, identity = record
            result["token_caches"].append(
                {
                    "path": str(cache.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": sha256(cache),
                    "identity": identity,
                }
            )
    suffix = "_pilot" if args.pilot else ""
    path = OUT / f"cqg_cross_run_domain_shift{suffix}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"WROTE {path} SHA256={sha256(path)}")


if __name__ == "__main__":
    main()
