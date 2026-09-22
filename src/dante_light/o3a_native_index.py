"""Build an O3a-only native index from the verified detector-aware cohort.

The 40 s raw contexts are retained by the cohort stage.  This stage replays
their exact bytes, whitening, clean-window hashes, Q transform, and DINOv2
tokens before fitting the approved historical MiniBatchKMeans architecture.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_cohort import (
    DEFAULT_EXTERNAL_ROOT as COHORT_EXTERNAL_ROOT,
    O4A_REFERENCE_REL,
    _atomic_json,
    _atomic_jsonl,
    _read_json,
    _read_jsonl,
    verify_native_cohort,
)
from src.dante_light.o3a_native_contract import ROOT, RUNTIME_REL, load_runtime_contract
from src.dante_light.o3a_scale_adequacy import STAGE_CONTRACT_REL, load_stage_contract
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_light.o4a_corrected_native_index import (
    _encode_images,
    cluster_native_tokens,
)


SCHEMA_VERSION = 1
CONTRACT_REL = "config/dante_o3a_native_index_v1.json"
COMPACT_COHORT_REL = "artifacts/dante_light/o3a_native_v1/native_cohort.json"
COMPACT_INDEX_REL = "artifacts/dante_light/o3a_native_v1/native_index.json"
IMPLEMENTATION_REL = "src/dante_light/o3a_native_index.py"
FREEZE_ENTRYPOINT_REL = "scripts/freeze_dante_o3a_native_index.py"
RUN_ENTRYPOINT_REL = "scripts/run_dante_o3a_native_index.py"
ENCODER_REL = "src/core/encoder.py"
MODEL_LOADER_REL = "src/core/model_loader.py"
PREPROCESSOR_REL = "src/core/preprocessor.py"
CLUSTER_METHOD_REL = "src/dante_light/o4a_corrected_native_index.py"
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")
DEFAULT_WORKERS = 8
DEFAULT_ENCODER_BATCH_SIZE = 8


def _binding(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    return {"path": relative, "sha256": file_sha256(root / relative), **extra}


def _validated_compact_cohort(root: Path) -> dict[str, Any]:
    value = _read_json(root / COMPACT_COHORT_REL)
    body = dict(value)
    declared = body.pop("artifact_digest", None)
    if (
        declared != canonical_json_sha256(body)
        or value.get("status") != "PASS_FROZEN_O3A_NATIVE_COHORT"
        or value.get("counts_by_detector") != {"H1": 647, "L1": 647}
    ):
        raise ContractError("O3a native-index cohort parent is not PASS")
    return value


def build_index_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    stage = load_stage_contract(root=root)
    runtime = load_runtime_contract(root=root)
    cohort = _validated_compact_cohort(root)
    method = _read_json(root / O4A_REFERENCE_REL)
    method_body = dict(method)
    method_digest = method_body.pop("contract_digest", None)
    if method_digest != canonical_json_sha256(method_body):
        raise ContractError("O4a native method reference digest changed")
    architecture = stage["author_decisions"]["native_index_architecture"]
    historical = method["historical_parity"]
    for field in (
        "centroid_count",
        "random_seed",
        "raw_embedding_sample_size",
        "minibatch_kmeans_batch_size",
        "minibatch_kmeans_n_init",
    ):
        if architecture[field] != historical[field]:
            raise ContractError("O3a native-index architecture parity changed")
    representation = dict(method["preprocessing"]["representation"])
    if architecture["embedding_dimension"] != representation["embedding_dimension"]:
        raise ContractError("O3a native-index representation parity changed")
    cohort_contract = _read_json(root / "config/dante_o3a_native_cohort_v1.json")
    if cohort["contract_digest"] != cohort_contract["contract_digest"]:
        raise ContractError("O3a native-index cohort contract changed")
    source_paths = (
        IMPLEMENTATION_REL,
        FREEZE_ENTRYPOINT_REL,
        RUN_ENTRYPOINT_REL,
        ENCODER_REL,
        MODEL_LOADER_REL,
        PREPROCESSOR_REL,
        CLUSTER_METHOD_REL,
    )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_NATIVE_INDEX_V1",
        "run": "O3A",
        "parents": {
            "approved_stage_contract": _binding(
                root, STAGE_CONTRACT_REL, contract_digest=stage["contract_digest"]
            ),
            "frozen_native_cohort": _binding(
                root,
                COMPACT_COHORT_REL,
                artifact_digest=cohort["artifact_digest"],
                ledger_sha256=cohort["ledger"]["sha256"],
            ),
            "frozen_native_cohort_contract": _binding(
                root,
                "config/dante_o3a_native_cohort_v1.json",
                contract_digest=cohort["contract_digest"],
            ),
            "canonical_runtime": _binding(
                root,
                RUNTIME_REL,
                environment_digest=runtime["runtime_environment"][
                    "environment_digest"
                ],
            ),
            "corrected_o4a_method": _binding(
                root, O4A_REFERENCE_REL, contract_digest=method_digest
            ),
        },
        "preprocessing": {
            "analysis_duration_s": int(method["preprocessing"]["analysis_duration_s"]),
            "whitening_pad_s": int(method["preprocessing"]["whitening_pad_s"]),
            "sample_rate_hz": int(method["preprocessing"]["sample_rate_hz"]),
            "raw_context_hash_replay": True,
            "clean_window_hash_replay": True,
            "excess_power_disposition_replay": True,
        },
        "representation": representation,
        "clustering": {
            "centroid_count": int(architecture["centroid_count"]),
            "random_seed": int(architecture["random_seed"]),
            "raw_embedding_sample_size": int(
                architecture["raw_embedding_sample_size"]
            ),
            "minibatch_kmeans_batch_size": int(
                architecture["minibatch_kmeans_batch_size"]
            ),
            "minibatch_kmeans_n_init": architecture["minibatch_kmeans_n_init"],
            "compute_labels": bool(architecture["compute_labels"]),
            "centroid_l2_normalization": bool(
                architecture["centroid_l2_normalization"]
            ),
            "raw_sample_l2_normalization": bool(
                architecture["raw_embedding_sample_l2_normalization"]
            ),
        },
        "execution": {
            "device": "cuda",
            "workers": DEFAULT_WORKERS,
            "encoder_batch_size": DEFAULT_ENCODER_BATCH_SIZE,
            "resume_unit": "VERIFIED_PATCH_TOKEN_SHARD",
            "token_order": "FROZEN_COHORT_LEDGER_ORDER",
            "cross_environment_reuse_allowed": False,
        },
        "storage": {
            "cohort_root_wsl": str(COHORT_EXTERNAL_ROOT),
            "index_root_wsl": str(DEFAULT_EXTERNAL_ROOT),
            "temporary_token_matrix": "WSL_TMP_MEMMAP",
            "full_raw_frame_archive_required": False,
        },
        "gates": {
            "exact_cohort_counts_by_detector": dict(cohort["counts_by_detector"]),
            "exact_cohort_rows": int(cohort["row_total"]),
            "exact_patch_token_total": int(cohort["row_total"])
            * int(representation["patch_tokens_per_image"]),
            "exact_centroid_shape": [
                int(architecture["centroid_count"]),
                int(representation["embedding_dimension"]),
            ],
            "exact_raw_sample_shape": [
                int(architecture["raw_embedding_sample_size"]),
                int(representation["embedding_dimension"]),
            ],
            "maximum_l2_norm_error": 2e-6,
            "zero_hash_context_or_encoder_failures": True,
            "fail_closed": True,
        },
        "implementation_sources": {
            relative: file_sha256(root / relative) for relative in source_paths
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def load_index_contract(*, root: Path = ROOT) -> dict[str, Any]:
    path = root.resolve() / CONTRACT_REL
    actual = _read_json(path)
    if actual != build_index_contract(root=root):
        raise ContractError("O3a native-index frozen contract changed")
    return actual


def _run_key(contract: Mapping[str, Any], runtime: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "stage": "o3a_detector_aware_native_index",
            "contract_digest": contract["contract_digest"],
            "cohort_artifact_digest": contract["parents"]["frozen_native_cohort"][
                "artifact_digest"
            ],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
        }
    )


def _cohort_rows(cohort_dir: Path, cohort: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _read_jsonl(cohort_dir / str(cohort["ledger"]["filename"]))
    if len(rows) != int(cohort["row_total"]):
        raise ContractError("O3a native-index cohort ledger is incomplete")
    return rows


def _preprocess_context(
    task: tuple[dict[str, Any], str, dict[str, Any]]
) -> tuple[np.ndarray, dict[str, Any]]:
    import matplotlib.pyplot as plt
    from gwpy.timeseries import TimeSeries

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )
    from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto

    row, cohort_dir_value, contract = task
    if row.get("quality_disposition") != "PASS_CLEAN":
        raise ContractError("O3a native-index cohort row is not clean")
    if canonical_json_sha256(row["context_sources"]) != row["context_sources_digest"]:
        raise ContractError("O3a native-index source-frame ledger changed")
    cohort_dir = Path(cohort_dir_value).resolve()
    raw = row["raw_context"]
    relative = Path(str(raw["relative_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError("O3a native-index context path escapes cohort")
    path = (cohort_dir / relative).resolve()
    if cohort_dir not in path.parents or file_sha256(path) != raw["file_sha256"]:
        raise ContractError("O3a native-index raw context file hash mismatch")
    values = np.load(path, allow_pickle=False)
    prep = contract["preprocessing"]
    representation = contract["representation"]
    gps = int(row["gps_start"])
    pad = int(prep["whitening_pad_s"])
    duration = int(prep["analysis_duration_s"])
    rate = int(prep["sample_rate_hz"])
    if (
        values.shape != tuple(raw["shape"])
        or values.shape != ((duration + 2 * pad) * rate,)
        or str(values.dtype) != raw["dtype"]
        or not np.isfinite(values).all()
        or hashlib.sha256(values.tobytes()).hexdigest() != raw["values_sha256"]
        or raw["context_interval_gps"] != [gps - pad, gps + duration + pad]
    ):
        raise ContractError("O3a native-index raw context values changed")
    series = TimeSeries(
        values,
        t0=gps - pad,
        sample_rate=rate,
        name=f"{row['detector']}:GWOSC-4KHZ_R1_STRAIN",
    )
    whitened, info = whiten_context(series, gps, gps + duration, pad=pad)
    tolerance = 1.0 / rate
    if (
        float(info["effective_left"]) < pad - tolerance
        or float(info["effective_right"]) < pad - tolerance
    ):
        raise ContractError("O3a native-index whitening context changed")
    clean = extract_clean_subwindow(whitened, gps, gps + duration)
    clean_values = np.ascontiguousarray(clean.value, dtype=np.float64)
    clean_sha = hashlib.sha256(clean_values.tobytes()).hexdigest()
    if (
        clean_sha != row["clean_window_sha256"]
        or list(clean_values.shape) != row["clean_window_shape"]
        or str(clean_values.dtype) != row["clean_window_dtype"]
        or not np.isfinite(clean_values).all()
        or excess_power_veto(clean, sample_rate=rate)
    ):
        raise ContractError("O3a native-index clean-window replay changed")
    spectrogram = generate_qtransform(
        clean,
        qrange=tuple(representation["qrange"]),
        frange=tuple(representation["frequency_range_hz"]),
        output_size=tuple(representation["image_shape"][:2]),
        save_path=None,
        cmap=str(representation["colormap"]),
    )
    image = np.ascontiguousarray(
        (plt.get_cmap(str(representation["colormap"]))(spectrogram)[:, :, :3] * 255)
        .astype(np.uint8)
    )
    if list(image.shape) != representation["image_shape"]:
        raise ContractError("O3a native-index image shape changed")
    replay = {
        "detector": str(row["detector"]),
        "gps_start": gps,
        "identity_digest": str(row["identity_digest"]),
        "cohort_detector_index": int(row["cohort_detector_index"]),
        "raw_context_values_sha256": str(raw["values_sha256"]),
        "clean_window_sha256": clean_sha,
        "context_sources_digest": str(row["context_sources_digest"]),
        "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
    }
    return image, replay


def preflight_native_index(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_index_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    cohort, cohort_dir = verify_native_cohort(root=root)
    if cohort["artifact_digest"] != contract["parents"]["frozen_native_cohort"][
        "artifact_digest"
    ]:
        raise ContractError("O3a native-index cohort parent changed")
    import sklearn
    import torch

    if sklearn.__version__ != runtime["runtime_environment"]["packages"][
        "scikit-learn"
    ]:
        raise ContractError("O3a native-index sklearn runtime changed")
    if not torch.cuda.is_available():
        raise ContractError("O3a native-index CUDA runtime is unavailable")
    rows = _cohort_rows(cohort_dir, cohort)
    from src.core.encoder import build_dinov2_transform
    from src.core.model_loader import load_dinov2_model

    device = torch.device(str(contract["execution"]["device"]))
    model = load_dinov2_model(device)
    model.eval()
    image, _replay = _preprocess_context((rows[0], str(cohort_dir), contract))
    tokens = _encode_images(
        [image],
        model=model,
        transform=build_dinov2_transform(
            output_size=int(contract["representation"]["encoder_input_size"])
        ),
        device=device,
    )
    expected = (
        1,
        int(contract["representation"]["patch_tokens_per_image"]),
        int(contract["representation"]["embedding_dimension"]),
    )
    if tokens.shape != expected:
        raise ContractError("O3a native-index real CUDA preflight shape changed")
    run_key = _run_key(contract, runtime)
    run_dir = external_root.resolve() / f"native_index_{run_key}"
    token_bytes = (
        int(contract["gates"]["exact_patch_token_total"])
        * int(contract["representation"]["embedding_dimension"])
        * np.dtype(np.float32).itemsize
    )
    reserve = 2 * 1024**3
    if (
        shutil.disk_usage(external_root).free < token_bytes + reserve
        or shutil.disk_usage(tempfile.gettempdir()).free < token_bytes + reserve
    ):
        raise ContractError("O3a native-index storage preflight failed")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_O3A_NATIVE_INDEX_PREFLIGHT",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "cohort_artifact_digest": cohort["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
        "cohort_rows": len(rows),
        "expected_patch_tokens": int(contract["gates"]["exact_patch_token_total"]),
        "real_context_replay_passed": True,
        "real_cuda_encoder_passed": True,
        "storage_gate_passed": True,
    }
    preflight = {**body, "preflight_digest": canonical_json_sha256(body)}
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "preflight.json"
    if path.exists() and _read_json(path) != preflight:
        raise ContractError("O3a native-index preflight is divergent")
    if not path.exists():
        _atomic_json(path, preflight)
    return preflight, run_dir


def _atomic_npy(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        np.save(stream, values, allow_pickle=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def _shard_paths(run_dir: Path, position: int) -> tuple[Path, Path]:
    basename = f"{position:04d}"
    return run_dir / "tokens" / f"{basename}.npy", run_dir / "tokens" / f"{basename}.json"


def _read_shard(
    *, run_dir: Path, position: int, row: Mapping[str, Any], contract: Mapping[str, Any]
) -> tuple[np.ndarray, dict[str, Any]] | None:
    token_path, manifest_path = _shard_paths(run_dir, position)
    if not token_path.exists() and not manifest_path.exists():
        return None
    if not token_path.is_file() or not manifest_path.is_file():
        raise ContractError("O3a native-index token shard is partial")
    manifest = _read_json(manifest_path)
    body = dict(manifest)
    declared = body.pop("shard_digest", None)
    values = np.load(token_path, allow_pickle=False)
    replay = manifest.get("replay", {})
    expected_shape = (
        int(contract["representation"]["patch_tokens_per_image"]),
        int(contract["representation"]["embedding_dimension"]),
    )
    if (
        declared != canonical_json_sha256(body)
        or manifest.get("position") != position
        or manifest.get("contract_digest") != contract["contract_digest"]
        or manifest.get("identity_digest") != row["identity_digest"]
        or manifest.get("detector") != row["detector"]
        or manifest.get("gps_start") != row["gps_start"]
        or replay.get("identity_digest") != row["identity_digest"]
        or replay.get("clean_window_sha256") != row.get("clean_window_sha256")
        or replay.get("raw_context_values_sha256")
        != row.get("raw_context", {}).get("values_sha256")
        or replay.get("context_sources_digest") != row.get("context_sources_digest")
        or replay.get("detector") != row["detector"]
        or replay.get("gps_start") != row["gps_start"]
        or replay.get("cohort_detector_index")
        != row.get("cohort_detector_index")
        or tuple(values.shape) != expected_shape
        or values.dtype != np.float32
        or not np.isfinite(values).all()
        or file_sha256(token_path) != manifest.get("token_file_sha256")
        or hashlib.sha256(values.tobytes()).hexdigest()
        != manifest.get("patch_tokens_sha256")
    ):
        raise ContractError("O3a native-index token shard changed")
    return values, manifest


def _write_shard(
    *,
    run_dir: Path,
    position: int,
    row: Mapping[str, Any],
    replay: Mapping[str, Any],
    values: np.ndarray,
    contract: Mapping[str, Any],
) -> None:
    token_path, manifest_path = _shard_paths(run_dir, position)
    if token_path.exists() or manifest_path.exists():
        raise ContractError("O3a native-index refuses to overwrite a token shard")
    contiguous = np.ascontiguousarray(values, dtype=np.float32)
    expected_shape = (
        int(contract["representation"]["patch_tokens_per_image"]),
        int(contract["representation"]["embedding_dimension"]),
    )
    if contiguous.shape != expected_shape or not np.isfinite(contiguous).all():
        raise ContractError("O3a native-index encoder output shape changed")
    _atomic_npy(token_path, contiguous)
    body = {
        "schema_version": SCHEMA_VERSION,
        "position": position,
        "contract_digest": contract["contract_digest"],
        "detector": row["detector"],
        "gps_start": row["gps_start"],
        "identity_digest": row["identity_digest"],
        "token_file_sha256": file_sha256(token_path),
        "patch_tokens_sha256": hashlib.sha256(contiguous.tobytes()).hexdigest(),
        "replay": dict(replay),
    }
    _atomic_json(manifest_path, {**body, "shard_digest": canonical_json_sha256(body)})


def _progress(run_dir: Path, *, completed: int, total: int, status: str) -> None:
    _atomic_json(
        run_dir / "progress.json",
        {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "completed_rows": completed,
            "total_rows": total,
        },
    )


def _load_preflight(
    *, run_dir: Path, contract: Mapping[str, Any], run_key: str
) -> dict[str, Any]:
    value = _read_json(run_dir / "preflight.json")
    body = dict(value)
    declared = body.pop("preflight_digest", None)
    if (
        declared != canonical_json_sha256(body)
        or value.get("status") != "PASS_O3A_NATIVE_INDEX_PREFLIGHT"
        or value.get("run_key") != run_key
        or value.get("contract_digest") != contract["contract_digest"]
        or value.get("cohort_artifact_digest")
        != contract["parents"]["frozen_native_cohort"]["artifact_digest"]
    ):
        raise ContractError("O3a native-index preflight changed")
    return value


def _failure_kind(exc: BaseException) -> str:
    if isinstance(exc, (OSError, MemoryError)):
        return "INFRASTRUCTURE"
    return "STRUCTURAL_OR_SCIENTIFIC"


def _expected_run(
    *, root: Path, external_root: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path]:
    contract = load_index_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    cohort, cohort_dir = verify_native_cohort(root=root)
    if cohort["artifact_digest"] != contract["parents"]["frozen_native_cohort"][
        "artifact_digest"
    ]:
        raise ContractError("O3a native-index parent cohort changed")
    run_dir = external_root.resolve() / f"native_index_{_run_key(contract, runtime)}"
    return contract, runtime, cohort, cohort_dir, run_dir


def build_native_index(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    """Replay and encode cohort contexts, then fit the frozen VQ index."""

    import fcntl

    root = root.resolve()
    contract, runtime, cohort, cohort_dir, run_dir = _expected_run(
        root=root, external_root=external_root
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "run.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError("another O3a native-index process owns this run key") from exc
        try:
            return _build_native_index_locked(
                root=root,
                contract=contract,
                runtime=runtime,
                cohort=cohort,
                cohort_dir=cohort_dir,
                run_dir=run_dir,
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _build_native_index_locked(
    *,
    root: Path,
    contract: Mapping[str, Any],
    runtime: Mapping[str, Any],
    cohort: Mapping[str, Any],
    cohort_dir: Path,
    run_dir: Path,
) -> tuple[dict[str, Any], Path]:
    run_key = _run_key(contract, runtime)
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a native-index failure must be archived before resume")
    if (run_dir / "native_index_summary.json").exists():
        return verify_native_index(root=root, external_root=run_dir.parent)
    _load_preflight(run_dir=run_dir, contract=contract, run_key=run_key)
    rows = _cohort_rows(cohort_dir, cohort)
    identity = {
        "schema_version": SCHEMA_VERSION,
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "cohort_artifact_digest": cohort["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.exists() and _read_json(identity_path) != identity:
        raise ContractError("O3a native-index run identity changed")
    if not identity_path.exists():
        _atomic_json(identity_path, identity)
    try:
        from src.core.encoder import build_dinov2_transform
        from src.core.model_loader import load_dinov2_model
        import torch

        device = torch.device(str(contract["execution"]["device"]))
        model = load_dinov2_model(device)
        model.eval()
        for parameter in model.parameters():
            parameter.requires_grad = False
        transform = build_dinov2_transform(
            output_size=int(contract["representation"]["encoder_input_size"])
        )
        batch_size = int(contract["execution"]["encoder_batch_size"])
        context = mp.get_context("spawn")
        completed = sum(
            _read_shard(run_dir=run_dir, position=i, row=row, contract=contract)
            is not None
            for i, row in enumerate(rows)
        )
        _progress(run_dir, completed=completed, total=len(rows), status="ENCODING")
        with ProcessPoolExecutor(
            max_workers=int(contract["execution"]["workers"]), mp_context=context
        ) as executor:
            for start in range(0, len(rows), batch_size):
                missing = [
                    (i, rows[i])
                    for i in range(start, min(start + batch_size, len(rows)))
                    if _read_shard(
                        run_dir=run_dir, position=i, row=rows[i], contract=contract
                    ) is None
                ]
                if not missing:
                    continue
                prepared = list(
                    executor.map(
                        _preprocess_context,
                        [(row, str(cohort_dir), dict(contract)) for _, row in missing],
                    )
                )
                encoded = _encode_images(
                    [image for image, _ in prepared],
                    model=model,
                    transform=transform,
                    device=device,
                )
                if encoded.shape != (
                    len(missing),
                    int(contract["representation"]["patch_tokens_per_image"]),
                    int(contract["representation"]["embedding_dimension"]),
                ):
                    raise ContractError("O3a native-index encoder output shape changed")
                for (position, row), (_, replay), tokens in zip(
                    missing, prepared, encoded, strict=True
                ):
                    _write_shard(
                        run_dir=run_dir,
                        position=position,
                        row=row,
                        replay=replay,
                        values=tokens,
                        contract=contract,
                    )
                completed += len(missing)
                _progress(run_dir, completed=completed, total=len(rows), status="ENCODING")
        if completed != len(rows):
            raise ContractError("O3a native-index token extraction is incomplete")
        _progress(run_dir, completed=completed, total=len(rows), status="CLUSTERING")
        dimension = int(contract["representation"]["embedding_dimension"])
        patch_count = int(contract["representation"]["patch_tokens_per_image"])
        token_total = int(contract["gates"]["exact_patch_token_total"])
        replay_rows: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="dante-o3a-native-index-") as temporary:
            matrix = np.memmap(
                Path(temporary) / "patch_tokens.float32.mmap",
                mode="w+",
                dtype=np.float32,
                shape=(token_total, dimension),
            )
            for position, row in enumerate(rows):
                shard = _read_shard(
                    run_dir=run_dir, position=position, row=row, contract=contract
                )
                if shard is None:
                    raise ContractError("O3a native-index verified shard disappeared")
                values, manifest = shard
                matrix[position * patch_count : (position + 1) * patch_count] = values
                replay_rows.append(
                    {
                        "position": position,
                        **manifest["replay"],
                        "patch_tokens_sha256": manifest["patch_tokens_sha256"],
                    }
                )
            matrix.flush()
            clustering = contract["clustering"]
            centroids, raw_sample = cluster_native_tokens(
                matrix,
                centroid_count=int(clustering["centroid_count"]),
                batch_size=int(clustering["minibatch_kmeans_batch_size"]),
                seed=int(clustering["random_seed"]),
                n_init=str(clustering["minibatch_kmeans_n_init"]),
                raw_sample_size=int(clustering["raw_embedding_sample_size"]),
            )
            del matrix
        replay_path = run_dir / "native_index_replay.jsonl"
        if replay_path.exists():
            if _read_jsonl(replay_path) != replay_rows:
                raise ContractError("O3a native-index replay ledger is divergent")
        else:
            _atomic_jsonl(replay_path, replay_rows)
        index_path = run_dir / "native_index.npz"
        meta = {
            "schema_version": 3,
            "run": "O3a",
            "detectors": ["H1", "L1"],
            "counts_by_detector": dict(cohort["counts_by_detector"]),
            "K": int(clustering["centroid_count"]),
            "seed": int(clustering["random_seed"]),
            "n_segments": len(rows),
            "cohort_artifact_digest": cohort["artifact_digest"],
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
            "preprocessing": "whiten_context_v1_single_bandpass",
            "colormap": contract["representation"]["colormap"],
            "qrange": contract["representation"]["qrange"],
            "qtransform_frange_hz": contract["representation"]["frequency_range_hz"],
            "qtransform_logf": True,
            "qtransform_output_size": list(contract["representation"]["image_shape"][:2]),
            "raw_sample_size": len(raw_sample),
            "raw_sample_total_tokens": token_total,
            "raw_sample_seed": int(clustering["random_seed"]),
            "detector_identity_inferred": False,
        }
        if index_path.exists():
            with np.load(index_path, allow_pickle=False) as existing:
                if (
                    set(existing.files)
                    != {"embeddings", "labels", "raw_embeddings_sample", "meta"}
                    or not np.array_equal(existing["embeddings"], centroids)
                    or not np.array_equal(existing["raw_embeddings_sample"], raw_sample)
                    or set(existing["labels"].tolist()) != {"BG_O3a"}
                    or json.loads(str(existing["meta"].item())) != meta
                ):
                    raise ContractError("O3a native-index prior NPZ is divergent")
        else:
            temporary_index = run_dir / f".{index_path.name}.{os.getpid()}.tmp.npz"
            np.savez_compressed(
                temporary_index,
                embeddings=centroids,
                labels=np.asarray(["BG_O3a"] * len(centroids)),
                raw_embeddings_sample=raw_sample,
                meta=json.dumps(meta, sort_keys=True, allow_nan=False),
            )
            temporary_index.replace(index_path)
        body = {
            **identity,
            "status": "PASS_BUILT_O3A_NATIVE_INDEX",
            "cohort_row_total": len(rows),
            "counts_by_detector": dict(cohort["counts_by_detector"]),
            "index": {
                "filename": index_path.name,
                "sha256": file_sha256(index_path),
                "size_bytes": index_path.stat().st_size,
                "centroid_shape": list(centroids.shape),
                "centroid_bytes_sha256": hashlib.sha256(centroids.tobytes()).hexdigest(),
                "raw_sample_shape": list(raw_sample.shape),
                "raw_sample_bytes_sha256": hashlib.sha256(raw_sample.tobytes()).hexdigest(),
                "token_total": token_total,
            },
            "replay_ledger": {
                "filename": replay_path.name,
                "sha256": file_sha256(replay_path),
                "row_digest": canonical_json_sha256(replay_rows),
                "row_total": len(replay_rows),
            },
            "gates": {
                "cohort_only": True,
                "raw_context_hash_mismatches": 0,
                "clean_window_hash_mismatches": 0,
                "context_failures": 0,
                "encoder_failures": 0,
            },
        }
        summary = {**body, "artifact_digest": canonical_json_sha256(body)}
        _atomic_json(run_dir / "native_index_summary.json", summary)
        verified, verified_dir = verify_native_index(root=root, external_root=run_dir.parent)
        _atomic_json(root / COMPACT_INDEX_REL, verified)
        _progress(run_dir, completed=completed, total=len(rows), status="COMPLETE")
        return verified, verified_dir
    except BaseException as exc:
        failure_body = {
            **identity,
            "status": "FAILED_O3A_NATIVE_INDEX",
            "failure_kind": _failure_kind(exc),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        _atomic_json(
            run_dir / "failure.json",
            {**failure_body, "failure_digest": canonical_json_sha256(failure_body)},
        )
        raise


def verify_native_index(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    """Verify the complete index, replay ledger, and all frozen cardinalities."""

    root = root.resolve()
    contract, runtime, cohort, cohort_dir, run_dir = _expected_run(
        root=root, external_root=external_root
    )
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a native-index failure artifact is present")
    _load_preflight(run_dir=run_dir, contract=contract, run_key=_run_key(contract, runtime))
    summary = _read_json(run_dir / "native_index_summary.json")
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if (
        declared != canonical_json_sha256(body)
        or summary.get("status") != "PASS_BUILT_O3A_NATIVE_INDEX"
        or summary.get("run_key") != _run_key(contract, runtime)
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("cohort_artifact_digest") != cohort["artifact_digest"]
        or summary.get("runtime_environment_digest")
        != runtime["runtime_environment"]["environment_digest"]
        or summary.get("counts_by_detector") != {"H1": 647, "L1": 647}
        or summary.get("cohort_row_total") != int(contract["gates"]["exact_cohort_rows"])
        or summary.get("index", {}).get("token_total")
        != int(contract["gates"]["exact_patch_token_total"])
    ):
        raise ContractError("O3a native-index summary changed")
    index_path = run_dir / str(summary["index"]["filename"])
    replay_path = run_dir / str(summary["replay_ledger"]["filename"])
    if (
        file_sha256(index_path) != summary["index"]["sha256"]
        or index_path.stat().st_size != summary["index"]["size_bytes"]
        or file_sha256(replay_path) != summary["replay_ledger"]["sha256"]
    ):
        raise ContractError("O3a native-index output file hash changed")
    replay_rows = _read_jsonl(replay_path)
    cohort_rows = _cohort_rows(cohort_dir, cohort)
    if (
        len(replay_rows) != len(cohort_rows)
        or canonical_json_sha256(replay_rows)
        != summary["replay_ledger"]["row_digest"]
    ):
        raise ContractError("O3a native-index replay ledger changed")
    for position, (cohort_row, replay) in enumerate(zip(cohort_rows, replay_rows, strict=True)):
        shard = _read_shard(
            run_dir=run_dir, position=position, row=cohort_row, contract=contract
        )
        if shard is None:
            raise ContractError("O3a native-index token shard missing")
        _, manifest = shard
        if replay != {
            "position": position,
            **manifest["replay"],
            "patch_tokens_sha256": manifest["patch_tokens_sha256"],
        }:
            raise ContractError("O3a native-index replay/shard mismatch")
    with np.load(index_path, allow_pickle=False) as data:
        if set(data.files) != {"embeddings", "labels", "raw_embeddings_sample", "meta"}:
            raise ContractError("O3a native-index NPZ schema changed")
        centroids = np.asarray(data["embeddings"])
        labels = np.asarray(data["labels"])
        raw_sample = np.asarray(data["raw_embeddings_sample"])
        meta = json.loads(str(data["meta"].item()))
    if (
        list(centroids.shape) != contract["gates"]["exact_centroid_shape"]
        or list(raw_sample.shape) != contract["gates"]["exact_raw_sample_shape"]
        or centroids.dtype != np.float32
        or raw_sample.dtype != np.float32
        or labels.shape != (len(centroids),)
        or set(labels.tolist()) != {"BG_O3a"}
        or meta.get("run") != "O3a"
        or meta.get("K") != len(centroids)
        or meta.get("cohort_artifact_digest") != cohort["artifact_digest"]
        or meta.get("contract_digest") != contract["contract_digest"]
        or meta.get("detector_identity_inferred") is not False
        or hashlib.sha256(centroids.tobytes()).hexdigest()
        != summary["index"]["centroid_bytes_sha256"]
        or hashlib.sha256(raw_sample.tobytes()).hexdigest()
        != summary["index"]["raw_sample_bytes_sha256"]
    ):
        raise ContractError("O3a native-index NPZ provenance changed")
    maximum_error = float(contract["gates"]["maximum_l2_norm_error"])
    if (
        not np.isfinite(centroids).all()
        or not np.isfinite(raw_sample).all()
        or float(np.max(np.abs(np.linalg.norm(centroids, axis=1) - 1))) > maximum_error
        or float(np.max(np.abs(np.linalg.norm(raw_sample, axis=1) - 1))) > maximum_error
    ):
        raise ContractError("O3a native-index normalization gate failed")
    return summary, run_dir


def write_index_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_index_contract(root=root)
    _atomic_json(root.resolve() / CONTRACT_REL, value)
    return value


def clear_infrastructure_failure(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> Path:
    """Archive a verified infrastructure-only failure before same-key resume."""

    root = root.resolve()
    contract = load_index_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    run_key = _run_key(contract, runtime)
    run_dir = external_root.resolve() / f"native_index_{run_key}"
    failure_path = run_dir / "failure.json"
    failure = _read_json(failure_path)
    body = dict(failure)
    declared = body.pop("failure_digest", None)
    if (
        declared != canonical_json_sha256(body)
        or failure.get("run_key") != run_key
        or failure.get("contract_digest") != contract["contract_digest"]
        or failure.get("failure_kind") != "INFRASTRUCTURE"
    ):
        raise ContractError("O3a native-index failure is not verified infrastructure-only")
    archive = run_dir / "failures" / f"failure_{declared}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise ContractError("O3a native-index failure archive already exists")
    os.replace(failure_path, archive)
    return archive


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "build_index_contract",
    "build_native_index",
    "clear_infrastructure_failure",
    "load_index_contract",
    "preflight_native_index",
    "verify_native_index",
    "write_index_contract",
]
