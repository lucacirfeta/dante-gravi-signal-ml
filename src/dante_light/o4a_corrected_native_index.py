"""Build the corrected O4a native VQ index from the frozen cohort only.

The detector-aware cohort is immutable before this module opens DINOv2 or
computes a representation.  Every raw HDF5 source is re-hashed once, every
clean-window hash is replayed exactly, and only then are patch tokens emitted
for the historical MiniBatchKMeans construction.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native import (
    load_native_contract,
    verify_native_cohort,
)
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.o4a_native_provenance import (
    verify_reference_with_reconciliation,
)


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_index_v1.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_index_v1"
)
SCHEMA_VERSION = 1


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    temporary.replace(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_native_index_contract(
    payload: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    """Validate the index contract, references, and inherited science."""

    value = dict(payload)
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("corrected native-index contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported corrected native-index contract schema")
    for reference in value.get("references", {}).values():
        path = root / str(reference["path"])
        verify_reference_with_reconciliation(
            root=root,
            path=path,
            expected_sha256=str(reference["sha256"]),
            raw_hasher=sha256_file,
        )

    parent = load_native_contract(root)
    if value.get("parent_native_contract_digest") != parent["contract_digest"]:
        raise ContractError("corrected native-index parent contract mismatch")
    historical = parent["historical_parity"]
    clustering = value.get("clustering", {})
    inherited = {
        "centroid_count": int(historical["centroid_count"]),
        "random_seed": int(historical["random_seed"]),
        "raw_embedding_sample_size": int(historical["raw_embedding_sample_size"]),
        "minibatch_kmeans_batch_size": int(
            historical["minibatch_kmeans_batch_size"]
        ),
        "minibatch_kmeans_n_init": historical["minibatch_kmeans_n_init"],
    }
    if clustering != {
        **inherited,
        "algorithm": "sklearn.cluster.MiniBatchKMeans.fit",
        "compute_labels": False,
        "centroid_l2_normalization": True,
        "raw_sample_l2_normalization": True,
        "raw_sample_algorithm": (
            "numpy.default_rng(seed).choice(total_tokens,size,replace=False)"
        ),
    }:
        raise ContractError("corrected native-index clustering drift")
    representation = parent["preprocessing"]["representation"]
    expected = {
        "embedding_dimension": int(representation["embedding_dimension"]),
        "patch_tokens_per_image": int(representation["patch_tokens_per_image"]),
        "image_shape": list(representation["image_shape"]),
        "qrange": list(representation["qrange"]),
        "frequency_range_hz": list(representation["frequency_range_hz"]),
        "colormap": str(representation["colormap"]),
    }
    if value.get("representation") != expected:
        raise ContractError("corrected native-index representation drift")
    if value.get("runtime", {}).get("sklearn_version") != "1.9.0":
        raise ContractError("corrected native-index sklearn version is not frozen")
    return value


def load_native_index_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_REL
    return validate_native_index_contract(
        json.loads(path.read_text(encoding="utf-8")), root.resolve()
    )


def _source_registry(
    rows: Sequence[Mapping[str, Any]], raw_root: Path
) -> list[dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for row in rows:
        sources = list(row.get("context_sources", []))
        if canonical_json_sha256(sources) != row.get("context_sources_digest"):
            raise ContractError("corrected native cohort source digest mismatch")
        for source in sources:
            relative = Path(str(source["relative_path"]))
            if relative.is_absolute() or ".." in relative.parts:
                raise ContractError("corrected native source path escapes raw root")
            absolute = (raw_root / relative).resolve()
            if raw_root != absolute and raw_root not in absolute.parents:
                raise ContractError("corrected native source path escapes raw root")
            normalized = relative.as_posix()
            record = {
                "relative_path": normalized,
                "absolute_path": str(absolute),
                "sha256": str(source["sha256"]),
                "block_interval": [float(value) for value in source["block_interval"]],
            }
            prior = registry.get(normalized)
            if prior is not None and prior != record:
                raise ContractError("corrected native source registry conflicts")
            registry[normalized] = record
    return [registry[key] for key in sorted(registry)]


def _verify_source(record: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(record["absolute_path"]))
    if not path.is_file():
        raise ContractError(f"corrected native raw source is missing: {path}")
    actual = sha256_file(path)
    if actual != str(record["sha256"]):
        raise ContractError(f"corrected native raw source hash mismatch: {path}")
    return {
        "relative_path": str(record["relative_path"]),
        "sha256": actual,
        "size_bytes": int(path.stat().st_size),
        "block_interval": list(record["block_interval"]),
    }


def verify_raw_sources(
    rows: Sequence[Mapping[str, Any]],
    *,
    raw_root: Path,
    workers: int,
) -> list[dict[str, Any]]:
    """Replay each unique complete-file HDF5 SHA-256 exactly once."""

    registry = _source_registry(rows, raw_root.resolve())
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
        verified = list(executor.map(_verify_source, registry))
    if len(verified) != len(registry):
        raise ContractError("corrected native raw-source verification is incomplete")
    return verified


def _read_ledger_context(
    row: Mapping[str, Any], *, raw_root: Path, sample_rate_hz: int, pad_s: float
):
    import h5py
    from gwpy.timeseries import TimeSeries

    gps = float(row["gps_start"])
    expected_start = gps - pad_s
    expected_end = gps + 32.0 + pad_s
    cursor = expected_start
    pieces: list[np.ndarray] = []
    for source in row["context_sources"]:
        block_start, block_end = (float(value) for value in source["block_interval"])
        used_start, used_end = (float(value) for value in source["used_interval"])
        tolerance = 1.0 / sample_rate_hz
        if abs(used_start - cursor) > tolerance or used_end <= used_start:
            raise ContractError("corrected native context sources are not contiguous")
        relative = Path(str(source["relative_path"]))
        path = (raw_root / relative).resolve()
        first = int(round((used_start - block_start) * sample_rate_hz))
        last = int(round((used_end - block_start) * sample_rate_hz))
        expected_shape = (int(round((block_end - block_start) * sample_rate_hz)),)
        with h5py.File(path, "r") as handle:
            if "Strain" not in handle or tuple(handle["Strain"].shape) != expected_shape:
                raise ContractError(f"corrected native HDF5 shape mismatch: {path}")
            values = np.asarray(handle["Strain"][first:last])
        if values.shape != (last - first,):
            raise ContractError(f"corrected native HDF5 slice is short: {path}")
        pieces.append(values)
        cursor = used_end
    tolerance = 1.0 / sample_rate_hz
    if abs(cursor - expected_end) > tolerance:
        raise ContractError("corrected native context interval is incomplete")
    values = np.ascontiguousarray(np.concatenate(pieces))
    expected_samples = int(round((expected_end - expected_start) * sample_rate_hz))
    if values.shape != (expected_samples,) or np.any(~np.isfinite(values)):
        raise ContractError("corrected native raw context is invalid")
    series = TimeSeries(
        values,
        t0=expected_start,
        sample_rate=sample_rate_hz,
        name=f"{row['detector']}:GWOSC-16KHZ_R1_STRAIN",
    )
    return series, values


def _preprocess_replay(arguments: tuple[Mapping[str, Any], str, int, float, str]):
    import matplotlib.pyplot as plt

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )
    from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto

    row, raw_root_value, sample_rate_hz, pad_s, colormap = arguments
    raw_root = Path(raw_root_value)
    series, raw_values = _read_ledger_context(
        row, raw_root=raw_root, sample_rate_hz=sample_rate_hz, pad_s=pad_s
    )
    gps = float(row["gps_start"])
    whitened, pad_info = whiten_context(series, gps, gps + 32.0, pad=pad_s)
    tolerance = max(1.0 / sample_rate_hz, np.finfo(np.float64).eps)
    if (
        float(pad_info["effective_left"]) < pad_s - tolerance
        or float(pad_info["effective_right"]) < pad_s - tolerance
    ):
        raise ContractError("corrected native replay whitening context is incomplete")
    clean = extract_clean_subwindow(whitened, gps, gps + 32.0)
    clean_values = np.ascontiguousarray(clean.value)
    clean_digest = hashlib.sha256(clean_values.tobytes()).hexdigest()
    if (
        clean_digest != row.get("clean_window_sha256")
        or list(clean_values.shape) != row.get("clean_window_shape")
        or str(clean_values.dtype) != row.get("clean_window_dtype")
        or np.any(~np.isfinite(clean_values))
    ):
        raise ContractError("corrected native clean-window replay mismatch")
    if excess_power_veto(clean, sample_rate=sample_rate_hz):
        raise ContractError("corrected native replay changed excess-power disposition")
    spectrogram = generate_qtransform(clean, save_path=None, cmap=colormap)
    cmap = plt.get_cmap(colormap)
    image = np.ascontiguousarray((cmap(spectrogram)[:, :, :3] * 255).astype(np.uint8))
    if image.shape != (256, 256, 3):
        raise ContractError("corrected native replay image shape mismatch")
    replay = {
        "cohort_index": int(row["cohort_index"]),
        "detector": str(row["detector"]),
        "gps_start": gps,
        "identity_digest": str(row["identity_digest"]),
        "context_sources_digest": str(row["context_sources_digest"]),
        "raw_context_sha256": hashlib.sha256(raw_values.tobytes()).hexdigest(),
        "clean_window_sha256": clean_digest,
        "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
    }
    return image, replay


def _encode_images(
    images: Sequence[np.ndarray], *, model: Any, transform: Any, device: Any
) -> np.ndarray:
    import torch
    import torch.nn.functional as functional
    from PIL import Image

    tensors = [transform(Image.fromarray(image)) for image in images]
    batch = torch.stack(tensors).to(device)
    with torch.inference_mode():
        features = model.forward_features(batch)
        tokens = functional.normalize(features["x_norm_patchtokens"], p=2, dim=-1)
    values = np.ascontiguousarray(tokens.cpu().numpy().astype(np.float32))
    if np.any(~np.isfinite(values)):
        raise ContractError("corrected native encoder returned non-finite tokens")
    return values


def cluster_native_tokens(
    tokens: np.ndarray,
    *,
    centroid_count: int,
    batch_size: int,
    seed: int,
    n_init: str,
    raw_sample_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply the frozen historical clustering and raw-sample algorithms."""

    from sklearn.cluster import MiniBatchKMeans

    if tokens.ndim != 2 or tokens.shape[1] != 384 or np.any(~np.isfinite(tokens)):
        raise ContractError("corrected native token matrix is invalid")
    if tokens.shape[0] < centroid_count:
        raise ContractError("corrected native token matrix is too small")
    kmeans = MiniBatchKMeans(
        n_clusters=centroid_count,
        batch_size=batch_size,
        compute_labels=False,
        random_state=seed,
        n_init=n_init,
    )
    kmeans.fit(tokens)
    centroids = np.asarray(kmeans.cluster_centers_, dtype=np.float32)
    centroid_norms = np.linalg.norm(centroids, axis=1, keepdims=True)
    if np.any(centroid_norms <= 0) or np.any(~np.isfinite(centroid_norms)):
        raise ContractError("corrected native centroid norms are invalid")
    centroids = np.ascontiguousarray(centroids / centroid_norms)
    rng = np.random.default_rng(seed)
    n_take = min(int(raw_sample_size), int(tokens.shape[0]))
    indices = rng.choice(tokens.shape[0], size=n_take, replace=False)
    raw_sample = np.asarray(tokens[indices], dtype=np.float32)
    raw_norms = np.linalg.norm(raw_sample, axis=1, keepdims=True)
    if np.any(raw_norms <= 0) or np.any(~np.isfinite(raw_norms)):
        raise ContractError("corrected native raw-sample norms are invalid")
    raw_sample = np.ascontiguousarray(raw_sample / raw_norms)
    return centroids, raw_sample


