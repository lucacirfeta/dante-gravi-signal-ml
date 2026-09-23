"""Fail-closed O3a-only native score replay over frozen detector/GPS identities."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_calibration_cohort import (
    _atomic_json,
    _atomic_jsonl,
    load_cohort_contract,
    verify_native_calibration_cohort,
)
from src.dante_light.o3a_native_contract import ROOT, load_runtime_contract
from src.dante_light.o3a_native_index import load_index_contract
from src.dante_light.o3a_native_rescore_preflight import preflight_from_verified_parents
from src.dante_light.o3a_primary_scan import (
    FrameGroupReader,
    InfrastructureError,
    _download_frame,
    load_scan_contract,
)
from src.dante_light.o3a_raw_download import file_sha256, validate_hdf5_metadata


SCHEMA_VERSION = 2
CONTRACT_REL = "config/dante_o3a_native_rescore_v2.json"
SCAN_REL = "artifacts/dante_light/o3a_native_v1/primary_scan.json"
INDEX_REL = "artifacts/dante_light/o3a_native_v1/native_index.json"
CALIBRATION_REL = "artifacts/dante_light/o3a_native_v1/native_calibration_cohort.json"
METHOD_REL = "config/dante_o4a_corrected_native_rescore_v2.json"
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")
SOURCE_PATHS = (
    "src/dante_light/o3a_native_rescore.py",
    "src/dante_light/o3a_native_rescore_preflight.py",
    "src/dante_light/o3a_native_cohort.py",
    "src/dante_light/o3a_native_calibration_cohort.py",
    "src/dante_light/o3a_primary_scan.py",
    "src/dante_light/o3a_raw_acquisition.py",
    "src/dante_light/o3a_raw_download.py",
    "src/core/preprocessor.py",
    "src/core/artifact_manifest.py",
    "src/core/patch_scorer.py",
    "src/core/encoder.py",
    "src/core/model_loader.py",
    "config.yaml",
    "scripts/run_dante_o3a_native_rescore.py",
    "tests/test_dante_o3a_native_rescore.py",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _binding(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    return {"path": relative, "sha256": file_sha256(root / relative), **extra}


def _validated_compact(root: Path, relative: str, expected_status: str) -> dict[str, Any]:
    value = _read_json(root / relative)
    body = dict(value)
    if "compact_digest" in body:
        digest = body.pop("compact_digest")
    else:
        digest = body.pop("artifact_digest", None)
    if value.get("status") != expected_status or digest != canonical_json_sha256(body):
        raise ContractError(f"O3a native-rescore compact parent is invalid: {relative}")
    return value


def build_rescore_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Build an immutable method contract without opening raw strain."""
    root = root.resolve()
    scan_contract = load_scan_contract(root=root)
    index_contract = load_index_contract(root=root)
    calibration_contract = load_cohort_contract(root=root)
    runtime = load_runtime_contract(root=root)
    scan = _validated_compact(root, SCAN_REL, "PASS_COMPLETE_O3A_PRIMARY_SCAN")
    index = _validated_compact(root, INDEX_REL, "PASS_BUILT_O3A_NATIVE_INDEX")
    calibration = _validated_compact(
        root, CALIBRATION_REL, "PASS_FROZEN_O3A_NATIVE_CALIBRATION_COHORT"
    )
    method = _read_json(root / METHOD_REL)
    method_body = dict(method)
    method_digest = method_body.pop("contract_digest", None)
    if method_digest != canonical_json_sha256(method_body):
        raise ContractError("O4a native-rescore method contract changed")
    prep = method["preprocessing"]
    representation = index_contract["representation"]
    configured_preprocessing = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))["preprocessing"]
    if (
        scan_contract["representation"]["sample_rate_hz"] != prep["sample_rate_hz"]
        or scan_contract["representation"]["analysis_duration_s"] != prep["analysis_duration_s"]
        or scan_contract["representation"]["whitening_pad_s"] != prep["whitening_pad_s"]
        or scan_contract["representation"]["top_k"] != method["scoring"]["top_k"]
        or representation["qrange"] != prep["qrange"]
        or representation["frequency_range_hz"] != prep["frequency_range_hz"]
        or representation["colormap"] != prep["colormap"]
        or representation["image_shape"] != prep["image_shape"]
        or scan_contract["representation"]["bandpass_hz"] != [configured_preprocessing["f_low"], configured_preprocessing["f_high"]]
        or calibration["parent_index_artifact_digest"] != index["artifact_digest"]
    ):
        raise ContractError("O3a native-rescore representation or parent parity changed")
    execution = method["execution"]
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_NATIVE_RESCORE_V2",
        "run": "O3A",
        "parents": {
            "primary_scan": _binding(root, SCAN_REL, artifact_digest=scan["artifact_digest"]),
            "native_index": _binding(root, INDEX_REL, artifact_digest=index["artifact_digest"], centroid_count=index["index"]["centroid_shape"][0]),
            "native_calibration": _binding(root, CALIBRATION_REL, artifact_digest=calibration["artifact_digest"], ledger_sha256=calibration["ledger_sha256"]),
            "scan_contract": _binding(root, "config/dante_o3a_primary_scan_v1.json", contract_digest=scan_contract["contract_digest"]),
            "index_contract": _binding(root, "config/dante_o3a_native_index_v1.json", contract_digest=index_contract["contract_digest"]),
            "calibration_contract": _binding(root, "config/dante_o3a_native_calibration_cohort_v1.json", contract_digest=calibration_contract["contract_digest"]),
            "canonical_runtime": _binding(root, "config/dante_o3a_native_v1_runtime.json", environment_digest=runtime["runtime_environment"]["environment_digest"]),
            "corrected_o4a_scoring_method": _binding(root, METHOD_REL, contract_digest=method_digest),
        },
        "preprocessing": dict(prep),
        "representation": dict(representation),
        "scoring": dict(method["scoring"]),
        "execution": {
            "device": method["scoring"]["device"],
            "workers": execution["workers"],
            "batch_size": execution["batch_size"],
            "process_start_method": scan_contract["execution"]["process_start_method"],
            "download_retries": scan_contract["execution"]["download_retries"],
            "raw_cache_limit_bytes": 8 * 1024**3,
            "free_space_reserve_bytes": 16 * 1024**3,
            "resume_unit": "VERIFIED_SCORE_BATCH_SHARD",
        },
        "population": {
            "calibration_rows_by_detector": calibration["counts_by_detector"],
            "bootstrap_block_length_rows": calibration_contract["selection"]["block_length_rows"],
            "candidate_rows_by_detector": scan["candidate_counts"],
            "exact_total_rows": sum(calibration["counts_by_detector"].values()) + scan["candidate_total"],
            "selection": "ALL_FROZEN_PRIMARY_SEEDS_AND_NATIVE_CALIBRATION_IDENTITIES",
        },
        "scientific_boundary": {
            "old_o4a_scores_or_thresholds_read": False,
            "native_threshold_or_class_computed": False,
            "progress_discloses_native_outcomes": False,
            "all_source_and_image_hashes_replayed": True,
            "v1_metadata_only_transport_fix": True,
        },
        "implementation_sources": {relative: file_sha256(root / relative) for relative in SOURCE_PATHS},
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def load_rescore_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = _read_json(root / CONTRACT_REL)
    if value != build_rescore_contract(root=root):
        raise ContractError("O3a native-rescore contract or source bytes changed")
    return value


