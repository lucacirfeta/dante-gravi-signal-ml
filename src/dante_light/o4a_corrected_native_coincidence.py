"""Frozen asymmetric physical-coincidence search for corrected O4a candidates."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore import _atomic_json, _atomic_jsonl
from src.dante_light.o4a_corrected_native_rescore_v2 import _load_jsonl
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.prefilter_v5_protocol import sha256_path
from src.pipeline_v2_production.coincidence_physical import (
    _bandpass,
    _max_normxcorr,
    _patch_time_band,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_coincidence_v1.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_coincidence_v1"
)
SCHEMA_VERSION = 1

_WORKER_RAW_ROOT: Path | None = None
_WORKER_RECEIPT: dict[str, dict[str, Any]] = {}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _file_reference(root: Path, reference: Mapping[str, Any]) -> Path:
    path = (root / str(reference["path"])).resolve()
    if not path.is_file() or sha256_path(path) != str(reference["sha256"]):
        raise ContractError(f"corrected native-coincidence reference changed: {path}")
    return path


def validate_native_coincidence_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("corrected native-coincidence contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("corrected native-coincidence schema changed")

    population = value.get("population", {})
    required_population = {
        "primary_seed_class": "ROBUST",
        "diagnostic_seed_class": "AMBIGUOUS",
        "excluded_class": "BACKGROUND",
        "partner_selection": "opposite_detector_same_window_regardless_of_class_or_catalogue_presence",
        "partner_class_read": False,
        "primary_and_diagnostic_threshold_pools_separate": True,
    }
    if any(population.get(key) != expected for key, expected in required_population.items()):
        raise ContractError("corrected native-coincidence population changed")
    expected_counts = {
        "primary": {"H1": 2090, "L1": 3316, "total": 5406},
        "diagnostic": {"H1": 672, "L1": 1672, "total": 2344},
        "excluded": {"H1": 1958, "L1": 1234, "total": 3192},
    }
    if population.get("exact_counts") != expected_counts:
        raise ContractError("corrected native-coincidence exact counts changed")

    measurement = value.get("measurement", {})
    required_measurement = {
        "algorithm": "bandpassed_light_travel_normxcorr_v1",
        "localization": "native_detector_aware_top_k_patch_columns",
        "segment_duration_s": 32.0,
        "sample_rate_hz": 4096,
        "whitening_pad_s": 4.0,
        "light_travel_s": 0.010002,
        "lag_margin_s": 0.002,
        "half_window_s": 0.5,
        "null_shifts_s": [1.0, 2.0, 4.0, 8.0, -1.0, -2.0, -4.0, -8.0],
        "patch_iou_role": "complementary_diagnostic",
        "threshold_source": "primary_seed_per_event_null_maxima_only",
        "threshold_quantile_percent": 99.0,
        "threshold_quantile_method": "linear",
        "decision_rule": "cc_onsource_strictly_greater_than_primary_null_p99",
    }
    if measurement != required_measurement:
        raise ContractError("corrected native-coincidence measurement changed")

    scoring = value.get("scoring", {})
    if scoring != {
        "index": "corrected_detector_aware_native_v1",
        "top_k": 68,
        "image_shape": [256, 256, 3],
        "colormap": "cividis",
        "max_seed_score_delta": 2e-7,
        "device": "cuda",
    }:
        raise ContractError("corrected native-coincidence scoring changed")

    boundary = value.get("scientific_boundary")
    if boundary != {
        "asymmetric_seed_search": True,
        "symmetric_robust_and_required": False,
        "partner_class_or_candidate_required": False,
        "ambiguous_affects_primary_threshold": False,
        "background_processed": False,
        "native_scores_or_classes_changed": False,
        "taxonomy_used_for_coincidence": False,
        "historical_artifacts_immutable": True,
        "efficiency_required_before_null_as_absence_claim": True,
    }:
        raise ContractError("corrected native-coincidence scientific boundary changed")

    references = value.get("references", {})
    for reference in references.values():
        _file_reference(root, reference)

    classification = _read_json(root / references["native_classification"]["path"])
    index = _read_json(root / references["native_index"]["path"])
    primary = _read_json(root / references["primary_scan"]["path"])
    taxonomy = _read_json(root / references["native_taxonomy"]["path"])
    if value.get("parents") != {
        "native_classification_artifact_digest": classification.get("external_artifact_digest"),
        "native_classification_contract_digest": classification.get("contract_digest"),
        "native_classification_row_digest": classification.get("output", {}).get("row_digest"),
        "native_classification_sha256": classification.get("output", {}).get("sha256"),
        "native_index_artifact_digest": index.get("artifact_digest"),
        "native_index_contract_digest": index.get("contract_digest"),
        "native_index_sha256": index.get("index", {}).get("sha256"),
        "primary_scan_artifact_digest": primary.get("artifact_digest"),
        "primary_scan_database_sha256": primary.get("database", {}).get("sha256"),
        "native_taxonomy_artifact_digest": taxonomy.get("external_artifact_digest"),
    }:
        raise ContractError("corrected native-coincidence parents changed")

    gates = value.get("gates", {})
    if gates != {
        "fail_closed": True,
        "exact_seed_detector_gps_identity": True,
        "exact_seed_image_sha256_replay": True,
        "exact_raw_source_sha256": True,
        "exact_symmetric_whitening_context": True,
        "zero_duplicate_seed_detector_gps": True,
        "zero_partner_class_reads": True,
        "zero_background_measurements": True,
        "maximum_seed_score_delta": 2e-7,
        "all_seeds_accounted": True,
        "full_ledger_verification": True,
    }:
        raise ContractError("corrected native-coincidence gates changed")
    if value.get("execution") != {
        "environment": "canonical WSL runtime",
        "workers": 8,
        "batch_size": 32,
        "producer_backend": "process",
        "shared_cuda_scorer": True,
        "raw_source_sha256_workers": 8,
        "atomic_outputs_only": True,
        "resume_partial_output": False,
    }:
        raise ContractError("corrected native-coincidence execution changed")
    if value.get("output") != {
        "root": "E:/dante_cache/dante_light/o4a_corrected_native_coincidence_v1",
        "summary_filename": "native_coincidence_summary.json",
        "primary_filename": "native_coincidence_robust.jsonl",
        "diagnostic_filename": "native_coincidence_ambiguous.jsonl",
        "raw_receipt_filename": "raw_source_receipt.jsonl",
        "historical_artifacts_overwritten": False,
        "large_outputs_committed_to_git": False,
    }:
        raise ContractError("corrected native-coincidence output contract changed")
    return {"contract_digest": digest, **value}


def load_native_coincidence_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_native_coincidence_contract(_read_json(root / CONTRACT_REL), root=root)


def split_seed_populations(
    rows: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    population = contract["population"]
    expected = population["exact_counts"]
    identities: set[tuple[str, float]] = set()
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    primary: list[dict[str, Any]] = []
    diagnostic: list[dict[str, Any]] = []
    allowed = {
        population["primary_seed_class"],
        population["diagnostic_seed_class"],
        population["excluded_class"],
    }
    for source in rows:
        detector = str(source.get("detector"))
        gps = float(source.get("gps_start", np.nan))
        native_class = str(source.get("native_class"))
        identity = (detector, gps)
        if (
            detector not in {"H1", "L1"}
            or not np.isfinite(gps)
            or native_class not in allowed
            or identity in identities
        ):
            raise ContractError("corrected native-coincidence seed population is invalid")
        identities.add(identity)
        if native_class == population["primary_seed_class"]:
            bucket = "primary"
            primary.append(dict(source))
        elif native_class == population["diagnostic_seed_class"]:
            bucket = "diagnostic"
            diagnostic.append(dict(source))
        else:
            bucket = "excluded"
        counts[bucket][detector] += 1
    for bucket in ("primary", "diagnostic", "excluded"):
        observed = {
            "H1": counts[bucket]["H1"],
            "L1": counts[bucket]["L1"],
            "total": counts[bucket]["H1"] + counts[bucket]["L1"],
        }
        if observed != expected[bucket]:
            raise ContractError(f"corrected native-coincidence {bucket} count changed")
    def order(row: Mapping[str, Any]) -> tuple[float, str]:
        return float(row["gps_start"]), str(row["detector"])

    return sorted(primary, key=order), sorted(diagnostic, key=order)


def _opposite(detector: str) -> str:
    if detector == "H1":
        return "L1"
    if detector == "L1":
        return "H1"
    raise ContractError(f"unsupported detector: {detector}")


def _context_plan(
    manifest: Any, *, detector: str, gps: float, pad_s: float
) -> list[dict[str, Any]]:
    start = gps - pad_s
    end = gps + 32.0 + pad_s
    grouped: dict[tuple[float, float], list[Path]] = defaultdict(list)
    for block_start, block_end, path in manifest.entries:
        if block_end > start and block_start < end:
            grouped[(float(block_start), float(block_end))].append(Path(path).resolve())
    tolerance = 1.0 / 4096.0
    cursor = start
    selected: list[tuple[float, float, Path]] = []
    blocks = [
        (block_start, block_end, sorted(set(paths), key=str)[0])
        for (block_start, block_end), paths in grouped.items()
    ]
    while cursor < end - tolerance:
        candidates = [
            item
            for item in blocks
            if item[0] <= cursor + tolerance and item[1] > cursor + tolerance
        ]
        if not candidates:
            return []
        chosen = sorted(candidates, key=lambda item: (-item[1], item[0], str(item[2])))[0]
        selected.append(chosen)
        cursor = min(end, chosen[1])
    sources = []
    cursor = start
    for block_start, block_end, path in selected:
        used_start = cursor
        used_end = min(end, block_end)
        sources.append(
            {
                "absolute_path": str(path),
                "block_interval": [block_start, block_end],
                "used_interval": [used_start, used_end],
                "sha256": str(manifest.expected_sha256[path]),
            }
        )
        cursor = used_end
    return sources


def _verify_source(record: Mapping[str, Any]) -> dict[str, Any]:
    path = Path(str(record["absolute_path"]))
    before = path.stat()
    actual = sha256_file(path)
    after = path.stat()
    if (
        actual != str(record["sha256"])
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise ContractError(f"corrected native-coincidence raw source changed: {path}")
    return {
        "absolute_path": str(path.resolve()),
        "sha256": actual,
        "size_bytes": int(after.st_size),
        "mtime_ns": int(after.st_mtime_ns),
    }


def _initialize_worker(raw_root: str, receipt: Sequence[Mapping[str, Any]]) -> None:
    global _WORKER_RAW_ROOT, _WORKER_RECEIPT
    _WORKER_RAW_ROOT = Path(raw_root).resolve()
    _WORKER_RECEIPT = {str(row["absolute_path"]): dict(row) for row in receipt}


def _read_planned_context(
    sources: Sequence[Mapping[str, Any]], *, detector: str, gps: float
):
    import h5py
    from gwpy.timeseries import TimeSeries

    if _WORKER_RAW_ROOT is None:
        raise ContractError("corrected native-coincidence worker is not initialized")
    pieces: list[np.ndarray] = []
    for source in sources:
        path = Path(str(source["absolute_path"])).resolve()
        if _WORKER_RAW_ROOT != path and _WORKER_RAW_ROOT not in path.parents:
            raise ContractError("corrected native-coincidence raw path escaped root")
        receipt = _WORKER_RECEIPT.get(str(path))
        stat = path.stat()
        if (
            receipt is None
            or receipt["sha256"] != source["sha256"]
            or int(receipt["size_bytes"]) != stat.st_size
            or int(receipt["mtime_ns"]) != stat.st_mtime_ns
        ):
            raise ContractError("corrected native-coincidence raw receipt changed")
        block_start, block_end = (float(value) for value in source["block_interval"])
        used_start, used_end = (float(value) for value in source["used_interval"])
        first = int(round((used_start - block_start) * 4096))
        last = int(round((used_end - block_start) * 4096))
        expected_shape = (int(round((block_end - block_start) * 4096)),)
        with h5py.File(path, "r") as handle:
            if "Strain" not in handle or tuple(handle["Strain"].shape) != expected_shape:
                raise ContractError(f"corrected native-coincidence HDF5 shape changed: {path}")
            values = np.asarray(handle["Strain"][first:last])
        if values.shape != (last - first,):
            raise ContractError("corrected native-coincidence HDF5 slice is short")
        pieces.append(values)
    values = np.ascontiguousarray(np.concatenate(pieces))
    if values.shape != (40 * 4096,) or np.any(~np.isfinite(values)):
        raise ContractError("corrected native-coincidence raw context is invalid")
    return TimeSeries(
        values,
        t0=gps - 4.0,
        sample_rate=4096,
        name=f"{detector}:GWOSC-16KHZ_R1_STRAIN",
    ), values


def _prepare_identity(argument: Mapping[str, Any]) -> dict[str, Any]:
    import matplotlib.pyplot as plt
    from src.core.preprocessor import extract_clean_subwindow, generate_qtransform, whiten_context

    detector = str(argument["detector"])
    gps = float(argument["gps_start"])
    sources = list(argument["context_sources"])
    context, raw = _read_planned_context(sources, detector=detector, gps=gps)
    whitened, pad_info = whiten_context(context, gps, gps + 32.0, pad=4.0)
    tolerance = 1.0 / 4096.0
    if (
        float(pad_info["effective_left"]) < 4.0 - tolerance
        or float(pad_info["effective_right"]) < 4.0 - tolerance
    ):
        raise ContractError("corrected native-coincidence whitening context is incomplete")
    clean = extract_clean_subwindow(whitened, gps, gps + 32.0)
    clean_values = np.ascontiguousarray(clean.value)
    if clean_values.shape != (32 * 4096,) or np.any(~np.isfinite(clean_values)):
        raise ContractError("corrected native-coincidence clean window is invalid")
    spectrogram = generate_qtransform(clean, save_path=None, cmap="cividis")
    image = np.ascontiguousarray(
        (plt.get_cmap("cividis")(spectrogram)[:, :, :3] * 255).astype(np.uint8)
    )
    if image.shape != (256, 256, 3):
        raise ContractError("corrected native-coincidence image shape changed")
    image_sha256 = hashlib.sha256(image.tobytes()).hexdigest()
    expected_image = argument.get("expected_image_sha256")
    if expected_image is not None and image_sha256 != str(expected_image):
        raise ContractError("corrected native-coincidence seed image hash mismatch")
    source_rows = [
        {
            "relative_path": str(Path(row["absolute_path"]).resolve().relative_to(_WORKER_RAW_ROOT)),
            "block_interval": list(row["block_interval"]),
            "used_interval": list(row["used_interval"]),
            "sha256": str(row["sha256"]),
        }
        for row in sources
    ]
    return {
        "detector": detector,
        "gps_start": gps,
        "image": image,
        "clean": clean_values,
        "image_sha256": image_sha256,
        "clean_window_sha256": hashlib.sha256(clean_values.tobytes()).hexdigest(),
        "raw_context_sha256": hashlib.sha256(raw.tobytes()).hexdigest(),
        "context_sources": source_rows,
        "context_sources_digest": canonical_json_sha256(source_rows),
    }


def measure_physical_arrays(
    candidate: np.ndarray,
    partner: np.ndarray,
    candidate_top_k: np.ndarray,
    partner_top_k: np.ndarray,
    *,
    measurement: Mapping[str, Any],
) -> dict[str, Any]:
    x_clean = np.asarray(candidate, dtype=np.float64)
    y_clean = np.asarray(partner, dtype=np.float64)
    if x_clean.shape != y_clean.shape or x_clean.shape != (32 * 4096,):
        raise ContractError("corrected native-coincidence clean arrays changed")
    t_offset, f_lo, f_hi = _patch_time_band(np.asarray(candidate_top_k, dtype=np.int64))
    half = float(measurement["half_window_s"])
    fs = float(measurement["sample_rate_hz"])

    def segment(values: np.ndarray, shift: float = 0.0) -> np.ndarray:
        center = t_offset + shift
        lo = max(0.0, center - half)
        hi = min(float(measurement["segment_duration_s"]), center + half)
        return _bandpass(values[int(lo * fs) : int(hi * fs)], fs, f_lo, f_hi)

    x = segment(x_clean)
    y = segment(y_clean)
    max_lag = float(measurement["light_travel_s"]) + float(measurement["lag_margin_s"])
    onsource = _max_normxcorr(x, y, fs, max_lag)
    null_values = []
    for shift in measurement["null_shifts_s"]:
        if 0.0 <= t_offset + shift - half and t_offset + shift + half <= 32.0:
            null_values.append(_max_normxcorr(x, segment(y_clean, float(shift)), fs, max_lag))
    if not null_values or not np.isfinite([onsource, *null_values]).all():
        raise ContractError("corrected native-coincidence statistic is invalid")
    left = set(np.asarray(candidate_top_k, dtype=np.int64).tolist())
    right = set(np.asarray(partner_top_k, dtype=np.int64).tolist())
    return {
        "t_offset_s": float(t_offset),
        "f_lo_hz": float(f_lo),
        "f_hi_hz": float(f_hi),
        "cc_onsource": float(onsource),
        "cc_null_values": [float(value) for value in null_values],
        "cc_null_mean": float(np.mean(null_values)),
        "cc_null_max": float(np.max(null_values)),
        "n_null": len(null_values),
        "patch_iou": len(left & right) / max(1, len(left | right)),
        "per_event_null_exceeded": bool(onsource > float(np.max(null_values))),
    }


def primary_null_threshold(
    events: Sequence[Mapping[str, Any]], *, measurement: Mapping[str, Any]
) -> float:
    values = np.asarray(
        [
            float(row["cc_null_max"])
            for row in events
            if row.get("measurement_status") == "MEASURED"
        ],
        dtype=np.float64,
    )
    if values.size == 0 or not np.isfinite(values).all():
        raise ContractError("corrected native-coincidence primary null is empty")
    return float(
        np.percentile(
            values,
            float(measurement["threshold_quantile_percent"]),
            method=str(measurement["threshold_quantile_method"]),
        )
    )


def _external_paths(
    *,
    root: Path,
    contract: Mapping[str, Any],
    primary_external_root: Path,
    classification_external_root: Path,
    index_external_root: Path,
) -> tuple[Path, Path, Path, Path]:
    classification_artifact = _read_json(
        root / contract["references"]["native_classification"]["path"]
    )
    primary_artifact = _read_json(root / contract["references"]["primary_scan"]["path"])
    index_artifact = _read_json(root / contract["references"]["native_index"]["path"])
    classification_dir = classification_external_root.resolve() / (
        "native_classification_" + classification_artifact["external_run"]["run_key"]
    )
    primary_dir = primary_external_root.resolve() / (
        "primary_scan_" + primary_artifact["run_key"]
    )
    index_dir = index_external_root.resolve() / (
        "native_index_" + index_artifact["run_key"]
    )
    return (
        classification_dir / classification_artifact["output"]["filename"],
        classification_dir / classification_artifact["external_run"]["summary_filename"],
        primary_dir / primary_artifact["database"]["filename"],
        index_dir / index_artifact["external_run"]["index_filename"],
    )


def _verified_inputs(
    *,
    root: Path,
    contract: Mapping[str, Any],
    primary_external_root: Path,
    classification_external_root: Path,
    index_external_root: Path,
) -> tuple[list[dict[str, Any]], Path, dict[tuple[str, float], dict[str, str]], Path]:
    import sqlite3

    classification_path, classification_summary_path, database_path, index_path = (
        _external_paths(
            root=root,
            contract=contract,
            primary_external_root=primary_external_root,
            classification_external_root=classification_external_root,
            index_external_root=index_external_root,
        )
    )
    parents = contract["parents"]
    if (
        not classification_path.is_file()
        or sha256_file(classification_path) != parents["native_classification_sha256"]
        or not classification_summary_path.is_file()
        or not database_path.is_file()
        or sha256_file(database_path) != parents["primary_scan_database_sha256"]
        or not index_path.is_file()
        or sha256_file(index_path) != parents["native_index_sha256"]
    ):
        raise ContractError("corrected native-coincidence parent file changed")
    classification_summary = _read_json(classification_summary_path)
    summary_body = dict(classification_summary)
    summary_digest = summary_body.pop("artifact_digest", None)
    if (
        summary_digest != canonical_json_sha256(summary_body)
        or summary_digest != parents["native_classification_artifact_digest"]
    ):
        raise ContractError("corrected native-coincidence classification summary changed")
    rows = _load_jsonl(classification_path)
    if canonical_json_sha256(rows) != parents["native_classification_row_digest"]:
        raise ContractError("corrected native-coincidence classified rows changed")

    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        source = connection.execute(
            "SELECT detector,gps_start,identity_digest,image_sha256 FROM windows "
            "WHERE is_candidate=1 ORDER BY detector,gps_start"
        ).fetchall()
    finally:
        connection.close()
    primary_map = {
        (str(detector), float(gps)): {
            "identity_digest": str(identity_digest),
            "image_sha256": str(image_sha256),
        }
        for detector, gps, identity_digest, image_sha256 in source
    }
    if len(primary_map) != 10942 or len(rows) != 10942:
        raise ContractError("corrected native-coincidence parent population changed")
    for row in rows:
        identity = (str(row["detector"]), float(row["gps_start"]))
        parent = primary_map.get(identity)
        if (
            parent is None
            or parent["identity_digest"] != str(row["identity_digest"])
            or parent["image_sha256"] != str(row["image_sha256"])
        ):
            raise ContractError("corrected native-coincidence seed identity join changed")
    return rows, database_path, primary_map, index_path


def _build_plans(
    seeds: Sequence[Mapping[str, Any]],
    *,
    raw_manifest_path: Path,
    raw_root: Path,
    primary_map: Mapping[tuple[str, float], Mapping[str, str]],
) -> tuple[
    dict[tuple[str, float], dict[str, Any]],
    dict[tuple[str, float], str],
    list[dict[str, Any]],
]:
    from src.core.patch_producer import load_frozen_raw_manifest

    manifests = {
        detector: load_frozen_raw_manifest(
            raw_manifest_path, raw_root=raw_root, detector=detector
        )
        for detector in ("H1", "L1")
    }
    plans: dict[tuple[str, float], dict[str, Any]] = {}
    unavailable: dict[tuple[str, float], str] = {}
    for seed in seeds:
        detector = str(seed["detector"])
        gps = float(seed["gps_start"])
        for role, current in (("candidate", detector), ("partner", _opposite(detector))):
            identity = (current, gps)
            if identity in plans or identity in unavailable:
                continue
            sources = _context_plan(
                manifests[current], detector=current, gps=gps, pad_s=4.0
            )
            if not sources:
                if role == "candidate":
                    raise ContractError(
                        f"corrected native-coincidence candidate context missing: {identity}"
                    )
                unavailable[identity] = "NO_COMPLETE_FROZEN_RAW_CONTEXT"
                continue
            parent = primary_map.get(identity)
            plans[identity] = {
                "detector": current,
                "gps_start": gps,
                "context_sources": sources,
                "expected_image_sha256": (
                    None if parent is None else parent["image_sha256"]
                ),
            }
    sources_by_path: dict[str, dict[str, Any]] = {}
    for plan in plans.values():
        for source in plan["context_sources"]:
            path = str(Path(source["absolute_path"]).resolve())
            current = sources_by_path.setdefault(
                path,
                {"absolute_path": path, "sha256": str(source["sha256"])},
            )
            if current["sha256"] != source["sha256"]:
                raise ContractError("corrected native-coincidence raw manifest conflict")
    return plans, unavailable, [sources_by_path[key] for key in sorted(sources_by_path)]


def _scorer_manifest(path: Path, *, index_path: Path, index_sha256: str) -> None:
    _atomic_json(
        path,
        {
            "schema_version": 1,
            "artifact_root": str(index_path.parent),
            "reference_indices": {
                "o4a_corrected_detector_aware_v1": {
                    "path": index_path.name,
                    "sha256": index_sha256,
                    "embedding_dim": 384,
                    "n_centroids": 1216,
                    "qrange": [4, 64],
                    "role": "corrected asymmetric physical coincidence",
                }
            },
        },
    )


def _measure_populations(
    *,
    primary: Sequence[Mapping[str, Any]],
    diagnostic: Sequence[Mapping[str, Any]],
    plans: Mapping[tuple[str, float], Mapping[str, Any]],
    unavailable: Mapping[tuple[str, float], str],
    receipt: Sequence[Mapping[str, Any]],
    raw_root: Path,
    scorer: Any,
    contract: Mapping[str, Any],
    workers: int,
    batch_size: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_delta = float(contract["gates"]["maximum_seed_score_delta"])
    measurement = contract["measurement"]
    outputs: dict[str, list[dict[str, Any]]] = {"primary": [], "diagnostic": []}
    context = mp.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=context,
        initializer=_initialize_worker,
        initargs=(str(raw_root), list(receipt)),
    ) as executor:
        for population_name, seeds in (("primary", primary), ("diagnostic", diagnostic)):
            for start in range(0, len(seeds), batch_size):
                batch = seeds[start : start + batch_size]
                needed: dict[tuple[str, float], Mapping[str, Any]] = {}
                for seed in batch:
                    detector = str(seed["detector"])
                    gps = float(seed["gps_start"])
                    needed[(detector, gps)] = plans[(detector, gps)]
                    partner_key = (_opposite(detector), gps)
                    if partner_key in plans:
                        needed[partner_key] = plans[partner_key]
                identities = sorted(needed, key=lambda key: (key[1], key[0]))
                prepared_rows = list(
                    executor.map(_prepare_identity, [needed[key] for key in identities])
                )
                images = [row["image"] for row in prepared_rows]
                tokens = scorer.encode_patch_tokens(images)
                scored_rows = scorer.score_patch_tokens(tokens, 1.0, output_mode="full")
                prepared: dict[tuple[str, float], dict[str, Any]] = {}
                for identity, row, scored in zip(
                    identities, prepared_rows, scored_rows, strict=True
                ):
                    value = {key: item for key, item in row.items() if key not in {"image"}}
                    value["clean"] = row["clean"]
                    value["native_score"] = float(scored["novelty_score"])
                    value["top_k_indices"] = np.asarray(
                        scored["top_k_indices"], dtype=np.int32
                    )
                    prepared[identity] = value
                for seed in batch:
                    detector = str(seed["detector"])
                    gps = float(seed["gps_start"])
                    partner = _opposite(detector)
                    seed_key = (detector, gps)
                    partner_key = (partner, gps)
                    candidate = prepared[seed_key]
                    score_delta = abs(
                        float(candidate["native_score"]) - float(seed["native_score"])
                    )
                    if score_delta > max_delta:
                        raise ContractError(
                            "corrected native-coincidence seed score replay changed"
                        )
                    base = {
                        "population": population_name,
                        "detector": detector,
                        "gps_start": gps,
                        "partner": partner,
                        "seed_native_class": str(seed["native_class"]),
                        "seed_identity_digest": str(seed["identity_digest"]),
                        "seed_native_score": float(seed["native_score"]),
                        "seed_replay_score": float(candidate["native_score"]),
                        "seed_score_delta": score_delta,
                        "seed_image_sha256": str(candidate["image_sha256"]),
                        "seed_clean_window_sha256": str(
                            candidate["clean_window_sha256"]
                        ),
                        "seed_raw_context_sha256": str(
                            candidate["raw_context_sha256"]
                        ),
                        "seed_context_sources": candidate["context_sources"],
                        "seed_context_sources_digest": candidate[
                            "context_sources_digest"
                        ],
                        "seed_top_k_indices": candidate["top_k_indices"].tolist(),
                    }
                    if partner_key in unavailable:
                        outputs[population_name].append(
                            {
                                **base,
                                "measurement_status": "PARTNER_DATA_UNAVAILABLE",
                                "unavailable_reason": unavailable[partner_key],
                                "partner_class_consulted": False,
                                "cc_onsource": None,
                                "cc_null_values": [],
                                "cc_null_mean": None,
                                "cc_null_max": None,
                                "n_null": 0,
                                "patch_iou": None,
                                "per_event_null_exceeded": None,
                                "exceeds_primary_threshold": None,
                            }
                        )
                        continue
                    partner_row = prepared[partner_key]
                    physical = measure_physical_arrays(
                        candidate["clean"],
                        partner_row["clean"],
                        candidate["top_k_indices"],
                        partner_row["top_k_indices"],
                        measurement=measurement,
                    )
                    outputs[population_name].append(
                        {
                            **base,
                            "measurement_status": "MEASURED",
                            "partner_class_consulted": False,
                            "partner_image_sha256": str(partner_row["image_sha256"]),
                            "partner_clean_window_sha256": str(
                                partner_row["clean_window_sha256"]
                            ),
                            "partner_raw_context_sha256": str(
                                partner_row["raw_context_sha256"]
                            ),
                            "partner_context_sources": partner_row["context_sources"],
                            "partner_context_sources_digest": partner_row[
                                "context_sources_digest"
                            ],
                            "partner_top_k_indices": partner_row[
                                "top_k_indices"
                            ].tolist(),
                            **physical,
                            "exceeds_primary_threshold": None,
                        }
                    )
    return outputs["primary"], outputs["diagnostic"]


def _event_summary(
    primary: list[dict[str, Any]],
    diagnostic: list[dict[str, Any]],
    *,
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], float]:
    threshold = primary_null_threshold(primary, measurement=contract["measurement"])
    for row in [*primary, *diagnostic]:
        if row["measurement_status"] == "MEASURED":
            row["exceeds_primary_threshold"] = bool(row["cc_onsource"] > threshold)
    result: dict[str, Any] = {"primary_null_p99": threshold}
    for name, rows in (("primary", primary), ("diagnostic", diagnostic)):
        measured = [row for row in rows if row["measurement_status"] == "MEASURED"]
        result[name] = {
            "seed_total": len(rows),
            "measured": len(measured),
            "partner_data_unavailable": sum(
                row["measurement_status"] == "PARTNER_DATA_UNAVAILABLE" for row in rows
            ),
            "per_event_null_exceeded": sum(
                bool(row["per_event_null_exceeded"]) for row in measured
            ),
            "primary_threshold_exceeded": sum(
                bool(row["exceeds_primary_threshold"]) for row in measured
            ),
        }
    return result, threshold


def _anchor_check(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    matches = [
        row
        for row in rows
        if str(row["detector"]) == "L1" and float(row["gps_start"]) == 1382955232.0
    ]
    if len(matches) != 1:
        raise ContractError("corrected native-coincidence historical anchor is ambiguous")
    row = matches[0]
    return {
        "catalog_gps": 1382955228.0,
        "analysis_window_gps": 1382955232.0,
        "localized_feature_gps": 1382955253.17,
        "detector": "L1",
        "corrected_native_class": str(row["native_class"]),
        "included_in_primary_seed_population": str(row["native_class"]) == "ROBUST",
        "identity_digest": str(row["identity_digest"]),
    }


def _run_key(contract: Mapping[str, Any], *, runtime: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "stage": "native_coincidence_v1",
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "parents": contract["parents"],
        }
    )


def run_native_coincidence(
    *,
    root: Path = ROOT,
    raw_root: Path,
    primary_external_root: Path,
    classification_external_root: Path,
    index_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
    workers: int = 8,
    batch_size: int = 32,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_coincidence_contract(root)
    execution = contract["execution"]
    if workers != int(execution["workers"]) or batch_size != int(
        execution["batch_size"]
    ):
        raise ContractError("corrected native-coincidence execution parameters changed")
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = _run_key(contract, runtime=runtime)
    run_dir = external_root.resolve() / f"native_coincidence_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_path = run_dir / "failure.json"
    summary_path = run_dir / contract["output"]["summary_filename"]
    primary_path = run_dir / contract["output"]["primary_filename"]
    diagnostic_path = run_dir / contract["output"]["diagnostic_filename"]
    receipt_path = run_dir / contract["output"]["raw_receipt_filename"]
    if failure_path.is_file():
        raise ContractError("corrected native-coincidence failure artifact is present")
    if summary_path.is_file():
        return verify_native_coincidence(
            root=root,
            primary_external_root=primary_external_root,
            classification_external_root=classification_external_root,
            index_external_root=index_external_root,
            external_root=external_root,
            device=device,
        )
    try:
        rows, database_path, primary_map, index_path = _verified_inputs(
            root=root,
            contract=contract,
            primary_external_root=primary_external_root,
            classification_external_root=classification_external_root,
            index_external_root=index_external_root,
        )
        primary, diagnostic = split_seed_populations(rows, contract=contract)
        raw_manifest_path = root / contract["references"]["raw_manifest"]["path"]
        plans, unavailable, source_records = _build_plans(
            [*primary, *diagnostic],
            raw_manifest_path=raw_manifest_path,
            raw_root=raw_root.resolve(),
            primary_map=primary_map,
        )
        with ThreadPoolExecutor(max_workers=workers) as executor:
            receipt = list(executor.map(_verify_source, source_records))
        _atomic_jsonl(receipt_path, receipt)
        scorer_manifest = run_dir / "scorer_artifact_manifest.json"
        _scorer_manifest(
            scorer_manifest,
            index_path=index_path,
            index_sha256=contract["parents"]["native_index_sha256"],
        )
        from src.core.patch_scorer import PatchScorer

        scorer = PatchScorer(
            index_path,
            device=device,
            k=int(contract["scoring"]["top_k"]),
            expected_sha256=contract["parents"]["native_index_sha256"],
            artifact_manifest_path=scorer_manifest,
            k_ablations=[],
            n_background=0,
        )
        primary_events, diagnostic_events = _measure_populations(
            primary=primary,
            diagnostic=diagnostic,
            plans=plans,
            unavailable=unavailable,
            receipt=receipt,
            raw_root=raw_root.resolve(),
            scorer=scorer,
            contract=contract,
            workers=workers,
            batch_size=batch_size,
        )
        event_summary, _threshold = _event_summary(
            primary_events, diagnostic_events, contract=contract
        )
        _atomic_jsonl(primary_path, primary_events)
        _atomic_jsonl(diagnostic_path, diagnostic_events)
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_COMPLETE_NATIVE_COINCIDENCE_V1",
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "population": contract["population"],
            "measurement": contract["measurement"],
            "scientific_boundary": contract["scientific_boundary"],
            "event_summary": event_summary,
            "historical_anchor_check": _anchor_check(rows),
            "sources": {
                "classification_row_digest": canonical_json_sha256(rows),
                "primary_database_sha256": sha256_file(database_path),
                "native_index_sha256": sha256_file(index_path),
                "raw_source_count": len(receipt),
                "raw_source_receipt_digest": canonical_json_sha256(receipt),
            },
            "outputs": {
                "primary": {
                    "filename": primary_path.name,
                    "row_total": len(primary_events),
                    "sha256": sha256_file(primary_path),
                    "row_digest": canonical_json_sha256(primary_events),
                },
                "diagnostic": {
                    "filename": diagnostic_path.name,
                    "row_total": len(diagnostic_events),
                    "sha256": sha256_file(diagnostic_path),
                    "row_digest": canonical_json_sha256(diagnostic_events),
                },
                "raw_source_receipt": {
                    "filename": receipt_path.name,
                    "row_total": len(receipt),
                    "sha256": sha256_file(receipt_path),
                    "row_digest": canonical_json_sha256(receipt),
                },
            },
            "gates": {
                "duplicate_seed_detector_gps": 0,
                "partner_class_reads": 0,
                "background_measurements": 0,
                "seed_image_hash_mismatches": 0,
                "seed_score_delta_max": max(
                    row["seed_score_delta"] for row in [*primary_events, *diagnostic_events]
                ),
                "unaccounted_seeds": 0,
            },
        }
        summary = {**body, "artifact_digest": canonical_json_sha256(body)}
        _atomic_json(summary_path, summary)
        return summary, run_dir
    except BaseException as exc:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_NATIVE_COINCIDENCE_V1",
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_native_coincidence(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    classification_external_root: Path,
    index_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_coincidence_contract(root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = _run_key(contract, runtime=runtime)
    run_dir = external_root.resolve() / f"native_coincidence_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("corrected native-coincidence failure artifact is present")
    summary_path = run_dir / contract["output"]["summary_filename"]
    if not summary_path.is_file():
        raise ContractError("corrected native-coincidence summary is missing")
    summary = _read_json(summary_path)
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if (
        digest != canonical_json_sha256(body)
        or summary.get("status") != "PASS_COMPLETE_NATIVE_COINCIDENCE_V1"
        or summary.get("run_key") != run_key
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("population") != contract["population"]
        or summary.get("measurement") != contract["measurement"]
        or summary.get("scientific_boundary") != contract["scientific_boundary"]
    ):
        raise ContractError("corrected native-coincidence summary changed")
    rows, database_path, _primary_map, index_path = _verified_inputs(
        root=root,
        contract=contract,
        primary_external_root=primary_external_root,
        classification_external_root=classification_external_root,
        index_external_root=index_external_root,
    )
    primary_seeds, diagnostic_seeds = split_seed_populations(rows, contract=contract)
    observed: dict[str, list[dict[str, Any]]] = {}
    for name in ("primary", "diagnostic", "raw_source_receipt"):
        spec = summary["outputs"][name]
        path = run_dir / spec["filename"]
        values = _load_jsonl(path)
        if (
            not path.is_file()
            or sha256_file(path) != spec["sha256"]
            or canonical_json_sha256(values) != spec["row_digest"]
            or len(values) != int(spec["row_total"])
        ):
            raise ContractError(f"corrected native-coincidence {name} output changed")
        observed[name] = values
    for name, seeds in (("primary", primary_seeds), ("diagnostic", diagnostic_seeds)):
        events = observed[name]
        expected_keys = [
            (str(row["detector"]), float(row["gps_start"])) for row in seeds
        ]
        event_keys = [
            (str(row["detector"]), float(row["gps_start"])) for row in events
        ]
        if (
            event_keys != expected_keys
            or any(row.get("population") != name for row in events)
            or any(row.get("partner_class_consulted") is not False for row in events)
            or any("partner_native_class" in row or "partner_class" in row for row in events)
        ):
            raise ContractError(f"corrected native-coincidence {name} ledger changed")
    recomputed_summary, _threshold = _event_summary(
        observed["primary"], observed["diagnostic"], contract=contract
    )
    if (
        summary.get("event_summary") != recomputed_summary
        or summary.get("historical_anchor_check") != _anchor_check(rows)
        or summary.get("sources", {}).get("classification_row_digest")
        != canonical_json_sha256(rows)
        or summary.get("sources", {}).get("primary_database_sha256")
        != sha256_file(database_path)
        or summary.get("sources", {}).get("native_index_sha256")
        != sha256_file(index_path)
        or summary.get("sources", {}).get("raw_source_receipt_digest")
        != canonical_json_sha256(observed["raw_source_receipt"])
    ):
        raise ContractError("corrected native-coincidence verification changed")
    expected_gates = {
        "duplicate_seed_detector_gps": 0,
        "partner_class_reads": 0,
        "background_measurements": 0,
        "seed_image_hash_mismatches": 0,
        "seed_score_delta_max": max(
            row["seed_score_delta"]
            for row in [*observed["primary"], *observed["diagnostic"]]
        ),
        "unaccounted_seeds": 0,
    }
    if summary.get("gates") != expected_gates:
        raise ContractError("corrected native-coincidence gates changed")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "load_native_coincidence_contract",
    "measure_physical_arrays",
    "primary_null_threshold",
    "run_native_coincidence",
    "split_seed_populations",
    "validate_native_coincidence_contract",
    "verify_native_coincidence",
]