def _run_key(
    contract: Mapping[str, Any],
    cohort_summary: Mapping[str, Any],
    runtime_contract: Mapping[str, Any],
) -> str:
    return canonical_json_sha256(
        {
            "stage": "build_corrected_detector_aware_native_index",
            "contract_digest": contract["contract_digest"],
            "cohort_artifact_digest": cohort_summary["artifact_digest"],
            "runtime_environment_digest": runtime_contract["runtime_environment"][
                "environment_digest"
            ],
        }
    )


def _index_summary(
    *,
    contract: Mapping[str, Any],
    cohort_summary: Mapping[str, Any],
    runtime_contract: Mapping[str, Any],
    run_key: str,
    index_path: Path,
    replay_path: Path,
    replay_rows: Sequence[Mapping[str, Any]],
    verified_sources: Sequence[Mapping[str, Any]],
    centroids: np.ndarray,
    raw_sample: np.ndarray,
    token_total: int,
) -> dict[str, Any]:
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_BUILT_NATIVE_INDEX",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "parent_native_contract_digest": contract[
            "parent_native_contract_digest"
        ],
        "cohort_artifact_digest": cohort_summary["artifact_digest"],
        "cohort_row_total": int(cohort_summary["row_total"]),
        "counts_by_detector": dict(cohort_summary["counts_by_detector"]),
        "runtime_environment_digest": runtime_contract["runtime_environment"][
            "environment_digest"
        ],
        "index": {
            "filename": index_path.name,
            "sha256": sha256_file(index_path),
            "size_bytes": int(index_path.stat().st_size),
            "centroid_shape": list(centroids.shape),
            "centroid_bytes_sha256": hashlib.sha256(centroids.tobytes()).hexdigest(),
            "raw_sample_shape": list(raw_sample.shape),
            "raw_sample_bytes_sha256": hashlib.sha256(raw_sample.tobytes()).hexdigest(),
            "token_total": int(token_total),
        },
        "replay_ledger": {
            "filename": replay_path.name,
            "sha256": sha256_file(replay_path),
            "row_digest": canonical_json_sha256(list(replay_rows)),
            "row_total": len(replay_rows),
        },
        "raw_sources": {
            "unique_file_count": len(verified_sources),
            "total_size_bytes": sum(int(row["size_bytes"]) for row in verified_sources),
            "manifest_digest": canonical_json_sha256(list(verified_sources)),
            "complete_file_sha256_replayed": True,
        },
        "gates": {
            "clean_window_hash_mismatches": 0,
            "raw_source_hash_mismatches": 0,
            "context_failures": 0,
            "encoder_failures": 0,
            "cohort_only": True,
        },
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def build_native_index(
    *,
    root: Path = ROOT,
    raw_root: Path,
    primary_external_root: Path,
    cohort_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
    workers: int = 8,
    encoder_batch_size: int = 8,
) -> tuple[dict[str, Any], Path]:
    """Build the index after full raw and clean-window replay."""

    if workers < 1 or encoder_batch_size < 1:
        raise ValueError("corrected native-index worker parameters must be positive")
    root = root.resolve()
    raw_root = raw_root.resolve()
    external_root = external_root.resolve()
    contract = load_native_index_contract(root)
    cohort_summary, cohort_run_dir = verify_native_cohort(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        external_root=cohort_external_root.resolve(),
    )
    runtime = load_canonical_runtime_contract(
        root=root, require_current=True, device=device
    )
    import sklearn

    if sklearn.__version__ != contract["runtime"]["sklearn_version"]:
        raise ContractError("corrected native-index sklearn runtime drift")
    run_key = _run_key(contract, cohort_summary, runtime)
    run_dir = external_root / f"native_index_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_path = run_dir / "failure.json"
    summary_path = run_dir / "native_index_summary.json"
    index_path = run_dir / str(contract["output"]["index_filename"])
    replay_path = run_dir / str(contract["output"]["replay_ledger_filename"])
    if summary_path.is_file() or index_path.is_file() or replay_path.is_file():
        return verify_native_index(
            root=root,
            primary_external_root=primary_external_root,
            cohort_external_root=cohort_external_root,
            external_root=external_root,
            device=device,
        )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "cohort_artifact_digest": cohort_summary["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
        "workers": int(workers),
        "encoder_batch_size": int(encoder_batch_size),
        "device": device,
    }
    _atomic_json(run_dir / "run_identity.json", identity)
    rows = _load_jsonl(cohort_run_dir / cohort_summary["ledger"]["filename"])
    rows.sort(key=lambda row: int(row["cohort_index"]))
    try:
        verified_sources = verify_raw_sources(
            rows, raw_root=raw_root, workers=workers
        )
        representation = contract["representation"]
        clustering = contract["clustering"]
        token_total = len(rows) * int(representation["patch_tokens_per_image"])
        embedding_dim = int(representation["embedding_dimension"])
        from src.core.encoder import build_dinov2_transform
        from src.core.model_loader import load_dinov2_model
        import torch

        torch_device = torch.device(device)
        model = load_dinov2_model(torch_device)
        model.eval()
        for parameter in model.parameters():
            parameter.requires_grad = False
        transform = build_dinov2_transform()
        replay_rows: list[dict[str, Any]] = []
        context = mp.get_context("spawn")
        with tempfile.TemporaryDirectory(prefix="dante-native-index-") as temporary:
            token_path = Path(temporary) / "patch_tokens.float32.mmap"
            tokens = np.memmap(
                token_path,
                mode="w+",
                dtype=np.float32,
                shape=(token_total, embedding_dim),
            )
            offset = 0
            with ProcessPoolExecutor(
                max_workers=workers, mp_context=context
            ) as executor:
                for start in range(0, len(rows), encoder_batch_size):
                    batch_rows = rows[start : start + encoder_batch_size]
                    arguments = [
                        (
                            row,
                            str(raw_root),
                            int(contract["preprocessing"]["sample_rate_hz"]),
                            float(contract["preprocessing"]["whitening_pad_s"]),
                            str(representation["colormap"]),
                        )
                        for row in batch_rows
                    ]
                    prepared = list(executor.map(_preprocess_replay, arguments))
                    images = [item[0] for item in prepared]
                    batch_tokens = _encode_images(
                        images, model=model, transform=transform, device=torch_device
                    )
                    expected_shape = (
                        len(batch_rows),
                        int(representation["patch_tokens_per_image"]),
                        embedding_dim,
                    )
                    if batch_tokens.shape != expected_shape:
                        raise ContractError("corrected native patch-token shape mismatch")
                    flattened = batch_tokens.reshape(-1, embedding_dim)
                    tokens[offset : offset + len(flattened)] = flattened
                    for item, patch_values in zip(
                        prepared, batch_tokens, strict=True
                    ):
                        replay = dict(item[1])
                        replay["patch_tokens_sha256"] = hashlib.sha256(
                            np.ascontiguousarray(patch_values).tobytes()
                        ).hexdigest()
                        replay_rows.append(replay)
                    offset += len(flattened)
            if offset != token_total or len(replay_rows) != len(rows):
                raise ContractError("corrected native token extraction is incomplete")
            tokens.flush()
            centroids, raw_sample = cluster_native_tokens(
                tokens,
                centroid_count=int(clustering["centroid_count"]),
                batch_size=int(clustering["minibatch_kmeans_batch_size"]),
                seed=int(clustering["random_seed"]),
                n_init=str(clustering["minibatch_kmeans_n_init"]),
                raw_sample_size=int(clustering["raw_embedding_sample_size"]),
            )
        replay_rows.sort(key=lambda row: int(row["cohort_index"]))
        _atomic_jsonl(replay_path, replay_rows)
        labels = np.asarray(["BG_O4a"] * len(centroids), dtype=str)
        meta = {
            "schema_version": 3,
            "run": "O4a",
            "detectors": ["H1", "L1"],
            "counts_by_detector": dict(cohort_summary["counts_by_detector"]),
            "K": int(clustering["centroid_count"]),
            "seed": int(clustering["random_seed"]),
            "n_segments": len(rows),
            "cohort_artifact_digest": cohort_summary["artifact_digest"],
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "preprocessing": "whiten_context_v1_single_bandpass",
            "colormap": representation["colormap"],
            "qrange": representation["qrange"],
            "qtransform_frange_hz": representation["frequency_range_hz"],
            "qtransform_logf": True,
            "qtransform_output_size": list(representation["image_shape"][:2]),
            "raw_sample_size": int(raw_sample.shape[0]),
            "raw_sample_total_tokens": int(token_total),
            "raw_sample_seed": int(clustering["random_seed"]),
            "detector_identity_inferred": False,
        }
        temporary_index = run_dir / f".{index_path.name}.{os.getpid()}.tmp.npz"
        np.savez_compressed(
            temporary_index,
            embeddings=centroids.astype(np.float32),
            labels=labels,
            raw_embeddings_sample=raw_sample.astype(np.float32),
            meta=json.dumps(meta, sort_keys=True, allow_nan=False),
        )
        temporary_index.replace(index_path)
        summary = _index_summary(
            contract=contract,
            cohort_summary=cohort_summary,
            runtime_contract=runtime,
            run_key=run_key,
            index_path=index_path,
            replay_path=replay_path,
            replay_rows=replay_rows,
            verified_sources=verified_sources,
            centroids=centroids,
            raw_sample=raw_sample,
            token_total=token_total,
        )
        _atomic_json(summary_path, summary)
        failure_path.unlink(missing_ok=True)
        return summary, run_dir
    except BaseException as exc:
        failure = {
            **identity,
            "status": "FAILED_NATIVE_INDEX_BUILD",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_native_index(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    cohort_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    """Verify the completed index, ledger, cardinality, and numeric gates."""

    root = root.resolve()
    contract = load_native_index_contract(root)
    cohort_summary, _cohort_run_dir = verify_native_cohort(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        external_root=cohort_external_root.resolve(),
    )
    runtime = load_canonical_runtime_contract(
        root=root, require_current=True, device=device
    )
    run_key = _run_key(contract, cohort_summary, runtime)
    run_dir = external_root.resolve() / f"native_index_{run_key}"
    summary_path = run_dir / "native_index_summary.json"
    if not summary_path.is_file():
        raise ContractError("corrected native-index summary is missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("corrected native-index artifact digest mismatch")
    if summary.get("status") != "PASS_BUILT_NATIVE_INDEX":
        raise ContractError("corrected native-index run is not PASS")
    if summary.get("run_key") != run_key:
        raise ContractError("corrected native-index run key mismatch")
    index_path = run_dir / summary["index"]["filename"]
    replay_path = run_dir / summary["replay_ledger"]["filename"]
    if sha256_file(index_path) != summary["index"]["sha256"]:
        raise ContractError("corrected native-index SHA-256 mismatch")
    if sha256_file(replay_path) != summary["replay_ledger"]["sha256"]:
        raise ContractError("corrected native replay-ledger SHA-256 mismatch")
    replay_rows = _load_jsonl(replay_path)
    if (
        canonical_json_sha256(replay_rows)
        != summary["replay_ledger"]["row_digest"]
        or len(replay_rows) != int(cohort_summary["row_total"])
    ):
        raise ContractError("corrected native replay-ledger content mismatch")
    with np.load(index_path, allow_pickle=False) as data:
        if set(data.files) != {
            "embeddings",
            "labels",
            "raw_embeddings_sample",
            "meta",
        }:
            raise ContractError("corrected native-index NPZ schema mismatch")
        centroids = np.asarray(data["embeddings"], dtype=np.float32)
        raw_sample = np.asarray(data["raw_embeddings_sample"], dtype=np.float32)
        labels = np.asarray(data["labels"])
        meta = json.loads(str(data["meta"].item()))
    expected_k = int(contract["clustering"]["centroid_count"])
    expected_raw = int(contract["clustering"]["raw_embedding_sample_size"])
    if (
        centroids.shape != (expected_k, 384)
        or raw_sample.shape != (expected_raw, 384)
        or labels.shape != (expected_k,)
        or set(labels.tolist()) != {"BG_O4a"}
    ):
        raise ContractError("corrected native-index array shape mismatch")
    centroid_error = float(np.max(np.abs(np.linalg.norm(centroids, axis=1) - 1.0)))
    raw_error = float(np.max(np.abs(np.linalg.norm(raw_sample, axis=1) - 1.0)))
    if (
        np.any(~np.isfinite(centroids))
        or np.any(~np.isfinite(raw_sample))
        or centroid_error > 2e-6
        or raw_error > 2e-6
    ):
        raise ContractError("corrected native-index normalization gate failed")
    if (
        hashlib.sha256(centroids.tobytes()).hexdigest()
        != summary["index"]["centroid_bytes_sha256"]
        or hashlib.sha256(raw_sample.tobytes()).hexdigest()
        != summary["index"]["raw_sample_bytes_sha256"]
        or meta.get("cohort_artifact_digest") != cohort_summary["artifact_digest"]
        or meta.get("detector_identity_inferred") is not False
    ):
        raise ContractError("corrected native-index provenance mismatch")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "build_native_index",
    "cluster_native_tokens",
    "load_native_index_contract",
    "validate_native_index_contract",
    "verify_native_index",
    "verify_raw_sources",
]