def write_rescore_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_rescore_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def _parent_runs(
    *, root: Path, external_root: Path, contract: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path, Path]:
    # This verifier independently re-verifies the scan, index and cohort.
    calibration, calibration_dir = verify_native_calibration_cohort(
        root=root, external_root=external_root
    )
    scan = _read_json(root / SCAN_REL)
    index = _read_json(root / INDEX_REL)
    if any(
        value["artifact_digest"] != contract["parents"][name]["artifact_digest"]
        for name, value in (("primary_scan", scan), ("native_index", index), ("native_calibration", calibration))
    ):
        raise ContractError("O3a native-rescore verified parent digest changed")
    scan_dir = external_root / f"primary_scan_{scan['run_key']}"
    index_dir = external_root / f"native_index_{index['run_key']}"
    return scan, index, calibration, scan_dir, index_dir, calibration_dir


def _run_key(contract: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {"stage": "o3a_native_score_only_replay", "contract_digest": contract["contract_digest"]}
    )


def _run_dir(contract: Mapping[str, Any], external_root: Path) -> Path:
    return external_root.resolve() / f"native_rescore_{_run_key(contract)}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def preflight_rescore(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    external_root = external_root.resolve()
    contract = load_rescore_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    if runtime["runtime_environment"]["environment_digest"] != contract["parents"]["canonical_runtime"]["environment_digest"]:
        raise ContractError("O3a native-rescore runtime changed")
    scan, index, calibration, scan_dir, _index_dir, calibration_dir = _parent_runs(
        root=root, external_root=external_root, contract=contract
    )
    work, audit = preflight_from_verified_parents(
        scan_database=scan_dir / scan["database"]["filename"],
        calibration_ledger=calibration_dir / calibration["ledger"]["filename"],
        root=root,
        expected_calibration_rows_by_detector=contract["population"]["calibration_rows_by_detector"],
        bootstrap_block_length_rows=int(contract["population"]["bootstrap_block_length_rows"]),
    )
    if (
        audit["calibration_rows_by_detector"] != contract["population"]["calibration_rows_by_detector"]
        or audit["candidate_rows_by_detector"] != contract["population"]["candidate_rows_by_detector"]
        or audit["row_total"] != contract["population"]["exact_total_rows"]
        or index["artifact_digest"] != contract["parents"]["native_index"]["artifact_digest"]
    ):
        raise ContractError("O3a native-rescore work population changed")
    run_dir = _run_dir(contract, external_root)
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a native-rescore failure artifact requires review")
    manifest_path = run_dir / "work_manifest.jsonl"
    ordered = sorted(work, key=lambda row: (row["detector"], row["gps_start"], row["population"]))
    _atomic_jsonl(manifest_path, ordered)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_O3A_NATIVE_RESCORE_PREFLIGHT",
        "run_key": _run_key(contract),
        "contract_digest": contract["contract_digest"],
        "parent_artifact_digests": {
            "primary_scan": scan["artifact_digest"],
            "native_index": index["artifact_digest"],
            "native_calibration": calibration["artifact_digest"],
        },
        "manifest": {
            "filename": manifest_path.name,
            "sha256": file_sha256(manifest_path),
            "row_digest": canonical_json_sha256(ordered),
            "row_total": len(ordered),
        },
        "audit": audit,
    }
    result = {**body, "preflight_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "preflight.json", result)
    return result, run_dir


def _load_preflight(run_dir: Path, contract: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    preflight = _read_json(run_dir / "preflight.json")
    body = dict(preflight)
    digest = body.pop("preflight_digest", None)
    manifest = run_dir / str(preflight["manifest"]["filename"])
    rows = _read_jsonl(manifest)
    if (
        digest != canonical_json_sha256(body)
        or preflight.get("status") != "PASS_O3A_NATIVE_RESCORE_PREFLIGHT"
        or preflight.get("contract_digest") != contract["contract_digest"]
        or preflight.get("run_key") != _run_key(contract)
        or file_sha256(manifest) != preflight["manifest"]["sha256"]
        or canonical_json_sha256(rows) != preflight["manifest"]["row_digest"]
        or len(rows) != contract["population"]["exact_total_rows"]
    ):
        raise ContractError("O3a native-rescore preflight or manifest changed")
    return preflight, rows


def _prepare_score_row(task: tuple[dict[str, Any], str, dict[str, Any]]) -> tuple[np.ndarray, dict[str, Any]]:
    import matplotlib.pyplot as plt
    from gwpy.timeseries import TimeSeries

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    row, cache_root_text, contract = task
    detector = str(row["detector"])
    gps = int(row["gps_start"])
    prep = contract["preprocessing"]
    representation = contract["representation"]
    pad = int(prep["whitening_pad_s"])
    duration = int(prep["analysis_duration_s"])
    sample_rate = int(prep["sample_rate_hz"])
    cache_root = Path(cache_root_text).resolve()
    sources = row["context_sources"]
    if canonical_json_sha256(sources) != row["context_sources_digest"]:
        raise ContractError("O3a native-rescore source ledger digest changed")
    paths: dict[str, Path] = {}
    for source in sources:
        name = str(source["filename"])
        if Path(name).name != name or source["detector"] != detector:
            raise ContractError("O3a native-rescore source path is invalid")
        path = (cache_root / detector / name).resolve()
        if path.parent != (cache_root / detector).resolve():
            raise ContractError("O3a native-rescore source escapes cache")
        paths[name] = path
    with FrameGroupReader(sources, paths) as reader:
        raw_values = reader.read(gps - pad, gps + duration + pad)
    if (
        raw_values.shape != ((duration + 2 * pad) * sample_rate,)
        or not np.isfinite(raw_values).all()
    ):
        raise ContractError("O3a native-rescore raw context is invalid")
    series = TimeSeries(
        raw_values,
        t0=gps - pad,
        sample_rate=sample_rate,
        name=f"{detector}:GWOSC-4KHZ_R1_STRAIN",
    )
    whitened, info = whiten_context(series, gps, gps + duration, pad=pad)
    tolerance = 1.0 / sample_rate
    if (
        float(info["effective_left"]) < pad - tolerance
        or float(info["effective_right"]) < pad - tolerance
    ):
        raise ContractError("O3a native-rescore whitening context is incomplete")
    clean = extract_clean_subwindow(whitened, gps, gps + duration)
    clean_values = np.ascontiguousarray(clean.value, dtype=np.float64)
    if clean_values.shape != (duration * sample_rate,) or not np.isfinite(clean_values).all():
        raise ContractError("O3a native-rescore clean window is invalid")
    spectrum = generate_qtransform(
        clean,
        qrange=tuple(representation["qrange"]),
        frange=tuple(representation["frequency_range_hz"]),
        output_size=tuple(representation["image_shape"][:2]),
        save_path=None,
        cmap=str(representation["colormap"]),
    )
    image = np.ascontiguousarray(
        (plt.get_cmap(str(representation["colormap"]))(spectrum)[:, :, :3] * 255)
        .astype(np.uint8)
    )
    image_digest = hashlib.sha256(image.tobytes()).hexdigest()
    if (
        list(image.shape) != representation["image_shape"]
        or image_digest != row["expected_image_sha256"]
    ):
        raise ContractError("O3a native-rescore primary-scan image hash changed")
    replay = {
        **row,
        "raw_context_sha256": hashlib.sha256(raw_values.tobytes()).hexdigest(),
        "clean_window_sha256": hashlib.sha256(clean_values.tobytes()).hexdigest(),
        "clean_window_shape": list(clean_values.shape),
        "clean_window_dtype": str(clean_values.dtype),
        "image_sha256": image_digest,
    }
    return image, replay


def _scorer_manifest(path: Path, index_path: Path, index_digest: str, contract: Mapping[str, Any]) -> None:
    _atomic_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "artifact_root": str(index_path.parent),
            "reference_indices": {
                "o3a_native_detector_aware_v1": {
                    "path": index_path.name,
                    "sha256": index_digest,
                    "embedding_dim": contract["representation"]["embedding_dimension"],
                    "n_centroids": contract["parents"]["native_index"]["centroid_count"],
                    "qrange": contract["representation"]["qrange"],
                    "role": "O3a-only detector-aware native score replay",
                }
            },
        },
    )


