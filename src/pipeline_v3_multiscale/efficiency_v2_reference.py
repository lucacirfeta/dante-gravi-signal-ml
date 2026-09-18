"""Contamination-proof short-scale references for efficiency v2.

The builder consumes only the frozen ``short_scale_index`` and
``short_scale_calibration`` roles.  It replays raw-source hashes, canonical
whitening, centered short-scale Q transforms, DINOv2 patch tokens, per-scale
detector dictionaries, and detector/raw-block bootstrap thresholds.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import multiprocessing as mp
import os
import platform
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import (
    ROOT,
    _read_jsonl,
    _verify_rows,
    load_contract,
    sha256_file,
    verify_cohort,
)

REFERENCE_CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2_reference.json")
SCHEMA_VERSION = 1
SCALE_LABELS = ("0.5", "1", "2", "4")


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


def _atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.stem}.{os.getpid()}.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    temporary.replace(path)


def validate_reference_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("multiscale reference contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported multiscale reference schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-reference":
        raise ContractError("multiscale reference contract id changed")
    if value.get("status") != "APPROVED_REFERENCE_BUILD_INPUT":
        raise ContractError("multiscale reference build is not approved")

    parent = load_contract(root.resolve())
    parent_ref = value.get("parent_contract", {})
    parent_path = root / str(parent_ref.get("path", ""))
    if (
        parent_ref.get("contract_digest") != parent["contract_digest"]
        or not parent_path.is_file()
        or sha256_file(parent_path) != parent_ref.get("sha256")
    ):
        raise ContractError("multiscale parent contract mismatch")
    cohort = value.get("cohort", {})
    if (
        cohort.get("status") != "PASS_FROZEN_MULTISCALE_EFFICIENCY_V2_COHORT"
        or int(cohort.get("row_total", -1)) != 11280
    ):
        raise ContractError("multiscale frozen cohort reference changed")
    gates = value.get("gates", {})
    expected_gates = {
        "index_rows_per_detector": 500,
        "calibration_rows_per_detector": 5000,
        "scales": [0.5, 1.0, 2.0, 4.0],
        "centroids_per_detector_scale": 275,
        "scores_per_detector_scale": 5000,
        "bootstrap_replicates": 2000,
        "bootstrap_confidence": 0.95,
        "bootstrap_unit": "raw_source_block",
        "detectors_pooled": False,
        "scales_pooled": False,
        "legacy_artifacts_consumed": False,
    }
    if any(gates.get(key) != expected for key, expected in expected_gates.items()):
        raise ContractError("multiscale reference gates changed")
    for name, reference in value.get("references", {}).items():
        path = root / str(reference["path"])
        if not path.is_file() or sha256_file(path) != str(reference["sha256"]):
            raise ContractError(f"multiscale reference source mismatch: {name}")
    return value


def load_reference_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root.resolve() / REFERENCE_CONTRACT_REL
    return validate_reference_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root.resolve()
    )


def _reference_run_key(
    *,
    reference_contract_digest: str,
    cohort_artifact_digest: str,
    runtime_environment_digest: str,
) -> str:
    return canonical_json_sha256(
        {
            "stage": "build_multiscale_efficiency_v2_reference",
            "reference_contract_digest": reference_contract_digest,
            "cohort_artifact_digest": cohort_artifact_digest,
            "runtime_environment_digest": runtime_environment_digest,
        }
    )


def raw_block_bootstrap_p99(
    scores: Sequence[float],
    raw_block_labels: Sequence[str],
    *,
    n_resamples: int,
    seed: int,
    confidence: float,
    percentile: float,
) -> dict[str, float | int | str]:
    """Bootstrap p99 by resampling complete raw source blocks."""

    values = np.asarray(scores, dtype=np.float64)
    labels = np.asarray(raw_block_labels, dtype=str)
    if (
        values.ndim != 1
        or labels.shape != values.shape
        or values.size == 0
        or np.any(~np.isfinite(values))
    ):
        raise ContractError("invalid block-bootstrap inputs")
    unique = np.unique(labels)
    if unique.size < 2:
        raise ContractError("block bootstrap needs at least two raw source blocks")
    grouped = [np.flatnonzero(labels == label) for label in unique]
    rng = np.random.default_rng(seed)
    boot = np.empty(int(n_resamples), dtype=np.float64)
    for index in range(int(n_resamples)):
        draw = rng.integers(0, len(grouped), size=len(grouped))
        sampled = np.concatenate([grouped[position] for position in draw])
        boot[index] = np.percentile(values[sampled], percentile)
    alpha = (1.0 - float(confidence)) * 50.0
    return {
        "method": "detector_raw_source_block_bootstrap_p99",
        "percentile": float(percentile),
        "point_p99": float(np.percentile(values, percentile)),
        "ci_lower": float(np.percentile(boot, alpha)),
        "ci_upper": float(np.percentile(boot, 100.0 - alpha)),
        "confidence": float(confidence),
        "n_resamples": int(n_resamples),
        "score_count": int(values.size),
        "raw_block_count": int(unique.size),
    }


def _read_raw_context(
    row: Mapping[str, Any], *, raw_root: Path, sample_rate_hz: int
) -> tuple[Any, np.ndarray]:
    import h5py
    from gwpy.timeseries import TimeSeries

    source = row["raw_block"]
    path = (raw_root / str(source["source_relative_path"])).resolve()
    block_start = float(source["gps_start"])
    block_end = float(source["gps_end"])
    context_start, context_end = (float(value) for value in row["context_interval"])
    first = round((context_start - block_start) * sample_rate_hz)
    last = round((context_end - block_start) * sample_rate_hz)
    expected_shape = (round((block_end - block_start) * sample_rate_hz),)
    with h5py.File(path, "r") as handle:
        if "Strain" not in handle or tuple(handle["Strain"].shape) != expected_shape:
            raise ContractError(f"multiscale HDF5 shape mismatch: {path}")
        values = np.ascontiguousarray(handle["Strain"][first:last])
    expected_samples = round((context_end - context_start) * sample_rate_hz)
    if values.shape != (expected_samples,) or np.any(~np.isfinite(values)):
        raise ContractError("multiscale raw context is invalid")
    series = TimeSeries(
        values,
        t0=context_start,
        sample_rate=sample_rate_hz,
        name=f"{row['detector']}:GWOSC-16KHZ_R1_STRAIN",
    )
    return series, values


def _preprocess_row(
    arguments: tuple[Mapping[str, Any], str, Mapping[str, Any]],
) -> tuple[list[np.ndarray], dict[str, Any]]:
    import matplotlib.pyplot as plt

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    row, raw_root_value, parent = arguments
    preprocessing = parent["preprocessing"]
    representation = parent["representation"]
    sample_rate = int(preprocessing["sample_rate_hz"])
    pad = float(preprocessing["whitening_pad_s"])
    duration = float(preprocessing["analysis_duration_s"])
    gps = float(row["gps_start"])
    series, raw_values = _read_raw_context(
        row, raw_root=Path(raw_root_value), sample_rate_hz=sample_rate
    )
    whitened, pad_info = whiten_context(series, gps, gps + duration, pad=pad)
    tolerance = 1.0 / sample_rate
    if (
        float(pad_info["effective_left"]) < pad - tolerance
        or float(pad_info["effective_right"]) < pad - tolerance
    ):
        raise ContractError("multiscale whitening context is incomplete")
    clean = extract_clean_subwindow(whitened, gps, gps + duration)
    clean_values = np.ascontiguousarray(clean.value)
    if np.any(~np.isfinite(clean_values)):
        raise ContractError("multiscale clean window is non-finite")
    center = gps + duration / 2.0
    conditional = representation["conditional_multiscale"]
    cmap_name = str(representation["colormap"])
    cmap = plt.get_cmap(cmap_name)
    images: list[np.ndarray] = []
    image_hashes: dict[str, str] = {}
    for label, scale in zip(SCALE_LABELS, conditional["scales_s"], strict=True):
        scale = float(scale)
        short = clean.crop(center - scale / 2.0, center + scale / 2.0)
        spectrogram = generate_qtransform(
            short,
            qrange=tuple(conditional["qrange"]),
            frange=tuple(representation["frequency_range_hz"]),
            output_size=tuple(representation["image_shape"][:2]),
            save_path=None,
            cmap=cmap_name,
        )
        image = np.ascontiguousarray(
            (cmap(spectrogram)[:, :, :3] * 255).astype(np.uint8)
        )
        if list(image.shape) != representation["image_shape"]:
            raise ContractError("multiscale image shape changed")
        images.append(image)
        image_hashes[label] = hashlib.sha256(image.tobytes()).hexdigest()
    replay = {
        "detector": str(row["detector"]),
        "role": str(row["role"]),
        "role_index": int(row["role_index"]),
        "gps_start": gps,
        "identity_digest": str(row["identity_digest"]),
        "raw_source_sha256": str(row["raw_block"]["source_sha256"]),
        "raw_context_sha256": hashlib.sha256(raw_values.tobytes()).hexdigest(),
        "clean_window_sha256": hashlib.sha256(clean_values.tobytes()).hexdigest(),
        "image_sha256_by_scale": image_hashes,
    }
    return images, replay


def _encode_images(
    images: Sequence[np.ndarray], *, model: Any, transform: Any, device: Any
) -> np.ndarray:
    import torch
    from PIL import Image
    from torch.nn import functional

    tensors = [transform(Image.fromarray(image)) for image in images]
    batch = torch.stack(tensors).to(device)
    with torch.inference_mode():
        tokens = model.forward_features(batch)["x_norm_patchtokens"]
        tokens = functional.normalize(tokens, p=2, dim=-1)
    result = np.ascontiguousarray(tokens.cpu().numpy().astype(np.float32))
    if np.any(~np.isfinite(result)):
        raise ContractError("multiscale encoder returned non-finite tokens")
    return result


def _verify_source(argument: tuple[str, str]) -> dict[str, Any]:
    path_value, expected = argument
    path = Path(path_value)
    actual = sha256_file(path)
    if actual != expected:
        raise ContractError(f"multiscale raw source SHA-256 mismatch: {path}")
    return {"path": str(path), "sha256": actual, "size_bytes": path.stat().st_size}


def verify_raw_sources(
    rows: Sequence[Mapping[str, Any]], *, raw_root: Path, workers: int
) -> list[dict[str, Any]]:
    registry: dict[Path, str] = {}
    for row in rows:
        source = row["raw_block"]
        path = (raw_root / str(source["source_relative_path"])).resolve()
        digest = str(source["source_sha256"])
        previous = registry.setdefault(path, digest)
        if previous != digest:
            raise ContractError("multiscale raw source has divergent expected hashes")
    arguments = [(str(path), digest) for path, digest in sorted(registry.items())]
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
        return list(executor.map(_verify_source, arguments))


def _runtime_identity(*, device: str, model: Any) -> dict[str, Any]:
    import torch

    packages = {}
    for name in ("numpy", "scikit-learn", "torch", "torchvision", "gwpy", "h5py"):
        packages[name] = importlib.metadata.version(name)
    cuda: dict[str, Any] | None = None
    if device == "cuda":
        if not torch.cuda.is_available():
            raise ContractError("CUDA was requested but is unavailable")
        cuda = {
            "name": torch.cuda.get_device_name(0),
            "capability": list(torch.cuda.get_device_capability(0)),
            "torch_cuda": torch.version.cuda,
        }
    model_provenance = dict(getattr(model, "dante_model_provenance", {}))
    model_provenance.pop("weights_path", None)
    body = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "device": device,
        "packages": packages,
        "cuda": cuda,
        "model": model_provenance,
    }
    return {**body, "environment_digest": canonical_json_sha256(body)}


def _update_progress(
    path: Path, *, stage: str, completed: int, total: int, started: float
) -> None:
    elapsed = max(0.0, time.monotonic() - started)
    rate = completed / elapsed if elapsed > 0 else 0.0
    remaining = (total - completed) / rate if rate > 0 else None
    _atomic_json(
        path,
        {
            "stage": stage,
            "completed": completed,
            "total": total,
            "fraction": completed / total if total else 1.0,
            "elapsed_seconds": elapsed,
            "estimated_remaining_seconds": remaining,
        },
    )


def _role_rows(rows: Sequence[Mapping[str, Any]], role: str) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if str(row["role"]) == role]


def _fit_centroids(tokens: np.ndarray, parent: Mapping[str, Any]) -> np.ndarray:
    from sklearn.cluster import MiniBatchKMeans

    spec = parent["representation"]["conditional_multiscale"]
    kmeans = MiniBatchKMeans(
        n_clusters=int(spec["centroids_per_detector_scale"]),
        batch_size=int(spec["minibatch_kmeans_batch_size"]),
        compute_labels=False,
        random_state=int(spec["random_seed"]),
        n_init=str(spec["minibatch_kmeans_n_init"]),
    )
    kmeans.fit(tokens)
    centroids = np.asarray(kmeans.cluster_centers_, dtype=np.float32)
    norms = np.linalg.norm(centroids, axis=1, keepdims=True)
    if np.any(norms <= 0) or np.any(~np.isfinite(norms)):
        raise ContractError("multiscale centroids are invalid")
    return np.ascontiguousarray(centroids / norms)


def _score_tokens(tokens: Any, centroids: Any, top_k: int) -> list[float]:
    import torch

    with torch.inference_mode():
        anomaly = 1.0 - torch.matmul(tokens, centroids.T).max(dim=2).values
        scores = torch.topk(anomaly, k=top_k, dim=1).values.mean(dim=1)
    result = scores.detach().cpu().numpy().astype(np.float64)
    if np.any(~np.isfinite(result)):
        raise ContractError("multiscale scoring returned non-finite values")
    return [float(value) for value in result]


def preflight_reference(
    *,
    cohort_run_dir: Path,
    raw_root: Path,
    device: str = "cuda",
    root: Path = ROOT,
) -> dict[str, Any]:
    import torch

    from src.core.encoder import build_dinov2_transform
    from src.core.model_loader import load_dinov2_model

    reference = load_reference_contract(root)
    parent = load_contract(root)
    verify_cohort(run_dir=cohort_run_dir, root=root)
    rows = _read_jsonl(cohort_run_dir / "multiscale_efficiency_v2_cohort.jsonl")
    _verify_rows(rows, parent)
    row = _role_rows(rows, "short_scale_index")[0]
    _verify_source(
        (
            str((raw_root / row["raw_block"]["source_relative_path"]).resolve()),
            str(row["raw_block"]["source_sha256"]),
        )
    )
    torch_device = torch.device(device)
    model = load_dinov2_model(torch_device, allow_download=False)
    transform = build_dinov2_transform(
        int(parent["representation"]["encoder_input_size"])
    )
    images, replay = _preprocess_row((row, str(raw_root.resolve()), parent))
    tokens = _encode_images(
        images, model=model, transform=transform, device=torch_device
    )
    expected_shape = (
        len(SCALE_LABELS),
        int(parent["representation"]["patch_tokens_per_image"]),
        int(parent["representation"]["embedding_dimension"]),
    )
    if tokens.shape != expected_shape:
        raise ContractError("multiscale preflight token shape changed")
    return {
        "status": "PASS_MULTISCALE_EFFICIENCY_V2_REFERENCE_PREFLIGHT",
        "reference_contract_digest": reference["contract_digest"],
        "cohort_artifact_digest": verify_cohort(run_dir=cohort_run_dir, root=root)[
            "artifact_digest"
        ],
        "runtime": _runtime_identity(device=device, model=model),
        "replay": replay,
        "token_shape": list(tokens.shape),
        "token_sha256": hashlib.sha256(tokens.tobytes()).hexdigest(),
    }


def build_reference(
    *,
    cohort_run_dir: Path,
    raw_root: Path,
    output_root: Path,
    device: str = "cuda",
    workers: int = 8,
    encoder_batch: int = 8,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    """Build and verify all v2 short-scale indices and thresholds."""

    import torch

    from src.core.encoder import build_dinov2_transform
    from src.core.model_loader import load_dinov2_model

    root = root.resolve()
    reference = load_reference_contract(root)
    parent = load_contract(root)
    cohort_summary = verify_cohort(run_dir=cohort_run_dir, root=root)
    if cohort_summary["artifact_digest"] != reference["cohort"]["artifact_digest"]:
        raise ContractError("reference build cohort artifact changed")
    rows = _read_jsonl(cohort_run_dir / cohort_summary["ledger"]["filename"])
    _verify_rows(rows, parent)
    consumed = _role_rows(rows, "short_scale_index") + _role_rows(
        rows, "short_scale_calibration"
    )
    torch_device = torch.device(device)
    model = load_dinov2_model(torch_device, allow_download=False)
    runtime = _runtime_identity(device=device, model=model)
    run_key = _reference_run_key(
        reference_contract_digest=reference["contract_digest"],
        cohort_artifact_digest=cohort_summary["artifact_digest"],
        runtime_environment_digest=runtime["environment_digest"],
    )
    run_dir = output_root.resolve() / f"reference_{run_key}"
    if run_dir.exists():
        return verify_reference(run_dir=run_dir, root=root), run_dir
    run_dir.mkdir(parents=True, exist_ok=False)
    progress_path = run_dir / "progress.json"
    failure_path = run_dir / "failure.json"
    token_paths: list[Path] = []
    started = time.monotonic()
    patch_count = int(parent["representation"]["patch_tokens_per_image"])
    embedding_dimension = int(parent["representation"]["embedding_dimension"])
    try:
        source_rows = verify_raw_sources(consumed, raw_root=raw_root, workers=workers)
        _atomic_json(
            run_dir / "raw_source_verification.json",
            {
                "status": "PASS_VERIFIED_RAW_SOURCES",
                "source_count": len(source_rows),
                "sources_digest": canonical_json_sha256(source_rows),
                "sources": source_rows,
            },
        )
        transform = build_dinov2_transform(
            int(parent["representation"]["encoder_input_size"])
        )
        index_rows = _role_rows(rows, "short_scale_index")
        calibration_rows = _role_rows(rows, "short_scale_calibration")
        index_replay: list[dict[str, Any]] = []
        index_artifacts: dict[str, dict[str, dict[str, Any]]] = {"H1": {}, "L1": {}}
        context = mp.get_context("spawn")
        completed = 0
        for detector in ("H1", "L1"):
            detector_rows = [row for row in index_rows if row["detector"] == detector]
            token_maps = []
            for label in SCALE_LABELS:
                path = run_dir / f".{detector}_{label}s_tokens.partial.dat"
                token_paths.append(path)
                token_maps.append(
                    np.memmap(
                        path,
                        mode="w+",
                        dtype=np.float32,
                        shape=(
                            len(detector_rows),
                            patch_count,
                            embedding_dimension,
                        ),
                    )
                )
            arguments = [
                (row, str(raw_root.resolve()), parent) for row in detector_rows
            ]
            pending_images: list[np.ndarray] = []
            pending_replay: list[dict[str, Any]] = []
            pending_indices: list[int] = []

            def flush_index_batch(token_maps=token_maps) -> None:
                nonlocal pending_images, pending_replay, pending_indices
                if not pending_images:
                    return
                encoded = _encode_images(
                    pending_images,
                    model=model,
                    transform=transform,
                    device=torch_device,
                ).reshape(
                    len(pending_indices),
                    len(SCALE_LABELS),
                    patch_count,
                    embedding_dimension,
                )
                for batch_index, row_index in enumerate(pending_indices):
                    replay = pending_replay[batch_index]
                    replay["patch_tokens_sha256_by_scale"] = {}
                    for scale_index, label in enumerate(SCALE_LABELS):
                        values = np.ascontiguousarray(encoded[batch_index, scale_index])
                        token_maps[scale_index][row_index] = values
                        replay["patch_tokens_sha256_by_scale"][label] = hashlib.sha256(
                            values.tobytes()
                        ).hexdigest()
                    index_replay.append(replay)
                pending_images = []
                pending_replay = []
                pending_indices = []

            with ProcessPoolExecutor(
                max_workers=workers, mp_context=context
            ) as executor:
                for row_index, (images, replay) in enumerate(
                    executor.map(_preprocess_row, arguments)
                ):
                    pending_images.extend(images)
                    pending_replay.append(replay)
                    pending_indices.append(row_index)
                    if len(pending_indices) >= encoder_batch:
                        flush_index_batch()
                    completed += 1
                    if completed % max(1, encoder_batch) == 0:
                        _update_progress(
                            progress_path,
                            stage=f"index:{detector}",
                            completed=completed,
                            total=len(index_rows) + len(calibration_rows),
                            started=started,
                        )
            flush_index_batch()
            for token_map in token_maps:
                token_map.flush()
            for scale_index, label in enumerate(SCALE_LABELS):
                flat = token_maps[scale_index].reshape(-1, embedding_dimension)
                centroids = _fit_centroids(flat, parent)
                index_path = run_dir / f"{detector}_short_scale_{label}s_index.npz"
                _atomic_npz(
                    index_path,
                    embeddings=centroids,
                    labels=np.asarray([f"BG_{detector}_{label}s"] * len(centroids)),
                )
                index_artifacts[detector][label] = {
                    "filename": index_path.name,
                    "sha256": sha256_file(index_path),
                    "centroid_shape": list(centroids.shape),
                    "maximum_l2_norm_error": float(
                        np.max(np.abs(np.linalg.norm(centroids, axis=1) - 1.0))
                    ),
                    "token_count": int(flat.shape[0]),
                }
            del flat, centroids
            for token_map in token_maps:
                token_map._mmap.close()
            del token_maps, token_map
            for path in token_paths:
                if path.name.startswith(f".{detector}_") and path.exists():
                    path.unlink()

        index_replay.sort(key=lambda row: (row["detector"], row["role_index"]))
        index_replay_path = run_dir / "short_scale_index_replay.jsonl"
        _atomic_jsonl(index_replay_path, index_replay)

        centroids_by_detector: dict[str, list[Any]] = {"H1": [], "L1": []}
        for detector in ("H1", "L1"):
            for label in SCALE_LABELS:
                path = run_dir / index_artifacts[detector][label]["filename"]
                with np.load(path, allow_pickle=False) as payload:
                    values = np.asarray(payload["embeddings"], dtype=np.float32)
                centroids_by_detector[detector].append(
                    torch.tensor(values, dtype=torch.float32, device=torch_device)
                )

        calibration_replay: list[dict[str, Any]] = []
        for detector in ("H1", "L1"):
            detector_rows = [
                row for row in calibration_rows if row["detector"] == detector
            ]
            arguments = [
                (row, str(raw_root.resolve()), parent) for row in detector_rows
            ]
            pending_images = []
            pending_replay = []

            def flush_calibration_batch(detector=detector) -> None:
                nonlocal pending_images, pending_replay
                if not pending_images:
                    return
                encoded = _encode_images(
                    pending_images,
                    model=model,
                    transform=transform,
                    device=torch_device,
                )
                encoded_tensor = torch.tensor(encoded, device=torch_device).reshape(
                    len(pending_replay),
                    len(SCALE_LABELS),
                    patch_count,
                    embedding_dimension,
                )
                scores_by_scale: dict[str, list[float]] = {}
                for scale_index, label in enumerate(SCALE_LABELS):
                    scores_by_scale[label] = _score_tokens(
                        encoded_tensor[:, scale_index],
                        centroids_by_detector[detector][scale_index],
                        int(
                            parent["representation"]["conditional_multiscale"]["top_k"]
                        ),
                    )
                for batch_index, replay in enumerate(pending_replay):
                    replay["score_by_scale"] = {
                        label: scores_by_scale[label][batch_index]
                        for label in SCALE_LABELS
                    }
                    calibration_replay.append(replay)
                pending_images = []
                pending_replay = []

            with ProcessPoolExecutor(
                max_workers=workers, mp_context=context
            ) as executor:
                for images, replay in executor.map(_preprocess_row, arguments):
                    pending_images.extend(images)
                    pending_replay.append(replay)
                    if len(pending_replay) >= encoder_batch:
                        flush_calibration_batch()
                    completed += 1
                    if completed % max(1, encoder_batch) == 0:
                        _update_progress(
                            progress_path,
                            stage=f"calibration:{detector}",
                            completed=completed,
                            total=len(index_rows) + len(calibration_rows),
                            started=started,
                        )
            flush_calibration_batch()

        calibration_replay.sort(key=lambda row: (row["detector"], row["role_index"]))
        calibration_path = run_dir / "short_scale_calibration_scores.jsonl"
        _atomic_jsonl(calibration_path, calibration_replay)
        uncertainty = parent["uncertainty"]
        thresholds: dict[str, dict[str, Any]] = {"H1": {}, "L1": {}}
        for detector in ("H1", "L1"):
            detector_scores = [
                row for row in calibration_replay if row["detector"] == detector
            ]
            labels = [str(row["raw_source_sha256"]) for row in detector_scores]
            for scale_index, label in enumerate(SCALE_LABELS):
                thresholds[detector][label] = raw_block_bootstrap_p99(
                    [row["score_by_scale"][label] for row in detector_scores],
                    labels,
                    n_resamples=int(uncertainty["n_resamples"]),
                    seed=int(uncertainty["seed"]) + scale_index,
                    confidence=float(uncertainty["confidence"]),
                    percentile=float(uncertainty["percentile"]),
                )

        threshold_path = run_dir / "short_scale_thresholds.json"
        threshold_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_MULTISCALE_EFFICIENCY_V2_THRESHOLDS",
            "reference_contract_digest": reference["contract_digest"],
            "cohort_artifact_digest": cohort_summary["artifact_digest"],
            "thresholds": thresholds,
        }
        _atomic_json(
            threshold_path,
            {
                **threshold_body,
                "artifact_digest": canonical_json_sha256(threshold_body),
            },
        )
        summary_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_MULTISCALE_EFFICIENCY_V2_REFERENCE",
            "run_key": run_key,
            "reference_contract_digest": reference["contract_digest"],
            "parent_contract_digest": parent["contract_digest"],
            "cohort_artifact_digest": cohort_summary["artifact_digest"],
            "runtime": runtime,
            "raw_source_verification_sha256": sha256_file(
                run_dir / "raw_source_verification.json"
            ),
            "indices": index_artifacts,
            "index_replay": {
                "filename": index_replay_path.name,
                "row_total": len(index_replay),
                "sha256": sha256_file(index_replay_path),
            },
            "calibration": {
                "filename": calibration_path.name,
                "row_total": len(calibration_replay),
                "sha256": sha256_file(calibration_path),
            },
            "thresholds": {
                "filename": threshold_path.name,
                "sha256": sha256_file(threshold_path),
            },
            "scientific_boundary": {
                "legacy_artifacts_consumed": False,
                "detectors_pooled": False,
                "scales_pooled": False,
                "bootstrap_unit": "raw_source_block",
            },
        }
        summary = {
            **summary_body,
            "artifact_digest": canonical_json_sha256(summary_body),
        }
        _atomic_json(run_dir / "reference_summary.json", summary)
        _update_progress(
            progress_path,
            stage="complete",
            completed=len(index_rows) + len(calibration_rows),
            total=len(index_rows) + len(calibration_rows),
            started=started,
        )
        return verify_reference(run_dir=run_dir, root=root), run_dir
    except BaseException as exc:
        _atomic_json(
            failure_path,
            {
                "status": "FAILED_MULTISCALE_EFFICIENCY_V2_REFERENCE",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "run_key": run_key,
            },
        )
        raise
    finally:
        for path in token_paths:
            if path.exists():
                path.unlink()


def verify_reference(*, run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    reference = load_reference_contract(root.resolve())
    parent = load_contract(root.resolve())
    summary_path = run_dir / "reference_summary.json"
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("multiscale reference failure artifact is present")
    if not summary_path.is_file():
        raise ContractError("multiscale reference summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("multiscale reference artifact digest mismatch")
    expected_run_key = _reference_run_key(
        reference_contract_digest=reference["contract_digest"],
        cohort_artifact_digest=reference["cohort"]["artifact_digest"],
        runtime_environment_digest=str(
            summary.get("runtime", {}).get("environment_digest", "")
        ),
    )
    if (
        summary.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_REFERENCE"
        or summary.get("reference_contract_digest") != reference["contract_digest"]
        or summary.get("parent_contract_digest") != parent["contract_digest"]
        or summary.get("cohort_artifact_digest")
        != reference["cohort"]["artifact_digest"]
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"reference_{expected_run_key}"
    ):
        raise ContractError("multiscale reference identity changed")
    raw_verification_path = run_dir / "raw_source_verification.json"
    if not raw_verification_path.is_file() or sha256_file(
        raw_verification_path
    ) != summary.get("raw_source_verification_sha256"):
        raise ContractError("multiscale raw-source verification hash mismatch")
    gates = reference["gates"]
    for detector in ("H1", "L1"):
        for label in SCALE_LABELS:
            entry = summary["indices"][detector][label]
            path = run_dir / entry["filename"]
            if not path.is_file() or sha256_file(path) != entry["sha256"]:
                raise ContractError("multiscale index hash mismatch")
            with np.load(path, allow_pickle=False) as payload:
                embeddings = np.asarray(payload["embeddings"])
            expected_shape = (
                int(gates["centroids_per_detector_scale"]),
                int(parent["representation"]["embedding_dimension"]),
            )
            if embeddings.shape != expected_shape or np.any(~np.isfinite(embeddings)):
                raise ContractError("multiscale index shape or finiteness mismatch")
    index_path = run_dir / summary["index_replay"]["filename"]
    calibration_path = run_dir / summary["calibration"]["filename"]
    threshold_path = run_dir / summary["thresholds"]["filename"]
    for path, entry in (
        (index_path, summary["index_replay"]),
        (calibration_path, summary["calibration"]),
        (threshold_path, summary["thresholds"]),
    ):
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ContractError("multiscale reference child artifact mismatch")
    index_rows = _read_jsonl(index_path)
    calibration_rows = _read_jsonl(calibration_path)
    detectors = tuple(parent["population"]["detectors"])
    expected_index = int(gates["index_rows_per_detector"])
    expected_calibration = int(gates["calibration_rows_per_detector"])
    if (
        len(index_rows) != len(detectors) * expected_index
        or len(calibration_rows) != len(detectors) * expected_calibration
    ):
        raise ContractError("multiscale reference replay cardinality mismatch")
    for detector in detectors:
        if sum(row["detector"] == detector for row in index_rows) != expected_index:
            raise ContractError("multiscale index detector cardinality mismatch")
        if (
            sum(row["detector"] == detector for row in calibration_rows)
            != expected_calibration
        ):
            raise ContractError("multiscale calibration detector cardinality mismatch")
    thresholds = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold_body = dict(thresholds)
    threshold_digest = threshold_body.pop("artifact_digest", None)
    if threshold_digest != canonical_json_sha256(threshold_body):
        raise ContractError("multiscale threshold artifact digest mismatch")
    if (
        thresholds.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_THRESHOLDS"
        or thresholds.get("reference_contract_digest") != reference["contract_digest"]
        or thresholds.get("cohort_artifact_digest")
        != reference["cohort"]["artifact_digest"]
    ):
        raise ContractError("multiscale threshold identity changed")
    for detector in ("H1", "L1"):
        for label in SCALE_LABELS:
            entry = thresholds["thresholds"][detector][label]
            values = [entry["point_p99"], entry["ci_lower"], entry["ci_upper"]]
            if (
                int(entry["score_count"]) != int(gates["scores_per_detector_scale"])
                or entry["method"] != "detector_raw_source_block_bootstrap_p99"
                or float(entry["percentile"])
                != float(parent["uncertainty"]["percentile"])
                or any(not math.isfinite(float(value)) for value in values)
                or float(entry["ci_lower"]) > float(entry["ci_upper"])
            ):
                raise ContractError("multiscale threshold gate failed")
    return summary


__all__ = [
    "REFERENCE_CONTRACT_REL",
    "SCALE_LABELS",
    "build_reference",
    "load_reference_contract",
    "preflight_reference",
    "raw_block_bootstrap_p99",
    "validate_reference_contract",
    "verify_raw_sources",
    "verify_reference",
]
