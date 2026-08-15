"""Held-out Gravity Spy O3b morphology control for the CQG manuscript.

High-confidence public labels are used only as external queries.  Clean O3b
segments build the native DANTE dictionary and a disjoint later clean subset is
the negative population.  The endpoint is known-morphology versus clean
background ranking, not multiclass classification and not O4a recall.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.validate_cross_run_domain_shift import (  # noqa: E402
    QRANGE,
    build_dictionary,
    compatible_cache_record,
    legacy_v2_runtime_equivalence_is_valid,
    topk_scores,
    unit_rows,
)


OUT = ROOT / "data" / "production" / "aggregated"
REFERENCE = ROOT / "data" / "reference"
LABELS = ("Blip", "Scattered_Light", "Koi_Fish")
MIN_CONFIDENCE = 0.95
MIN_SNR = 7.5
GUARD_S = 96.0
QUALITY_RESERVE_PER_CLASS = 20
LEGACY_V2_KNOWN_SOURCE_SHA256 = {
    "scripts/validate_known_glitch_controls.py": "23b01d88a773d6440bf2761409cbe2dffe6b51618e1742ccb6c77e695197c0a8",
    "scripts/validate_cross_run_domain_shift.py": "2a56c705a43ce5ed4c8c4f1c9ed3b74eceae75b533f9237a7132d7f89cb468c0",
    "src/pipeline_v3_multiscale/norm_leakage/common.py": "ecc93a1de771c0810c0e4ebfea0e939a2a8760986a209862c00bf16e342ad9ad",
    "src/core/preprocessor.py": "e31a9b618482cfb4db09048f350bd9084849ff27cf1f88dd94088bf912736fc2",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def known_cache_identity(
    *, detector: str, pool_digest: str, pool_n: int, n_per_class: int
) -> dict:
    from src.core.artifact_manager import model_contract_summary

    model = model_contract_summary()
    return {
        "schema_version": 3,
        "detector": detector,
        "qrange": list(QRANGE),
        "selection_pool_sha256": pool_digest,
        "selection_pool_n": pool_n,
        "labels": list(LABELS),
        "n_per_class": int(n_per_class),
        "quality_gate": "fetch_whiten_qtransform_finite_then_priority_backfill",
        "encoder": {
            key: model[key]
            for key in (
                "artifact_id",
                "repository",
                "revision",
                "source_python_tree_sha256",
                "weights_sha256",
            )
        },
        "source_sha256": {
            path: sha256(ROOT / path)
            for path in (
                "scripts/validate_known_glitch_controls.py",
                "scripts/validate_cross_run_domain_shift.py",
                "src/pipeline_v3_multiscale/norm_leakage/common.py",
                "src/core/preprocessor.py",
                "src/core/model_loader.py",
            )
        },
    }


def legacy_v2_known_cache_identity(
    *, detector: str, pool_digest: str, pool_n: int, n_per_class: int
) -> dict:
    return {
        "schema_version": 2,
        "detector": detector,
        "qrange": list(QRANGE),
        "selection_pool_sha256": pool_digest,
        "selection_pool_n": pool_n,
        "labels": list(LABELS),
        "n_per_class": int(n_per_class),
        "quality_gate": "fetch_whiten_qtransform_finite_then_priority_backfill",
        "source_sha256": dict(LEGACY_V2_KNOWN_SOURCE_SHA256),
    }


def known_cache_identity_is_compatible(
    identity: dict,
    *,
    detector: str,
    pool_digest: str,
    pool_n: int,
    n_per_class: int,
) -> bool:
    kwargs = {
        "detector": detector,
        "pool_digest": pool_digest,
        "pool_n": pool_n,
        "n_per_class": n_per_class,
    }
    if identity == known_cache_identity(**kwargs):
        return True
    return (
        identity == legacy_v2_known_cache_identity(**kwargs)
        and legacy_v2_runtime_equivalence_is_valid()
    )


def stable_priority(seed: int, detector: str, gravityspy_id: str) -> str:
    payload = f"{seed}|{detector}|{gravityspy_id}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def select_manifest(
    catalog: pd.DataFrame,
    *,
    detector: str,
    labels: tuple[str, ...],
    n_per_class: int,
    seed: int,
    excluded_gps: np.ndarray,
) -> list[dict]:
    """Deterministically select a fixed, high-confidence external query set."""
    required = {
        "event_time",
        "ifo",
        "ml_label",
        "ml_confidence",
        "snr",
        "gravityspy_id",
    }
    missing = required - set(catalog.columns)
    if missing:
        raise ValueError(f"Gravity Spy catalog missing columns: {sorted(missing)}")
    frame = catalog[
        (catalog["ifo"] == detector)
        & (catalog["ml_label"].isin(labels))
        & (catalog["ml_confidence"] >= MIN_CONFIDENCE)
        & (catalog["snr"] >= MIN_SNR)
    ].copy()
    frame = frame.drop_duplicates("gravityspy_id")
    if len(excluded_gps):
        times = frame["event_time"].to_numpy(dtype=float)
        keep = np.min(
            np.abs(times[:, None] - np.asarray(excluded_gps)[None, :]), axis=1
        ) >= GUARD_S
        frame = frame[keep]
    frame["selection_priority"] = [
        stable_priority(seed, detector, str(value))
        for value in frame["gravityspy_id"]
    ]
    selected: list[dict] = []
    for label in labels:
        group = frame[frame["ml_label"] == label].sort_values(
            ["selection_priority", "gravityspy_id"]
        )
        if len(group) < n_per_class:
            raise RuntimeError(
                f"{detector}/{label}: only {len(group)}/{n_per_class} "
                "eligible external controls"
            )
        for _, row in group.head(n_per_class).iterrows():
            selected.append(
                {
                    "detector": detector,
                    "label": label,
                    "event_time": float(row["event_time"]),
                    "gravityspy_id": str(row["gravityspy_id"]),
                    "ml_confidence": float(row["ml_confidence"]),
                    "snr": float(row["snr"]),
                    "selection_priority": str(row["selection_priority"]),
                }
            )
    return selected


def manifest_digest(manifest: list[dict]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fetch_query_strain(
    fetcher,
    detector: str,
    start: float,
    end: float,
    *,
    attempts: int = 3,
):
    """Retry transient GWOSC failures without changing shared cache identity."""
    last_error = None
    for attempt in range(attempts):
        try:
            return fetcher(
                detector,
                start,
                end,
                cache_raw=True,
                edge_tolerance=4.0,
            )
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(
        f"query strain unavailable after {attempts} attempts: {last_error}"
    ) from last_error


def stratified_auc(
    positive: np.ndarray,
    negative: np.ndarray,
    *,
    seed: int,
    n_boot: int = 2000,
) -> dict:
    from sklearn.metrics import roc_auc_score

    positive = np.asarray(positive, dtype=float)
    negative = np.asarray(negative, dtype=float)
    y = np.r_[np.ones(len(positive), dtype=int), np.zeros(len(negative), dtype=int)]
    score = np.r_[positive, negative]
    observed = float(roc_auc_score(y, score))
    rng = np.random.default_rng(seed)
    boot = np.empty(n_boot, dtype=float)
    differences = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        pos = rng.choice(positive, size=len(positive), replace=True)
        neg = rng.choice(negative, size=len(negative), replace=True)
        boot_y = np.r_[np.ones(len(pos), dtype=int), np.zeros(len(neg), dtype=int)]
        boot[i] = roc_auc_score(boot_y, np.r_[pos, neg])
        differences[i] = np.median(pos) - np.median(neg)
    return {
        "auc": observed,
        "auc_bootstrap_ci95": [
            float(value) for value in np.quantile(boot, [0.025, 0.975])
        ],
        "median_positive": float(np.median(positive)),
        "median_negative": float(np.median(negative)),
        "median_difference": float(np.median(positive) - np.median(negative)),
        "median_difference_bootstrap_ci95": [
            float(value)
            for value in np.quantile(differences, [0.025, 0.975])
        ],
        "n_positive": int(len(positive)),
        "n_negative": int(len(negative)),
        "bootstrap_replicates": n_boot,
    }


def encode_manifest(
    manifest: list[dict],
    *,
    detector: str,
    batch_size: int,
    n_per_class: int,
) -> tuple[np.ndarray, Path, list[dict], list[dict]]:
    """Encode a deterministic quality-screened query manifest.

    ``manifest`` is an ordered reserve pool fixed before looking at DANTE
    scores.  Segments that cannot be fetched or fail finite-value/Q-transform
    checks are recorded and replaced by the next item of the same morphology.
    This is a generic data-availability gate, not a score-based exclusion.
    """
    pool_digest = manifest_digest(manifest)
    cache = OUT / (
        f"cqg_known_glitch_tokens_o3b_{detector}_q4-64_"
        f"{pool_digest[:12]}.npz"
    )
    identity_kwargs = {
        "detector": detector,
        "pool_digest": pool_digest,
        "pool_n": len(manifest),
        "n_per_class": n_per_class,
    }
    identity = known_cache_identity(**identity_kwargs)
    expected_n = n_per_class * len(LABELS)
    if cache.is_file():
        with np.load(cache, allow_pickle=False) as value:
            cached_identity = json.loads(str(value["identity_json"].item()))
            tokens = value["tokens"]
            selected_manifest = json.loads(
                str(value["selected_manifest_json"].item())
            )
            failures = json.loads(str(value["failures_json"].item()))
        counts = pd.Series(
            [event["label"] for event in selected_manifest]
        ).value_counts().to_dict()
        if (
            known_cache_identity_is_compatible(
                cached_identity, **identity_kwargs
            )
            and tokens.shape == (expected_n, 1369, 384)
            and np.all(np.isfinite(tokens))
            and counts == {label: n_per_class for label in LABELS}
        ):
            return tokens, cache, selected_manifest, failures

    from src.core.data_loader import fetch_strain_data
    from src.core.preprocessor import extract_clean_subwindow, whiten_context
    from src.core.utils import normalize_spectrogram
    from src.pipeline_v3_multiscale.norm_leakage.common import (
        PatchEncoder,
        raw_qgram,
        spectrogram_to_rgb,
    )

    images: list[np.ndarray] = []
    selected_manifest: list[dict] = []
    failures: list[dict] = []
    counts = {label: 0 for label in LABELS}
    for event in manifest:
        label = str(event["label"])
        if counts[label] >= n_per_class:
            continue
        t = float(event["event_time"])
        try:
            ts_super = fetch_query_strain(
                fetch_strain_data,
                detector,
                t - 20.0,
                t + 20.0,
            )
            whitened, _ = whiten_context(ts_super, t - 16.0, t + 16.0, pad=4.0)
            clean = extract_clean_subwindow(whitened, t - 16.0, t + 16.0)
            spec = normalize_spectrogram(
                raw_qgram(
                    clean.crop(t - 16.0, t + 16.0),
                    qrange=QRANGE,
                )
            )
            image = spectrogram_to_rgb(spec)
            if not np.all(np.isfinite(image)):
                raise ValueError("non-finite rendered query image")
            images.append(image)
            selected_manifest.append(event)
            counts[label] += 1
        except Exception as exc:
            failures.append(
                {
                    "gravityspy_id": event["gravityspy_id"],
                    "event_time": t,
                    "label": label,
                    "error": repr(exc),
                }
            )
    if counts != {label: n_per_class for label in LABELS}:
        raise RuntimeError(
            f"{detector}: quality-screened Gravity Spy pool did not fill "
            f"the predeclared class quotas: {counts}; failures={failures}"
        )
    encoder = PatchEncoder()
    chunks = [
        encoder.encode_batch(images[start : start + batch_size])
        for start in range(0, len(images), batch_size)
    ]
    tokens = np.concatenate(chunks).astype(np.float32)
    if tokens.shape != (expected_n, 1369, 384) or not np.all(np.isfinite(tokens)):
        raise RuntimeError(f"{detector}: invalid query tokens {tokens.shape}")
    OUT.mkdir(parents=True, exist_ok=True)
    partial = cache.with_suffix(".partial.npz")
    np.savez_compressed(
        partial,
        tokens=tokens,
        identity_json=json.dumps(identity, sort_keys=True),
        selected_manifest_json=json.dumps(selected_manifest, sort_keys=True),
        failures_json=json.dumps(failures, sort_keys=True),
    )
    partial.replace(cache)
    return tokens, cache, selected_manifest, failures


def analyse_detector(
    detector: str,
    *,
    domain_n: int,
    n_per_class: int,
    seed: int,
    batch_size: int,
) -> dict:
    domain_record = compatible_cache_record("o3b", detector, domain_n, seed)
    if domain_record is None:
        raise FileNotFoundError(
            "run cross-run domain validation first; no compatible cache for "
            f"o3b/{detector}/n={domain_n}/seed={seed}"
        )
    domain_cache, identity = domain_record
    with np.load(domain_cache, allow_pickle=False) as value:
        gps = value["gps"]
        clean_tokens = value["tokens"]

    order = np.argsort(gps)
    cut = max(2, int(round(0.60 * domain_n)))
    train_idx, held_idx = order[:cut], order[cut:]
    catalog_path = REFERENCE / f"gs_classifications_O3b_{detector}.csv"
    catalog = pd.read_csv(catalog_path)
    manifest = select_manifest(
        catalog,
        detector=detector,
        labels=LABELS,
        n_per_class=n_per_class + QUALITY_RESERVE_PER_CLASS,
        seed=seed,
        excluded_gps=gps,
    )
    query_tokens, query_cache, selected_manifest, quality_failures = encode_manifest(
        manifest,
        detector=detector,
        batch_size=batch_size,
        n_per_class=n_per_class,
    )

    k = max(
        16, int(round(cut * clean_tokens.shape[1] / 1458.0))
    )
    centroids = build_dictionary(clean_tokens[train_idx], k, seed)
    held_scores = topk_scores(clean_tokens[held_idx], centroids)
    query_scores = topk_scores(query_tokens, centroids)

    # Simple baseline: nearest clean segment-mean embedding, with no patch
    # dictionary and no label information.
    train_means = unit_rows(clean_tokens[train_idx].mean(axis=1))
    held_means = unit_rows(clean_tokens[held_idx].mean(axis=1))
    query_means = unit_rows(query_tokens.mean(axis=1))
    held_baseline = (1.0 - held_means @ train_means.T).min(axis=1)
    query_baseline = (1.0 - query_means @ train_means.T).min(axis=1)

    metrics = {}
    labels = np.asarray([event["label"] for event in selected_manifest])
    for index, label in enumerate(LABELS):
        selected = labels == label
        metrics[label] = {
            "dante_topk": stratified_auc(
                query_scores[selected],
                held_scores,
                seed=seed + 101 * (index + 1),
            ),
            "segment_mean_1nn_baseline": stratified_auc(
                query_baseline[selected],
                held_baseline,
                seed=seed + 211 * (index + 1),
            ),
            "confidence_min": float(
                min(
                    event["ml_confidence"]
                    for event in selected_manifest
                    if event["label"] == label
                )
            ),
        }
    return {
        "detector": detector,
        "domain_train_n": int(len(train_idx)),
        "clean_heldout_n": int(len(held_idx)),
        "dictionary_k": int(k),
        "query_n_per_class": n_per_class,
        "manifest_sha256": manifest_digest(selected_manifest),
        "manifest": selected_manifest,
        "selection_pool_sha256": manifest_digest(manifest),
        "selection_pool_n": len(manifest),
        "quality_gate": {
            "rule": "fetch_whiten_qtransform_finite_then_priority_backfill",
            "reserve_per_class": QUALITY_RESERVE_PER_CLASS,
            "n_excluded": len(quality_failures),
            "exclusions": quality_failures,
        },
        "separation_guard_s": GUARD_S,
        "catalog": {
            "path": str(catalog_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256(catalog_path),
            "source": "Zenodo record 5649212",
        },
        "token_caches": {
            "clean_o3b": {
                "path": str(domain_cache.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(domain_cache),
            },
            "gravity_spy_queries": {
                "path": str(query_cache.relative_to(ROOT)).replace("\\", "/"),
                "sha256": sha256(query_cache),
            },
        },
        "clean_gps": {
            "train": [float(value) for value in gps[train_idx]],
            "held_out": [float(value) for value in gps[held_idx]],
        },
        "metrics": metrics,
        "raw_scores": {
            "clean_dante": [float(value) for value in held_scores],
            "clean_baseline": [float(value) for value in held_baseline],
            "query_dante": [float(value) for value in query_scores],
            "query_baseline": [float(value) for value in query_baseline],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--detectors", nargs="+", default=["H1", "L1"])
    parser.add_argument("--seed", type=int, default=20260730)
    parser.add_argument("--domain-n", type=int, default=100)
    parser.add_argument("--n-per-class", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    domain_n = 12 if args.pilot else args.domain_n
    n_per_class = 3 if args.pilot else args.n_per_class
    result = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "cqg_known_glitch_controls",
        "scope": (
            "External O3b known-morphology versus clean-background ranking "
            "control; not multiclass classification and not O4a recall."
        ),
        "representation": "idxq4-64_queryq4-64",
        "labels": list(LABELS),
        "selection": {
            "min_ml_confidence": MIN_CONFIDENCE,
            "min_snr": MIN_SNR,
            "n_per_class": n_per_class,
            "quality_reserve_per_class": QUALITY_RESERVE_PER_CLASS,
            "seed": args.seed,
        },
        "detectors": {},
    }
    for detector in args.detectors:
        result["detectors"][detector] = analyse_detector(
            detector,
            domain_n=domain_n,
            n_per_class=n_per_class,
            seed=args.seed,
            batch_size=args.batch_size,
        )
    OUT.mkdir(parents=True, exist_ok=True)
    suffix = "_pilot" if args.pilot else ""
    destination = OUT / f"cqg_known_glitch_controls{suffix}.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"WROTE {destination} SHA256={sha256(destination)}")


if __name__ == "__main__":
    main()