def _float32_hex(score: float) -> str:
    value = np.asarray([score], dtype=np.float32)
    if not np.isfinite(value).all():
        raise ContractError("O3a native-rescore score is non-finite")
    return value.tobytes().hex()


def _replace_progress(path: Path, *, completed: int, total: int, status: str) -> None:
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "completed_rows": completed,
        "total_rows": total,
        "outcomes_disclosed": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _batch_rows(rows: Sequence[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    return [list(rows[start : start + batch_size]) for start in range(0, len(rows), batch_size)]


def _shard_path(run_dir: Path, batch_index: int) -> Path:
    return run_dir / "score_shards" / f"batch_{batch_index:05d}.json"


def _read_shard(
    *, run_dir: Path, batch_index: int, expected: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> list[dict[str, Any]] | None:
    path = _shard_path(run_dir, batch_index)
    if not path.exists():
        return None
    shard = _read_json(path)
    body = dict(shard)
    digest = body.pop("shard_digest", None)
    rows = shard.get("rows")
    if (
        digest != canonical_json_sha256(body)
        or shard.get("status") != "PASS_O3A_NATIVE_SCORE_SHARD"
        or shard.get("run_key") != _run_key(contract)
        or shard.get("contract_digest") != contract["contract_digest"]
        or shard.get("batch_index") != batch_index
        or shard.get("input_rows_digest") != canonical_json_sha256(list(expected))
        or not isinstance(rows, list)
        or len(rows) != len(expected)
    ):
        raise ContractError(f"O3a native-rescore shard changed: {path}")
    for source, actual in zip(expected, rows, strict=True):
        if (
            not isinstance(actual, dict)
            or any(actual.get(key) != value for key, value in source.items())
            or actual.get("image_sha256") != source["expected_image_sha256"]
            or not isinstance(actual.get("native_score"), (int, float))
            or not np.isfinite(float(actual["native_score"]))
            or actual.get("score_float32_hex") != _float32_hex(float(actual["native_score"]))
            or "class" in actual
            or "threshold" in actual
        ):
            raise ContractError(f"O3a native-rescore scored row changed: {path}")
    return rows


def _write_shard(
    *, run_dir: Path, batch_index: int, inputs: Sequence[Mapping[str, Any]],
    outputs: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> None:
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_O3A_NATIVE_SCORE_SHARD",
        "run_key": _run_key(contract),
        "contract_digest": contract["contract_digest"],
        "batch_index": batch_index,
        "input_rows_digest": canonical_json_sha256(list(inputs)),
        "rows": list(outputs),
    }
    _atomic_json(_shard_path(run_dir, batch_index), {**body, "shard_digest": canonical_json_sha256(body)})


def _frame_key(source: Mapping[str, Any]) -> tuple[str, str]:
    detector = str(source["detector"])
    filename = str(source["filename"])
    if detector not in {"H1", "L1"} or Path(filename).name != filename:
        raise ContractError("O3a native-rescore frame identity is invalid")
    return detector, filename


def _frame_dependency_order(
    batches: Sequence[Sequence[Mapping[str, Any]]]
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], dict[str, Any]]]:
    last_use: dict[tuple[str, str], int] = {}
    sources: dict[tuple[str, str], dict[str, Any]] = {}
    for batch_index, batch in enumerate(batches):
        for row in batch:
            for source in row["context_sources"]:
                key = _frame_key(source)
                identity = dict(source)
                identity.pop("used_interval_gps", None)
                if key in sources and sources[key] != identity:
                    raise ContractError("O3a native-rescore frame identity differs across rows")
                sources[key] = identity
                last_use[key] = batch_index
    return last_use, sources


def _verified_cache_file(
    *, path: Path, source: Mapping[str, Any]
) -> tuple[int, int]:
    if file_sha256(path) != source["sha256"] or path.stat().st_size != source["size_bytes"]:
        raise ContractError("O3a native-rescore cached raw frame hash changed")
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _download_scoring_frame(
    *, source: Mapping[str, Any], target: Path, retries: int
) -> dict[str, Any]:
    """Supply inventory metadata and recover only a fully verified partial."""
    duration = int(source["gps_end"]) - int(source["gps_start"])
    if duration <= 0:
        raise ContractError("O3a native-rescore frame duration is invalid")
    frame = {**source, "duration_s": duration}
    partial = target.with_suffix(target.suffix + ".part")
    if not target.exists() and partial.is_file():
        partial_size = partial.stat().st_size
        expected_size = int(source["size_bytes"])
        if partial_size > expected_size:
            raise ContractError("O3a native-rescore partial frame exceeds ledger size")
        if partial_size == expected_size:
            validate_hdf5_metadata(partial, frame)
            if file_sha256(partial) != source["sha256"]:
                raise ContractError("O3a native-rescore complete partial frame hash changed")
            os.replace(partial, target)
    return _download_frame(
        frame=frame,
        target=target,
        retries=retries,
        expected_sha256=str(source["sha256"]),
    )


def _prepare_batch_sources(
    *, batch: Sequence[Mapping[str, Any]], run_dir: Path, contract: Mapping[str, Any],
    known: dict[tuple[str, str], tuple[int, int]],
) -> None:
    cache_root = run_dir / "transient_raw"
    frame_rows = {
        _frame_key(source): source
        for row in batch for source in row["context_sources"]
    }
    reserve = int(contract["execution"]["free_space_reserve_bytes"])
    for key, source in sorted(frame_rows.items()):
        target = cache_root / key[0] / key[1]
        if key in known:
            if not target.is_file():
                raise ContractError("O3a native-rescore verified cache file disappeared")
            stat = target.stat()
            if (stat.st_size, stat.st_mtime_ns) != known[key]:
                raise ContractError("O3a native-rescore verified cache file changed")
            continue
        if shutil.disk_usage(run_dir).free < int(source["size_bytes"]) + reserve:
            raise InfrastructureError("O3a native-rescore transient raw reserve is insufficient")
        result = _download_scoring_frame(
            source=source,
            target=target,
            retries=int(contract["execution"]["download_retries"]),
        )
        if result["sha256"] != source["sha256"] or result["size_bytes"] != source["size_bytes"]:
            raise ContractError("O3a native-rescore raw frame ledger mismatch")
        known[key] = _verified_cache_file(path=target, source=source)
    if sum(path.stat().st_size for path in cache_root.rglob("*.hdf5")) > int(contract["execution"]["raw_cache_limit_bytes"]):
        raise ContractError("O3a native-rescore transient raw cache exceeds contract")


def _evict_finished_frames(
    *, run_dir: Path, batch_index: int, last_use: Mapping[tuple[str, str], int],
    sources: Mapping[tuple[str, str], Mapping[str, Any]],
    known: dict[tuple[str, str], tuple[int, int]],
) -> None:
    for key in sorted(key for key, final in last_use.items() if final <= batch_index):
        target = run_dir / "transient_raw" / key[0] / key[1]
        if not target.is_file():
            known.pop(key, None)
            continue
        _verified_cache_file(path=target, source=sources[key])
        target.unlink()
        known.pop(key, None)


def _load_scorer(*, run_dir: Path, index_dir: Path, index: Mapping[str, Any], contract: Mapping[str, Any]):
    from src.core.patch_scorer import PatchScorer

    index_path = index_dir / str(index["index"]["filename"])
    digest = str(index["index"]["sha256"])
    if file_sha256(index_path) != digest:
        raise ContractError("O3a native-rescore native index hash changed")
    manifest = run_dir / "scorer_artifact_manifest.json"
    _scorer_manifest(manifest, index_path, digest, contract)
    return PatchScorer(
        index_path,
        device=str(contract["scoring"]["device"]),
        k=int(contract["scoring"]["top_k"]),
        expected_sha256=digest,
        artifact_manifest_path=manifest,
        k_ablations=[],
        n_background=0,
    )


def _score_prepared(prepared: Sequence[tuple[np.ndarray, dict[str, Any]]], *, scorer: Any, contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    import torch

    images = [image for image, _row in prepared]
    tokens = scorer.encode_patch_tokens(images)
    if (
        tokens.ndim != 3
        or tokens.shape[0] != len(images)
        or tokens.shape[1] != contract["representation"]["patch_tokens_per_image"]
        or tokens.shape[2] != contract["representation"]["embedding_dimension"]
        or not bool(torch.isfinite(tokens).all())
    ):
        raise ContractError("O3a native-rescore patch tokens are invalid")
    scored = scorer.score_patch_tokens(
        tokens,
        float(contract["scoring"]["temporary_threshold"]),
        output_mode=str(contract["scoring"]["output_mode"]),
    )
    if len(scored) != len(prepared):
        raise ContractError("O3a native-rescore scorer batch is incomplete")
    output: list[dict[str, Any]] = []
    for (_image, replay), result in zip(prepared, scored, strict=True):
        score = float(result["novelty_score"])
        if not np.isfinite(score):
            raise ContractError("O3a native-rescore score is non-finite")
        output.append({**replay, "native_score": score, "score_float32_hex": _float32_hex(score)})
    return output


def cuda_preflight_rescore(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    """Replay one frozen background row through actual HDF5 and CUDA without publishing a score."""
    preflight, run_dir = preflight_rescore(root=root, external_root=external_root)
    contract = load_rescore_contract(root=root)
    path = run_dir / "cuda_preflight.json"
    if path.exists():
        value = _read_json(path)
        _cuda_preflight_is_valid(run_dir, preflight, contract)
        return value, run_dir
    _stored, rows = _load_preflight(run_dir, contract)
    row = next((item for item in rows if item["population"] == "native_calibration"), None)
    stitched = next(
        (item for item in rows if item["population"] == "native_calibration" and len(item["context_sources"]) > 1),
        None,
    )
    if row is None or stitched is None:
        raise ContractError("O3a native-rescore CUDA preflight lacks ordinary or stitched calibration context")
    index = _read_json(root / INDEX_REL)
    index_dir = external_root.resolve() / f"native_index_{index['run_key']}"
    known: dict[tuple[str, str], tuple[int, int]] = {}
    samples = [row, stitched] if row != stitched else [row]
    _prepare_batch_sources(batch=samples, run_dir=run_dir, contract=contract, known=known)
    prepared = [
        _prepare_score_row((item, str(run_dir / "transient_raw"), contract))
        for item in samples
    ]
    scorer = _load_scorer(run_dir=run_dir, index_dir=index_dir, index=index, contract=contract)
    result = _score_prepared(prepared, scorer=scorer, contract=contract)
    if len(result) != len(samples) or any(
        actual["image_sha256"] != expected["expected_image_sha256"]
        for actual, expected in zip(result, samples, strict=True)
    ):
        raise ContractError("O3a native-rescore CUDA preflight failed")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_O3A_NATIVE_RESCORE_CUDA_PREFLIGHT",
        "run_key": _run_key(contract),
        "contract_digest": contract["contract_digest"],
        "work_manifest_sha256": preflight["manifest"]["sha256"],
        "raw_frame_sha256_replay": True,
        "image_sha256_replay": True,
        "stitched_context_replay": True,
        "finite_cuda_tokens_and_score": True,
        "score_disclosed": False,
    }
    value = {**body, "cuda_preflight_digest": canonical_json_sha256(body)}
    _atomic_json(path, value)
    return value, run_dir


def _cuda_preflight_is_valid(run_dir: Path, preflight: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    path = run_dir / "cuda_preflight.json"
    if not path.is_file():
        return False
    value = _read_json(path)
    body = dict(value)
    digest = body.pop("cuda_preflight_digest", None)
    if (
        digest != canonical_json_sha256(body)
        or value.get("status") != "PASS_O3A_NATIVE_RESCORE_CUDA_PREFLIGHT"
        or value.get("run_key") != _run_key(contract)
        or value.get("contract_digest") != contract["contract_digest"]
        or value.get("work_manifest_sha256") != preflight["manifest"]["sha256"]
        or value.get("raw_frame_sha256_replay") is not True
        or value.get("image_sha256_replay") is not True
        or value.get("stitched_context_replay") is not True
        or value.get("finite_cuda_tokens_and_score") is not True
        or value.get("score_disclosed") is not False
    ):
        raise ContractError("O3a native-rescore CUDA preflight evidence changed")
    return True


def _validate_cache_inventory(
    *, run_dir: Path, sources: Mapping[tuple[str, str], Mapping[str, Any]],
) -> None:
    cache_root = run_dir / "transient_raw"
    if not cache_root.exists():
        return
    for path in cache_root.rglob("*"):
        if path.is_file() and not path.name.endswith(".part"):
            key = (path.parent.name, path.name)
            if key not in sources or path != cache_root / key[0] / key[1]:
                raise ContractError("O3a native-rescore cache has an unknown raw file")


def _gather_outputs(
    *, run_dir: Path, batches: Sequence[Sequence[Mapping[str, Any]]], contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for batch_index, batch in enumerate(batches):
        shard = _read_shard(run_dir=run_dir, batch_index=batch_index, expected=batch, contract=contract)
        if shard is None:
            raise ContractError("O3a native-rescore score shards are incomplete")
        result.extend(shard)
    if len(result) != contract["population"]["exact_total_rows"]:
        raise ContractError("O3a native-rescore scored row total changed")
    return result


def _output_groups(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "native_calibration_H1": sorted(
            [dict(row) for row in rows if row["population"] == "native_calibration" and row["detector"] == "H1"],
            key=lambda row: row["ordinal"],
        ),
        "native_calibration_L1": sorted(
            [dict(row) for row in rows if row["population"] == "native_calibration" and row["detector"] == "L1"],
            key=lambda row: row["ordinal"],
        ),
        "primary_candidate": sorted(
            [dict(row) for row in rows if row["population"] == "primary_candidate"],
            key=lambda row: row["ordinal"],
        ),
    }


def _finish_rescore(
    *, run_dir: Path, contract: Mapping[str, Any], batches: Sequence[Sequence[Mapping[str, Any]]],
    preflight: Mapping[str, Any]
) -> dict[str, Any]:
    rows = _gather_outputs(run_dir=run_dir, batches=batches, contract=contract)
    groups = _output_groups(rows)
    outputs: dict[str, Any] = {}
    for name, values in groups.items():
        path = run_dir / f"{name}.jsonl"
        _atomic_jsonl(path, values)
        outputs[name] = {
            "filename": path.name,
            "sha256": file_sha256(path),
            "row_digest": canonical_json_sha256(values),
            "row_total": len(values),
        }
    if (
        outputs["native_calibration_H1"]["row_total"] != contract["population"]["calibration_rows_by_detector"]["H1"]
        or outputs["native_calibration_L1"]["row_total"] != contract["population"]["calibration_rows_by_detector"]["L1"]
        or outputs["primary_candidate"]["row_total"] != sum(contract["population"]["candidate_rows_by_detector"].values())
    ):
        raise ContractError("O3a native-rescore output populations changed")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_O3A_NATIVE_RESCORE",
        "run_key": _run_key(contract),
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "row_total": len(rows),
        "outputs": outputs,
        "gates": {
            "source_frame_hash_mismatches": 0,
            "context_failures": 0,
            "image_hash_mismatches": 0,
            "encoder_failures": 0,
            "nonfinite_scores": 0,
            "old_o4a_scores_or_thresholds_read": False,
            "threshold_or_class_computed": False,
        },
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "native_rescore_summary.json", summary)
    return summary


def _run_native_rescore_locked(
    *, root: Path, external_root: Path, contract: Mapping[str, Any], run_dir: Path
) -> tuple[dict[str, Any], Path]:
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a native-rescore failure requires explicit infrastructure review")
    if (run_dir / "native_rescore_summary.json").exists():
        return verify_native_rescore(root=root, external_root=external_root)
    preflight, run_dir = preflight_rescore(root=root, external_root=external_root)
    if not _cuda_preflight_is_valid(run_dir, preflight, contract):
        cuda_preflight_rescore(root=root, external_root=external_root)
    _stored, rows = _load_preflight(run_dir, contract)
    batches = _batch_rows(rows, int(contract["execution"]["batch_size"]))
    last_use, sources = _frame_dependency_order(batches)
    _validate_cache_inventory(run_dir=run_dir, sources=sources)
    index = _read_json(root / INDEX_REL)
    index_dir = external_root / f"native_index_{index['run_key']}"
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": _run_key(contract),
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
    }
    _atomic_json(run_dir / "run_identity.json", identity)
    completed = sum(
        len(shard)
        for batch_index, batch in enumerate(batches)
        if (shard := _read_shard(run_dir=run_dir, batch_index=batch_index, expected=batch, contract=contract)) is not None
    )
    _replace_progress(run_dir / "progress.json", completed=completed, total=len(rows), status="SCORING")
    known: dict[tuple[str, str], tuple[int, int]] = {}
    try:
        scorer = _load_scorer(run_dir=run_dir, index_dir=index_dir, index=index, contract=contract)
        context = mp.get_context(str(contract["execution"]["process_start_method"]))
        with ProcessPoolExecutor(max_workers=int(contract["execution"]["workers"]), mp_context=context) as executor:
            for batch_index, batch in enumerate(batches):
                if _read_shard(run_dir=run_dir, batch_index=batch_index, expected=batch, contract=contract) is not None:
                    _evict_finished_frames(run_dir=run_dir, batch_index=batch_index, last_use=last_use, sources=sources, known=known)
                    continue
                _prepare_batch_sources(batch=batch, run_dir=run_dir, contract=contract, known=known)
                prepared = list(executor.map(
                    _prepare_score_row,
                    [(row, str(run_dir / "transient_raw"), dict(contract)) for row in batch],
                ))
                output = _score_prepared(prepared, scorer=scorer, contract=contract)
                _write_shard(run_dir=run_dir, batch_index=batch_index, inputs=batch, outputs=output, contract=contract)
                completed += len(batch)
                _replace_progress(run_dir / "progress.json", completed=completed, total=len(rows), status="SCORING")
                _evict_finished_frames(run_dir=run_dir, batch_index=batch_index, last_use=last_use, sources=sources, known=known)
        if completed != len(rows):
            raise ContractError("O3a native-rescore completed-row count changed")
        cache_root = run_dir / "transient_raw"
        if cache_root.exists() and any(path.is_file() for path in cache_root.rglob("*")):
            raise ContractError("O3a native-rescore transient raw cache is not empty")
        _replace_progress(run_dir / "progress.json", completed=completed, total=len(rows), status="VERIFYING")
        _finish_rescore(run_dir=run_dir, contract=contract, batches=batches, preflight=preflight)
        summary, path = verify_native_rescore(root=root, external_root=external_root)
        _replace_progress(run_dir / "progress.json", completed=completed, total=len(rows), status="PASS_VERIFIED")
        return summary, path
    except BaseException as exc:
        failure_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_O3A_NATIVE_RESCORE",
            "run_key": _run_key(contract),
            "contract_digest": contract["contract_digest"],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        _atomic_json(run_dir / "failure.json", {**failure_body, "artifact_digest": canonical_json_sha256(failure_body)})
        raise


def run_native_rescore(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    import fcntl

    root = root.resolve()
    external_root = external_root.resolve()
    contract = load_rescore_contract(root=root)
    run_dir = _run_dir(contract, external_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "run.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError("another O3a native-rescore process owns this run key") from exc
        try:
            return _run_native_rescore_locked(
                root=root, external_root=external_root, contract=contract, run_dir=run_dir
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def verify_native_rescore(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    external_root = external_root.resolve()
    contract = load_rescore_contract(root=root)
    run_dir = _run_dir(contract, external_root)
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a native-rescore failure artifact is present")
    preflight, run_dir = preflight_rescore(root=root, external_root=external_root)
    if not _cuda_preflight_is_valid(run_dir, preflight, contract):
        raise ContractError("O3a native-rescore CUDA preflight is missing")
    _stored, work = _load_preflight(run_dir, contract)
    batches = _batch_rows(work, int(contract["execution"]["batch_size"]))
    scored = _gather_outputs(run_dir=run_dir, batches=batches, contract=contract)
    groups = _output_groups(scored)
    summary_path = run_dir / "native_rescore_summary.json"
    summary = _read_json(summary_path)
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if (
        digest != canonical_json_sha256(body)
        or summary.get("status") != "PASS_COMPLETE_O3A_NATIVE_RESCORE"
        or summary.get("run_key") != _run_key(contract)
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("preflight_digest") != preflight["preflight_digest"]
        or summary.get("row_total") != len(scored)
        or summary.get("gates")
        != {
            "source_frame_hash_mismatches": 0,
            "context_failures": 0,
            "image_hash_mismatches": 0,
            "encoder_failures": 0,
            "nonfinite_scores": 0,
            "old_o4a_scores_or_thresholds_read": False,
            "threshold_or_class_computed": False,
        }
    ):
        raise ContractError("O3a native-rescore summary changed")
    for name, expected in groups.items():
        output = summary["outputs"].get(name)
        if not isinstance(output, dict):
            raise ContractError("O3a native-rescore output summary is incomplete")
        path = run_dir / str(output["filename"])
        if (
            path.name != f"{name}.jsonl"
            or not path.is_file()
            or file_sha256(path) != output["sha256"]
            or _read_jsonl(path) != expected
            or output["row_total"] != len(expected)
            or output["row_digest"] != canonical_json_sha256(expected)
        ):
            raise ContractError("O3a native-rescore output ledger changed")
    cache_root = run_dir / "transient_raw"
    if cache_root.exists() and any(path.is_file() for path in cache_root.rglob("*")):
        raise ContractError("O3a native-rescore transient raw cache is not empty")
    return summary, run_dir


def clear_infrastructure_failure(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> Path:
    """Archive only a verified transport/disk failure before same-key resume."""
    root = root.resolve()
    contract = load_rescore_contract(root=root)
    run_dir = _run_dir(contract, external_root)
    path = run_dir / "failure.json"
    failure = _read_json(path)
    body = dict(failure)
    digest = body.pop("artifact_digest", None)
    if (
        digest != canonical_json_sha256(body)
        or failure.get("status") != "FAILED_O3A_NATIVE_RESCORE"
        or failure.get("run_key") != _run_key(contract)
        or failure.get("error_type") not in {"InfrastructureError", "OSError", "ConnectionError", "TimeoutError"}
    ):
        raise ContractError("O3a native-rescore failure is not an infrastructure-only failure")
    preflight, rows = _load_preflight(run_dir, contract)
    if not _cuda_preflight_is_valid(run_dir, preflight, contract):
        raise ContractError("O3a native-rescore CUDA preflight changed before resume")
    batches = _batch_rows(rows, int(contract["execution"]["batch_size"]))
    for index, batch in enumerate(batches):
        _read_shard(run_dir=run_dir, batch_index=index, expected=batch, contract=contract)
    archive = run_dir / "failure_history" / f"failure_{digest}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise ContractError("O3a native-rescore infrastructure failure was already archived")
    os.replace(path, archive)
    if _read_json(archive) != failure:
        raise ContractError("O3a native-rescore infrastructure failure archive changed")
    return archive


def write_compact_rescore_artifact(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> dict[str, Any]:
    summary, run_dir = verify_native_rescore(root=root, external_root=external_root)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_VERIFIED_O3A_NATIVE_RESCORE",
        "run": "O3A",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "artifact_digest": summary["artifact_digest"],
        "row_total": summary["row_total"],
        "output_sha256": {name: value["sha256"] for name, value in summary["outputs"].items()},
        "native_threshold_or_class_computed": False,
        "external_run_dir_wsl": str(run_dir),
    }
    compact = {**body, "compact_digest": canonical_json_sha256(body)}
    _atomic_json(root / "artifacts/dante_light/o3a_native_v1/native_rescore.json", compact)
    return compact
