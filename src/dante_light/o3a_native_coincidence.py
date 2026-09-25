"""Pre-run O3a physical-coincidence contract and outcome-blind source planning.

The physical statistic is the frozen corrected-O4a implementation. This
module does not measure coincidence or open strain until the parent and raw
source plans have been bound to an O3a-only run key.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import bisect
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence

import numpy as np

from src.dante_light import o3a_native_classification as nc
from src.dante_light import o3a_native_taxonomy as tx
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_calibration_cohort import _atomic_json, _atomic_jsonl
from src.dante_light.o3a_native_contract import ROOT, RUNTIME_REL, load_runtime_contract
from src.dante_light.o3a_native_rescore import (
    CONTRACT_REL as RESCORE_CONTRACT_REL,
    _evict_finished_frames,
    _frame_dependency_order,
    _load_scorer,
    _prepare_batch_sources,
    load_rescore_contract,
)
from src.dante_light.o3a_primary_scan import InfrastructureError, _download_frame
from src.dante_light.o3a_raw_acquisition import (
    INVENTORY_REL,
    _cover_interval,
    _inventory_frames,
    load_source_inventory,
)
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_light.o3a_native_cohort import _raw_frame_rows
from src.dante_light.o3a_scale_adequacy import STAGE_CONTRACT_REL, load_stage_contract
from src.dante_light.o4a_corrected_native_coincidence import (
    measure_physical_arrays,
    primary_null_threshold,
)

CONTRACT_REL = "config/dante_o3a_native_coincidence_v1.json"
COMPACT_REL = "artifacts/dante_light/o3a_native_v1/native_coincidence.json"
METHOD_REL = "config/dante_o4a_corrected_native_coincidence_v1.json"
CLASSIFICATION_REL = nc.COMPACT_REL
TAXONOMY_REL = tx.COMPACT_REL
INDEX_REL = "artifacts/dante_light/o3a_native_v1/native_index.json"
PRIMARY_REL = "artifacts/dante_light/o3a_native_v1/primary_scan.json"
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")
SOURCE_PATHS = (
    "src/dante_light/o3a_native_coincidence.py",
    "scripts/run_dante_o3a_native_coincidence.py",
    "tests/test_dante_o3a_native_coincidence.py",
    "src/dante_light/o4a_corrected_native_coincidence.py",
    "src/pipeline_v2_production/coincidence_physical.py",
    "src/dante_light/o3a_native_rescore.py",
    "src/dante_light/o3a_native_calibration_cohort.py",
    "src/dante_light/o3a_primary_scan.py",
    "src/dante_light/o3a_raw_acquisition.py",
    "src/dante_light/o3a_raw_download.py",
    "src/dante_light/contracts.py",
    "src/core/preprocessor.py",
    "src/core/patch_scorer.py",
    "src/core/encoder.py",
    "src/core/model_loader.py",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _sealed(path: Path, key: str) -> dict[str, Any]:
    value = _read_json(path)
    body = dict(value)
    if body.pop(key, None) != canonical_json_sha256(body):
        raise ContractError(f"O3a coincidence parent seal changed: {path}")
    return value


def _binding(root: Path, relative: str, *, seal: str | None = None) -> dict[str, Any]:
    value = {
        "path": relative,
        "sha256": file_sha256(root / relative),
    }
    if seal is not None:
        value["artifact_digest"] = seal
    return value


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Bind approved O4a method and verified O3a parents without strain access."""
    root = root.resolve()
    stage = load_stage_contract(root=root)
    decision = stage["author_decisions"]["coincidence_interpretation"]
    if decision != {
        "global_significance_claim_allowed": False,
        "partner_class_required": False,
        "primary_role": "POOLED_NULL_EXCEEDANCES_ARE_DIAGNOSTIC_PEM_SHORTLIST_ONLY",
        "robust_seed_asymmetric_partner_evaluation": True,
        "time_slide_full_pipeline_null_required_for_global_claim": True,
    }:
        raise ContractError("O3a coincidence interpretation changed")
    method = _sealed(root / METHOD_REL, "contract_digest")
    classified = _sealed(root / CLASSIFICATION_REL, "artifact_digest")
    taxonomy = _sealed(root / TAXONOMY_REL, "artifact_digest")
    index = _sealed(root / INDEX_REL, "artifact_digest")
    primary = _sealed(root / PRIMARY_REL, "artifact_digest")
    runtime = load_runtime_contract(root=root)
    rescore = load_rescore_contract(root=root)
    inventory = load_source_inventory(root=root)
    if (
        classified.get("status") != "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION"
        or taxonomy.get("status") != "PASS_VERIFIED_O3A_NATIVE_TAXONOMY"
        or taxonomy.get("parent_native_classification_artifact_digest")
        != classified["artifact_digest"]
        or taxonomy.get("parent_primary_scan_artifact_digest")
        != primary["artifact_digest"]
        or classified.get("row_total") != primary.get("candidate_total")
        or taxonomy.get("row_total") != classified.get("row_total")
        or index.get("status") != "PASS_BUILT_O3A_NATIVE_INDEX"
        or method.get("scientific_boundary", {}).get("asymmetric_seed_search") is not True
        or method.get("population", {}).get("partner_class_read") is not False
        or method.get("measurement", {}).get("threshold_source")
        != "primary_seed_per_event_null_maxima_only"
        or rescore["representation"]["image_shape"] != method["scoring"]["image_shape"]
        or rescore["representation"]["colormap"] != method["scoring"]["colormap"]
        or rescore["scoring"]["top_k"] != method["scoring"]["top_k"]
        or rescore["preprocessing"]["sample_rate_hz"]
        != method["measurement"]["sample_rate_hz"]
    ):
        raise ContractError("O3a coincidence parents or O4a method changed")
    counts = classified["counts_by_detector_and_class"]
    if set(counts) != {"H1", "L1"} or any(
        set(counts[detector]) != {"ROBUST", "AMBIGUOUS", "BACKGROUND"}
        for detector in counts
    ):
        raise ContractError("O3a coincidence class population changed")
    population = {
        "primary_seed_class": "ROBUST",
        "diagnostic_seed_class": "AMBIGUOUS",
        "excluded_class": "BACKGROUND",
        "partner_selection": method["population"]["partner_selection"],
        "partner_class_read": False,
        "primary_and_diagnostic_threshold_pools_separate": True,
        "exact_counts": {
            bucket: {
                **{d: int(counts[d][label]) for d in ("H1", "L1")},
                "total": sum(int(counts[d][label]) for d in ("H1", "L1")),
            }
            for bucket, label in (
                ("primary", "ROBUST"),
                ("diagnostic", "AMBIGUOUS"),
                ("excluded", "BACKGROUND"),
            )
        },
    }
    if sum(v["total"] for v in population["exact_counts"].values()) != 8900:
        raise ContractError("O3a coincidence exact seed total changed")
    parents = {
        "native_classification": _binding(root, CLASSIFICATION_REL, seal=classified["artifact_digest"]),
        "native_taxonomy": _binding(root, TAXONOMY_REL, seal=taxonomy["artifact_digest"]),
        "native_index": {
            **_binding(root, INDEX_REL, seal=index["artifact_digest"]),
            "centroid_count": index["index"]["centroid_shape"][0],
            "index_sha256": index["index"]["sha256"],
            "run_key": index["run_key"],
            "index_filename": index["index"]["filename"],
        },
        "primary_scan": _binding(root, PRIMARY_REL, seal=primary["artifact_digest"]),
        "native_rescore_contract": _binding(root, RESCORE_CONTRACT_REL),
        "o3a_stage_decision": _binding(root, STAGE_CONTRACT_REL),
        "o3a_source_inventory": _binding(root, INVENTORY_REL),
        "o3a_runtime": _binding(root, RUNTIME_REL),
        "corrected_o4a_method": _binding(root, METHOD_REL),
    }
    body = {
        "schema_version": 1,
        "status": "FROZEN_O3A_NATIVE_COINCIDENCE_V1",
        "run": "O3A",
        "parents": parents,
        "population": population,
        "measurement": method["measurement"],
        "representation": rescore["representation"],
        "scoring": {
            **method["scoring"],
            "index": "o3a_native_detector_aware_v1",
            "temporary_threshold": rescore["scoring"]["temporary_threshold"],
        },
        "execution": {
            "workers": 8,
            "batch_size": 32,
            "download_retries": 5,
            "raw_cache_limit_bytes": 8 * 1024**3,
            "free_space_reserve_bytes": 16 * 1024**3,
            "resume_unit": "VERIFIED_EVENT_BATCH_SHARD",
        },
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "o4a_method_precedent_digest": method["contract_digest"],
        "source_inventory_digest": inventory["inventory_digest"],
        "pre_registered_limitation": {
            "within_seed_shift_count_upper_bound": len(method["measurement"]["null_shifts_s"]),
            "pooled_p99_unit": "ONE_NULL_MAXIMUM_PER_MEASURED_ROBUST_SEED",
            "effective_independence_established": False,
            "tail_precision_established": False,
            "global_look_elsewhere_control": False,
            "no_post_hoc_retuning": True,
        },
        "scientific_boundary": {
            "o4a_scientific_rows_or_thresholds_imported": False,
            "partner_class_consulted": False,
            "taxonomy_family_used": False,
            "diagnostic_only": True,
            "global_significance_claim": False,
            "multiscale_used": False,
        },
        "implementation_sources": {p: file_sha256(root / p) for p in SOURCE_PATHS},
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def freeze_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def load_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = _sealed(root / CONTRACT_REL, "contract_digest")
    if value != build_contract(root=root):
        raise ContractError("O3a coincidence frozen contract or source changed")
    return value


def split_seed_populations(
    rows: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify seed roles without reading partner class or morphology family."""
    classes = {"ROBUST": "primary", "AMBIGUOUS": "diagnostic", "BACKGROUND": "excluded"}
    expected = contract["population"]["exact_counts"]
    observed: dict[str, Counter[str]] = {name: Counter() for name in expected}
    groups: dict[str, list[dict[str, Any]]] = {"primary": [], "diagnostic": []}
    identities: set[tuple[str, int]] = set()
    for source in rows:
        detector = str(source.get("detector"))
        gps = source.get("gps_start")
        label = str(source.get("native_class"))
        if detector not in {"H1", "L1"} or type(gps) is not int or label not in classes:
            raise ContractError("O3a coincidence seed identity or class is invalid")
        identity = detector, gps
        if identity in identities:
            raise ContractError("O3a coincidence duplicate seed identity")
        identities.add(identity)
        group = classes[label]
        observed[group][detector] += 1
        if group in groups:
            groups[group].append(dict(source))
    for name in expected:
        counts = {d: observed[name][d] for d in ("H1", "L1")}
        counts["total"] = sum(counts.values())
        if counts != expected[name]:
            raise ContractError(f"O3a coincidence {name} population changed")
    def order(row: Mapping[str, Any]) -> tuple[int, str]:
        return int(row["gps_start"]), str(row["detector"])

    return sorted(groups["primary"], key=order), sorted(groups["diagnostic"], key=order)


def _source_plan(
    *, detector: str, gps: int, frames: Sequence[Mapping[str, Any]],
    starts: Sequence[int], ledger: Mapping[tuple[str, str], Mapping[str, Any]],
    pad: int, duration: int,
) -> list[dict[str, Any]]:
    start, end = gps - pad, gps + duration + pad
    position = max(0, bisect.bisect_right(starts, start) - 1)
    nearby: list[Mapping[str, Any]] = []
    while position < len(frames) and int(frames[position]["gps_start"]) < end:
        if int(frames[position]["gps_end"]) > start:
            nearby.append(frames[position])
        position += 1
    selected = _cover_interval(nearby, start, end)
    result: list[dict[str, Any]] = []
    cursor = start
    for frame in selected:
        name = str(frame["filename"])
        source = ledger.get((detector, name))
        if source is not None and (
            source["detector"] != detector
            or any(
                source[key] != frame[key]
                for key in ("filename", "gps_start", "gps_end", "url")
            )
        ):
            raise ContractError("O3a coincidence scan raw-frame identity changed")
        used_end = min(end, int(frame["gps_end"]))
        result.append({
            "detector": detector,
            "gps_start": int(frame["gps_start"]),
            "gps_end": int(frame["gps_end"]),
            "filename": name,
            "url": str(frame["url"]),
            "sha256": None if source is None else str(source["sha256"]),
            "size_bytes": None if source is None else int(source["size_bytes"]),
            "used_interval_gps": [cursor, used_end],
        })
        cursor = used_end
    if cursor != end:
        raise ContractError("O3a coincidence source plan has incomplete context")
    return result


def plan_sources(
    seeds: Sequence[Mapping[str, Any]], *,
    frames_by_detector: Mapping[str, Sequence[Mapping[str, Any]]],
    raw_frame_ledger: Mapping[tuple[str, str], Mapping[str, Any]],
    pad: int, duration: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Map each seed and opposite detector to inventory frames, not classes."""
    starts = {
        d: [int(frame["gps_start"]) for frame in frames_by_detector[d]]
        for d in ("H1", "L1")
    }
    seed_map = {
        (str(row["detector"]), int(row["gps_start"])): row for row in seeds
    }
    if len(seed_map) != len(seeds):
        raise ContractError("O3a coincidence source plan has duplicate seeds")
    source_plans: dict[tuple[str, int], dict[str, Any]] = {}
    for seed in seeds:
        detector, gps = str(seed["detector"]), int(seed["gps_start"])
        for current in (detector, "L1" if detector == "H1" else "H1"):
            key = current, gps
            if key in source_plans:
                continue
            required = key in seed_map
            try:
                sources = _source_plan(
                    detector=current, gps=gps,
                    frames=frames_by_detector[current], starts=starts[current],
                    ledger=raw_frame_ledger, pad=pad, duration=duration,
                )
            except ContractError as exc:
                if required or "raw source coverage gap" not in str(exc):
                    raise
                source_plans[key] = {
                    "detector": current, "gps_start": gps,
                    "role": "PARTNER", "availability": "NO_COMPLETE_SOURCE_COVERAGE",
                    "sources": [],
                }
                continue
            if required:
                parent_sources = seed_map[key].get("context_sources")
                if parent_sources is not None and sources != parent_sources:
                    raise ContractError("O3a coincidence seed source context changed")
            source_plans[key] = {
                "detector": current, "gps_start": gps,
                "role": "SEED" if required else "PARTNER",
                "availability": "SOURCE_COVERED",
                "sources": sources,
            }
    ordered = [source_plans[key] for key in sorted(source_plans, key=lambda k: (k[1], k[0]))]
    frame_map: dict[tuple[str, str], dict[str, Any]] = {}
    for plan in ordered:
        for source in plan["sources"]:
            key = str(source["detector"]), str(source["filename"])
            meta = {k: source[k] for k in ("detector", "gps_start", "gps_end", "filename", "url", "sha256", "size_bytes")}
            if key in frame_map and frame_map[key] != meta:
                raise ContractError("O3a coincidence divergent source-frame metadata")
            frame_map[key] = meta
    audit = {
        "seed_total": len(seeds),
        "identity_total": len(ordered),
        "partner_source_coverage_unavailable": sum(
            plan["availability"] != "SOURCE_COVERED" for plan in ordered
        ),
        "unique_source_frame_count": len(frame_map),
        "unhashed_new_source_frame_count": sum(
            frame["sha256"] is None for frame in frame_map.values()
        ),
        "partner_class_consulted": False,
        "strain_opened": False,
        "coincidence_outcomes_opened": False,
    }
    return ordered, audit


def _preflight_details(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
    contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Read frozen metadata and classes; never open strain or coincidence scores."""
    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root) if contract is None else contract
    classified = _sealed(root / CLASSIFICATION_REL, "artifact_digest")
    primary = _sealed(root / PRIMARY_REL, "artifact_digest")
    class_dir = external_root / f"native_classification_{classified['run_key']}"
    scan_dir = external_root / f"primary_scan_{primary['run_key']}"
    class_file = class_dir / "native_classified_candidates.jsonl"
    scan_database = scan_dir / primary["database"]["filename"]
    if (
        not class_file.is_file()
        or not scan_database.is_file()
        or file_sha256(class_file) != classified["output_sha256"]
        or file_sha256(scan_database) != primary["database"]["sha256"]
    ):
        raise ContractError("O3a coincidence classification or scan parent changed")
    rows = [json.loads(line) for line in class_file.read_text(encoding="utf-8").splitlines() if line]
    if canonical_json_sha256(rows) != classified["output_row_digest"]:
        raise ContractError("O3a coincidence classified row digest changed")
    primary_seeds, diagnostic_seeds = split_seed_populations(rows, contract=contract)
    seeds = [*primary_seeds, *diagnostic_seeds]
    inventory = load_source_inventory(root=root)
    frames = {d: _inventory_frames(inventory, d) for d in ("H1", "L1")}
    ledger = _raw_frame_rows(scan_database)
    measurement = contract["measurement"]
    plans, audit = plan_sources(
        seeds, frames_by_detector=frames, raw_frame_ledger=ledger,
        pad=int(measurement["whitening_pad_s"]),
        duration=int(measurement["segment_duration_s"]),
    )
    body = {
        "schema_version": 1,
        "status": "PASS_O3A_COINCIDENCE_SOURCE_PREFLIGHT",
        "contract_digest": contract["contract_digest"],
        "source_classification_sha256": file_sha256(class_file),
        "source_scan_database_sha256": file_sha256(scan_database),
        "source_inventory_digest": inventory["inventory_digest"],
        "seed_population_digest": canonical_json_sha256(seeds),
        "source_plan_digest": canonical_json_sha256(plans),
        "source_audit": audit,
    }
    return {**body, "preflight_digest": canonical_json_sha256(body)}, plans, seeds


def preflight_sources(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
    contract: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Path]:
    preflight, _plans, _seeds = _preflight_details(
        root=root, external_root=external_root, contract=contract,
    )
    return preflight, external_root.resolve()


def _run_key(contract: Mapping[str, Any], preflight: Mapping[str, Any]) -> str:
    return canonical_json_sha256({
        "stage": "o3a_native_coincidence_v1",
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "runtime_environment_digest": contract["runtime_environment_digest"],
    })


def _read_context(task: tuple[Mapping[str, Any], str, Mapping[str, Any]]) -> dict[str, Any]:
    """Replay exact O3a strain image and retain clean values for the statistic."""
    import h5py
    import matplotlib.pyplot as plt
    from gwpy.timeseries import TimeSeries

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    plan, cache_text, contract = task
    detector, gps = str(plan["detector"]), int(plan["gps_start"])
    sample_rate = int(contract["measurement"]["sample_rate_hz"])
    pad = int(contract["measurement"]["whitening_pad_s"])
    duration = int(contract["measurement"]["segment_duration_s"])
    cache = Path(cache_text).resolve()
    pieces: list[np.ndarray] = []
    for source in plan["sources"]:
        path = (cache / detector / str(source["filename"])).resolve()
        if path.parent != (cache / detector).resolve():
            raise ContractError("O3a coincidence raw path escaped cache")
        frame_start = int(source["gps_start"])
        used_start, used_end = [int(x) for x in source["used_interval_gps"]]
        first = (used_start - frame_start) * sample_rate
        last = (used_end - frame_start) * sample_rate
        with h5py.File(path, "r") as handle:
            dataset = handle.get("strain/Strain")
            if dataset is None or tuple(dataset.shape) != (
                (int(source["gps_end"]) - frame_start) * sample_rate,
            ):
                raise ContractError("O3a coincidence raw HDF5 shape changed")
            piece = np.asarray(dataset[first:last], dtype=np.float64)
        if piece.shape != (last - first,):
            raise ContractError("O3a coincidence raw HDF5 slice is short")
        pieces.append(piece)
    if not pieces:
        raise ContractError("O3a coincidence covered context is empty")
    raw = np.ascontiguousarray(np.concatenate(pieces), dtype=np.float64)
    if raw.shape != ((duration + 2 * pad) * sample_rate,):
        raise ContractError("O3a coincidence raw context length changed")
    if not np.isfinite(raw).all():
        if plan["role"] == "SEED":
            raise ContractError("O3a coincidence seed raw context is non-finite")
        return {
            "detector": detector,
            "gps_start": gps,
            "availability": "PARTNER_RAW_CONTEXT_NONFINITE",
        }
    series = TimeSeries(
        raw, t0=gps - pad, sample_rate=sample_rate,
        name=f"{detector}:GWOSC-4KHZ_R1_STRAIN",
    )
    whitened, info = whiten_context(series, gps, gps + duration, pad=pad)
    tolerance = 1.0 / sample_rate
    if (
        float(info["effective_left"]) < pad - tolerance
        or float(info["effective_right"]) < pad - tolerance
    ):
        raise ContractError("O3a coincidence whitening context is incomplete")
    clean = extract_clean_subwindow(whitened, gps, gps + duration)
    clean_values = np.ascontiguousarray(clean.value, dtype=np.float64)
    if clean_values.shape != (duration * sample_rate,) or not np.isfinite(clean_values).all():
        raise ContractError("O3a coincidence clean window is invalid")
    representation = contract["representation"]
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
    image_sha = hashlib.sha256(image.tobytes()).hexdigest()
    if list(image.shape) != representation["image_shape"]:
        raise ContractError("O3a coincidence image shape changed")
    return {
        "detector": detector,
        "gps_start": gps,
        "availability": "AVAILABLE",
        "image": image,
        "clean": clean_values,
        "image_sha256": image_sha,
        "clean_window_sha256": hashlib.sha256(clean_values.tobytes()).hexdigest(),
        "raw_context_sha256": hashlib.sha256(raw.tobytes()).hexdigest(),
        "context_sources": plan["sources"],
    }


def _pin_new_frames(
    plans: list[dict[str, Any]], *, run_dir: Path, contract: Mapping[str, Any],
    allow_download: bool,
) -> dict[str, Any]:
    """Pin inventory-only partner bytes before any coincidence statistic."""
    unknown: dict[tuple[str, str], dict[str, Any]] = {}
    for plan in plans:
        for source in plan["sources"]:
            if source["sha256"] is None:
                key = str(source["detector"]), str(source["filename"])
                unknown[key] = source
    receipt_path = run_dir / "new_source_frame_receipt.json"
    if receipt_path.exists():
        receipt = _sealed(receipt_path, "receipt_digest")
        if set(receipt["frames"]) != {"|".join(key) for key in unknown}:
            raise ContractError("O3a coincidence new-source receipt frame set changed")
    else:
        if not allow_download:
            raise ContractError("O3a coincidence new-source receipt is missing")
        frames: dict[str, dict[str, Any]] = {}
        for key, source in sorted(unknown.items()):
            target = run_dir / "transient_raw" / key[0] / key[1]
            frame = {**source, "duration_s": int(source["gps_end"]) - int(source["gps_start"])}
            result = _download_frame(
                frame=frame, target=target,
                retries=int(contract["execution"]["download_retries"]),
                expected_sha256=None,
            )
            frames["|".join(key)] = {
                "sha256": result["sha256"],
                "size_bytes": result["size_bytes"],
                "url": source["url"],
            }
        body = {"status": "PINNED_O3A_COINCIDENCE_NEW_RAW", "frames": frames}
        receipt = {**body, "receipt_digest": canonical_json_sha256(body)}
        _atomic_json(receipt_path, receipt)
    for plan in plans:
        for source in plan["sources"]:
            if source["sha256"] is None:
                key = f"{source['detector']}|{source['filename']}"
                pinned = receipt["frames"][key]
                if pinned["url"] != source["url"]:
                    raise ContractError("O3a coincidence new raw URL changed")
                source["sha256"] = pinned["sha256"]
                source["size_bytes"] = pinned["size_bytes"]
    return receipt


def _batch_plan_rows(
    seeds: Sequence[Mapping[str, Any]], plans: Mapping[tuple[str, int], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    needed: dict[tuple[str, int], dict[str, Any]] = {}
    for seed in seeds:
        detector, gps = str(seed["detector"]), int(seed["gps_start"])
        for key in ((detector, gps), ("L1" if detector == "H1" else "H1", gps)):
            plan = plans[key]
            if plan["availability"] == "SOURCE_COVERED":
                needed[key] = {"detector": key[0], "gps_start": key[1], "context_sources": plan["sources"]}
    return [needed[key] for key in sorted(needed, key=lambda x: (x[1], x[0]))]


def _measure_batch(
    *, seeds: Sequence[Mapping[str, Any]],
    plan_rows: Sequence[Mapping[str, Any]],
    plan_map: Mapping[tuple[str, int], Mapping[str, Any]],
    seed_map: Mapping[tuple[str, int], Mapping[str, Any]],
    cache_root: Path, contract: Mapping[str, Any], scorer: Any,
    executor: ProcessPoolExecutor,
) -> list[dict[str, Any]]:
    import torch

    prepared_rows = list(executor.map(
        _read_context,
        [(plan_map[(str(row["detector"]), int(row["gps_start"]))], str(cache_root), contract)
         for row in plan_rows],
    ))
    available = [row for row in prepared_rows if row["availability"] == "AVAILABLE"]
    scored_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    if available:
        tokens = scorer.encode_patch_tokens([row["image"] for row in available])
        if (
            tokens.ndim != 3
            or tokens.shape[0] != len(available)
            or tokens.shape[1] != int(contract["representation"]["patch_tokens_per_image"])
            or tokens.shape[2] != int(contract["representation"]["embedding_dimension"])
            or not bool(torch.isfinite(tokens).all())
        ):
            raise ContractError("O3a coincidence patch tokens are invalid")
        scored = scorer.score_patch_tokens(
            tokens, float(contract["scoring"]["temporary_threshold"]),
            output_mode="full",
        )
        if len(scored) != len(available):
            raise ContractError("O3a coincidence scorer output batch is incomplete")
        for row, result in zip(available, scored, strict=True):
            key = str(row["detector"]), int(row["gps_start"])
            score = float(result["novelty_score"])
            top_k = np.asarray(result["top_k_indices"], dtype=np.int32)
            if not np.isfinite(score) or top_k.shape != (int(contract["scoring"]["top_k"]),):
                raise ContractError("O3a coincidence scorer produced invalid score or top-K")
            scored_by_key[key] = {
                **row,
                "native_score": score,
                "top_k_indices": top_k,
            }
    for key, row in scored_by_key.items():
        seed = seed_map.get(key)
        if seed is None:
            continue
        if (
            row["image_sha256"] != seed["image_sha256"]
            or row["clean_window_sha256"] != seed["clean_window_sha256"]
            or row["raw_context_sha256"] != seed["raw_context_sha256"]
            or abs(row["native_score"] - float(seed["native_score"]))
            > float(contract["scoring"]["max_seed_score_delta"])
        ):
            raise ContractError("O3a coincidence frozen seed replay changed")
    unavailable = {
        (str(row["detector"]), int(row["gps_start"])): str(row["availability"])
        for row in prepared_rows if row["availability"] != "AVAILABLE"
    }
    events: list[dict[str, Any]] = []
    for seed in seeds:
        detector, gps = str(seed["detector"]), int(seed["gps_start"])
        key = detector, gps
        opposite = "L1" if detector == "H1" else "H1"
        partner_key = opposite, gps
        candidate = scored_by_key.get(key)
        if candidate is None:
            raise ContractError("O3a coincidence seed replay missing")
        delta = abs(candidate["native_score"] - float(seed["native_score"]))
        base = {
            "detector": detector,
            "gps_start": gps,
            "partner": opposite,
            "population": "primary" if seed["native_class"] == "ROBUST" else "diagnostic",
            "seed_native_class": seed["native_class"],
            "seed_identity_digest": seed["identity_digest"],
            "seed_native_score": seed["native_score"],
            "seed_replay_score": candidate["native_score"],
            "seed_score_delta": delta,
            "seed_image_sha256": candidate["image_sha256"],
            "seed_clean_window_sha256": candidate["clean_window_sha256"],
            "seed_raw_context_sha256": candidate["raw_context_sha256"],
            "seed_top_k_indices": candidate["top_k_indices"].tolist(),
            "partner_class_consulted": False,
        }
        if plan_map[partner_key]["availability"] != "SOURCE_COVERED" or partner_key in unavailable:
            events.append({
                **base,
                "measurement_status": "PARTNER_DATA_UNAVAILABLE",
                "unavailable_reason": unavailable.get(
                    partner_key, plan_map[partner_key]["availability"]
                ),
                "cc_onsource": None,
                "cc_null_values": [],
                "cc_null_max": None,
                "n_null": 0,
                "per_event_null_exceeded": None,
            })
            continue
        partner = scored_by_key.get(partner_key)
        if partner is None:
            raise ContractError("O3a coincidence partner replay missing")
        physical = measure_physical_arrays(
            candidate["clean"], partner["clean"],
            candidate["top_k_indices"], partner["top_k_indices"],
            measurement=contract["measurement"],
        )
        events.append({
            **base,
            "measurement_status": "MEASURED",
            "partner_image_sha256": partner["image_sha256"],
            "partner_clean_window_sha256": partner["clean_window_sha256"],
            "partner_raw_context_sha256": partner["raw_context_sha256"],
            "partner_top_k_indices": partner["top_k_indices"].tolist(),
            **physical,
        })
    return events


def _shard_path(run_dir: Path, number: int) -> Path:
    return run_dir / "event_shards" / f"batch_{number:05d}.json"


def _read_shard(
    run_dir: Path, number: int, seeds: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any], run_key: str,
) -> list[dict[str, Any]] | None:
    path = _shard_path(run_dir, number)
    if not path.exists():
        return None
    shard = _sealed(path, "shard_digest")
    rows = shard.get("rows")
    if (
        shard.get("status") != "PASS_O3A_COINCIDENCE_EVENT_SHARD"
        or shard.get("contract_digest") != contract["contract_digest"]
        or shard.get("run_key") != run_key
        or shard.get("batch_index") != number
        or shard.get("seed_digest") != canonical_json_sha256(list(seeds))
        or not isinstance(rows, list)
        or len(rows) != len(seeds)
    ):
        raise ContractError("O3a coincidence event shard changed")
    for seed, event in zip(seeds, rows, strict=True):
        if (
            not isinstance(event, dict)
            or event.get("detector") != seed["detector"]
            or event.get("gps_start") != seed["gps_start"]
            or event.get("seed_identity_digest") != seed["identity_digest"]
            or event.get("seed_native_score") != seed["native_score"]
            or event.get("seed_native_class") != seed["native_class"]
            or event.get("partner_class_consulted") is not False
            or event.get("population") != (
                "primary" if seed["native_class"] == "ROBUST" else "diagnostic"
            )
            or "partner_class" in event
            or "partner_native_class" in event
        ):
            raise ContractError("O3a coincidence event shard seed changed")
        if event["measurement_status"] == "MEASURED":
            null = event.get("cc_null_values")
            if (
                not isinstance(null, list)
                or not 1 <= len(null) <= len(contract["measurement"]["null_shifts_s"])
                or event.get("n_null") != len(null)
                or not np.isfinite([float(event["cc_onsource"]), *map(float, null)]).all()
                or event.get("cc_null_max") != max(null)
                or event.get("cc_null_mean") != float(np.mean(null))
                or event.get("per_event_null_exceeded")
                is not (float(event["cc_onsource"]) > float(event["cc_null_max"]))
            ):
                raise ContractError("O3a coincidence measured null ledger changed")
        elif event["measurement_status"] == "PARTNER_DATA_UNAVAILABLE":
            if (
                event.get("cc_onsource") is not None
                or event.get("cc_null_values") != []
                or event.get("cc_null_max") is not None
                or event.get("n_null") != 0
                or event.get("per_event_null_exceeded") is not None
                or not event.get("unavailable_reason")
            ):
                raise ContractError("O3a coincidence unavailable measurement changed")
        else:
            raise ContractError("O3a coincidence measurement status changed")
    return rows


def _write_shard(
    run_dir: Path, number: int, seeds: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any], run_key: str,
) -> None:
    body = {
        "status": "PASS_O3A_COINCIDENCE_EVENT_SHARD",
        "contract_digest": contract["contract_digest"],
        "run_key": run_key,
        "batch_index": number,
        "seed_digest": canonical_json_sha256(list(seeds)),
        "rows": list(rows),
    }
    _atomic_json(_shard_path(run_dir, number), {**body, "shard_digest": canonical_json_sha256(body)})


def _batch_seed_rows(seeds: Sequence[Mapping[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [
        [dict(row) for row in seeds[start : start + size]]
        for start in range(0, len(seeds), size)
    ]


def _event_summary(
    primary: Sequence[Mapping[str, Any]], diagnostic: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    threshold = primary_null_threshold(primary, measurement=contract["measurement"])
    output: dict[str, list[dict[str, Any]]] = {"primary": [], "diagnostic": []}
    summary: dict[str, Any] = {"primary_null_p99": threshold}
    for name, rows in (("primary", primary), ("diagnostic", diagnostic)):
        for source in rows:
            row = dict(source)
            row["exceeds_primary_threshold"] = (
                bool(float(row["cc_onsource"]) > threshold)
                if row["measurement_status"] == "MEASURED" else None
            )
            output[name].append(row)
        measured = [r for r in output[name] if r["measurement_status"] == "MEASURED"]
        summary[name] = {
            "seed_total": len(rows),
            "measured": len(measured),
            "partner_data_unavailable": len(rows) - len(measured),
            "per_event_null_exceeded": sum(bool(r["per_event_null_exceeded"]) for r in measured),
            "primary_threshold_exceeded": sum(bool(r["exceeds_primary_threshold"]) for r in measured),
        }
    return summary, output["primary"], output["diagnostic"]


def _raw_receipt(plans: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for plan in plans:
        for source in plan["sources"]:
            key = str(source["detector"]), str(source["filename"])
            row = {k: source[k] for k in (
                "detector", "filename", "gps_start", "gps_end", "url", "sha256", "size_bytes"
            )}
            if not isinstance(row["sha256"], str) or not isinstance(row["size_bytes"], int):
                raise ContractError("O3a coincidence raw source is not pinned")
            if key in by_key and by_key[key] != row:
                raise ContractError("O3a coincidence raw receipt diverges")
            by_key[key] = row
    return [by_key[key] for key in sorted(by_key)]


def _replace_progress(path: Path, *, completed: int, total: int, status: str) -> None:
    """Progress is mutable bookkeeping, never evidence or outcome-bearing."""
    body = {
        "status": status,
        "completed_seeds": completed,
        "total_seeds": total,
        "outcomes_disclosed": False,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _aggregate_shards(
    *, run_dir: Path, seed_batches: Sequence[Sequence[Mapping[str, Any]]],
    contract: Mapping[str, Any], run_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    primary: list[dict[str, Any]] = []
    diagnostic: list[dict[str, Any]] = []
    for number, batch in enumerate(seed_batches):
        rows = _read_shard(run_dir, number, batch, contract, run_key)
        if rows is None:
            raise ContractError("O3a coincidence event shards are incomplete")
        for row in rows:
            if row["population"] == "primary":
                primary.append(row)
            elif row["population"] == "diagnostic":
                diagnostic.append(row)
            else:
                raise ContractError("O3a coincidence event shard population changed")
    expected = contract["population"]["exact_counts"]
    if len(primary) != expected["primary"]["total"] or len(diagnostic) != expected["diagnostic"]["total"]:
        raise ContractError("O3a coincidence event population incomplete")
    return primary, diagnostic


def _finish(
    *, run_dir: Path, preflight: Mapping[str, Any], plans: Sequence[Mapping[str, Any]],
    seed_batches: Sequence[Sequence[Mapping[str, Any]]], contract: Mapping[str, Any],
    run_key: str,
) -> dict[str, Any]:
    primary_raw, diagnostic_raw = _aggregate_shards(
        run_dir=run_dir, seed_batches=seed_batches, contract=contract, run_key=run_key,
    )
    event_summary, primary, diagnostic = _event_summary(primary_raw, diagnostic_raw, contract)
    receipt = _raw_receipt(plans)
    outputs: dict[str, dict[str, Any]] = {}
    for name, rows, filename in (
        ("primary", primary, "native_coincidence_robust.jsonl"),
        ("diagnostic", diagnostic, "native_coincidence_ambiguous.jsonl"),
        ("raw_source_receipt", receipt, "raw_source_receipt.jsonl"),
    ):
        path = run_dir / filename
        _atomic_jsonl(path, rows)
        outputs[name] = {
            "filename": filename,
            "row_total": len(rows),
            "sha256": file_sha256(path),
            "row_digest": canonical_json_sha256(rows),
        }
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_COINCIDENCE",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "source_plan_pinned_digest": canonical_json_sha256(list(plans)),
        "runtime_environment_digest": contract["runtime_environment_digest"],
        "population": contract["population"],
        "measurement": contract["measurement"],
        "pre_registered_limitation": contract["pre_registered_limitation"],
        "event_summary": event_summary,
        "outputs": outputs,
        "gates": {
            "duplicate_seed_detector_gps": 0,
            "partner_class_reads": 0,
            "background_measurements": 0,
            "seed_image_or_score_mismatches": 0,
            "unaccounted_seeds": 0,
            "transient_cache_empty": True,
        },
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "native_coincidence_summary.json", summary)
    return summary


def run_native_coincidence(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    """Measure the frozen diagnostic statistic in resumable verified shards."""
    import fcntl

    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    if runtime["runtime_environment"]["environment_digest"] != contract["runtime_environment_digest"]:
        raise ContractError("O3a coincidence canonical runtime changed")
    preflight, plans, seeds = _preflight_details(
        root=root, external_root=external_root, contract=contract,
    )
    run_key = _run_key(contract, preflight)
    run_dir = external_root / f"native_coincidence_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "run.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError("another O3a coincidence process owns this run key") from exc
        try:
            if (run_dir / "failure.json").exists():
                raise ContractError("O3a coincidence failure requires review")
            summary_path = run_dir / "native_coincidence_summary.json"
            if summary_path.exists():
                return verify_native_coincidence(root=root, external_root=external_root)
            preflight_path = run_dir / "preflight.json"
            if preflight_path.exists() and _read_json(preflight_path) != preflight:
                raise ContractError("O3a coincidence preflight changed")
            _atomic_json(preflight_path, preflight)
            new_source = _pin_new_frames(
                plans, run_dir=run_dir, contract=contract, allow_download=True,
            )
            plan_map = {(p["detector"], p["gps_start"]): p for p in plans}
            seed_map = {(s["detector"], s["gps_start"]): s for s in seeds}
            size = int(contract["execution"]["batch_size"])
            seed_batches = _batch_seed_rows(seeds, size)
            plan_batches = [_batch_plan_rows(batch, plan_map) for batch in seed_batches]
            last_use, sources = _frame_dependency_order(plan_batches)
            cache_root = run_dir / "transient_raw"
            known: dict[tuple[str, str], tuple[int, int]] = {}
            index = _sealed(root / INDEX_REL, "artifact_digest")
            index_dir = external_root / f"native_index_{index['run_key']}"
            scorer = _load_scorer(
                run_dir=run_dir, index_dir=index_dir, index=index, contract=contract,
            )
            completed = sum(
                len(batch) for number, batch in enumerate(seed_batches)
                if _read_shard(run_dir, number, batch, contract, run_key) is not None
            )
            _replace_progress(
                run_dir / "progress.json", completed=completed,
                total=len(seeds), status="MEASURING",
            )
            context = mp.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=int(contract["execution"]["workers"]),
                mp_context=context,
            ) as executor:
                for number, (batch, plan_batch) in enumerate(zip(seed_batches, plan_batches, strict=True)):
                    if _read_shard(run_dir, number, batch, contract, run_key) is not None:
                        _evict_finished_frames(
                            run_dir=run_dir, batch_index=number, last_use=last_use,
                            sources=sources, known=known,
                        )
                        continue
                    if shutil.disk_usage(run_dir).free < int(contract["execution"]["free_space_reserve_bytes"]):
                        raise InfrastructureError("O3a coincidence raw-cache free-space reserve exhausted")
                    _prepare_batch_sources(
                        batch=plan_batch, run_dir=run_dir, contract=contract, known=known,
                    )
                    rows = _measure_batch(
                        seeds=batch, plan_rows=plan_batch, plan_map=plan_map,
                        seed_map=seed_map, cache_root=cache_root,
                        contract=contract, scorer=scorer, executor=executor,
                    )
                    _write_shard(run_dir, number, batch, rows, contract, run_key)
                    completed += len(batch)
                    _replace_progress(
                        run_dir / "progress.json", completed=completed,
                        total=len(seeds), status="MEASURING",
                    )
                    _evict_finished_frames(
                        run_dir=run_dir, batch_index=number, last_use=last_use,
                        sources=sources, known=known,
                    )
            if completed != len(seeds) or any(p.is_file() for p in cache_root.rglob("*")):
                raise ContractError("O3a coincidence work or transient cache incomplete")
            if new_source["status"] != "PINNED_O3A_COINCIDENCE_NEW_RAW":
                raise ContractError("O3a coincidence new raw receipt changed")
            summary = _finish(
                run_dir=run_dir, preflight=preflight, plans=plans,
                seed_batches=seed_batches, contract=contract, run_key=run_key,
            )
            _replace_progress(
                run_dir / "progress.json", completed=completed,
                total=len(seeds), status="PASS_COMPLETE",
            )
            return summary, run_dir
        except BaseException as exc:
            if not isinstance(exc, ContractError) or "failure requires review" not in str(exc):
                body = {
                    "status": "FAILED_O3A_NATIVE_COINCIDENCE",
                    "contract_digest": contract["contract_digest"],
                    "run_key": run_key,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                _atomic_json(
                    run_dir / "failure.json",
                    {**body, "artifact_digest": canonical_json_sha256(body)},
                )
            raise
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def archive_infrastructure_failure(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> Path:
    """Archive verified transport/storage failure before same-key shard resume."""
    import fcntl

    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root)
    preflight, plans, seeds = _preflight_details(
        root=root, external_root=external_root, contract=contract,
    )
    run_key = _run_key(contract, preflight)
    run_dir = external_root / f"native_coincidence_{run_key}"
    with (run_dir / "run.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError("O3a coincidence run is still active") from exc
        try:
            failure = _sealed(run_dir / "failure.json", "artifact_digest")
            if (
                failure.get("status") != "FAILED_O3A_NATIVE_COINCIDENCE"
                or failure.get("contract_digest") != contract["contract_digest"]
                or failure.get("run_key") != run_key
                or failure.get("error_type") != "InfrastructureError"
                or _read_json(run_dir / "preflight.json") != preflight
            ):
                raise ContractError("O3a coincidence failure is not verified infrastructure-only")
            batches = _batch_seed_rows(seeds, int(contract["execution"]["batch_size"]))
            complete = 0
            for number, batch in enumerate(batches):
                if _read_shard(run_dir, number, batch, contract, run_key) is not None:
                    complete += 1
            if complete and not (run_dir / "new_source_frame_receipt.json").exists():
                raise ContractError("O3a coincidence completed shards lack pinned new raw")
            if (run_dir / "new_source_frame_receipt.json").exists():
                _pin_new_frames(plans, run_dir=run_dir, contract=contract, allow_download=False)
            archive = run_dir / "failure_history" / f"failure_{failure['artifact_digest']}.json"
            if archive.exists():
                raise ContractError("O3a coincidence failure was already archived")
            archive.parent.mkdir(parents=True, exist_ok=True)
            os.replace(run_dir / "failure.json", archive)
            if _read_json(archive) != failure:
                raise ContractError("O3a coincidence failure archive changed")
            return archive
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def verify_native_coincidence(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    """Independently rebuild population/threshold/output ledgers from shards."""
    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    if runtime["runtime_environment"]["environment_digest"] != contract["runtime_environment_digest"]:
        raise ContractError("O3a coincidence canonical runtime changed")
    preflight, plans, seeds = _preflight_details(
        root=root, external_root=external_root, contract=contract,
    )
    run_key = _run_key(contract, preflight)
    run_dir = external_root / f"native_coincidence_{run_key}"
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a coincidence failure evidence is present")
    if _read_json(run_dir / "preflight.json") != preflight:
        raise ContractError("O3a coincidence preflight replay changed")
    _pin_new_frames(plans, run_dir=run_dir, contract=contract, allow_download=False)
    if any(p.is_file() for p in (run_dir / "transient_raw").rglob("*")):
        raise ContractError("O3a coincidence transient raw cache is not empty")
    seed_batches = _batch_seed_rows(seeds, int(contract["execution"]["batch_size"]))
    primary_raw, diagnostic_raw = _aggregate_shards(
        run_dir=run_dir, seed_batches=seed_batches, contract=contract, run_key=run_key,
    )
    event_summary, expected_primary, expected_diagnostic = _event_summary(
        primary_raw, diagnostic_raw, contract,
    )
    expected_receipt = _raw_receipt(plans)
    summary = _sealed(run_dir / "native_coincidence_summary.json", "artifact_digest")
    if (
        summary.get("status") != "PASS_COMPLETE_O3A_NATIVE_COINCIDENCE"
        or summary.get("run_key") != run_key
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("preflight_digest") != preflight["preflight_digest"]
        or summary.get("source_plan_pinned_digest") != canonical_json_sha256(plans)
        or summary.get("event_summary") != event_summary
        or summary.get("measurement") != contract["measurement"]
        or summary.get("population") != contract["population"]
        or summary.get("pre_registered_limitation") != contract["pre_registered_limitation"]
        or summary.get("gates") != {
            "duplicate_seed_detector_gps": 0,
            "partner_class_reads": 0,
            "background_measurements": 0,
            "seed_image_or_score_mismatches": 0,
            "unaccounted_seeds": 0,
            "transient_cache_empty": True,
        }
    ):
        raise ContractError("O3a coincidence summary changed")
    for name, expected in (
        ("primary", expected_primary),
        ("diagnostic", expected_diagnostic),
        ("raw_source_receipt", expected_receipt),
    ):
        spec = summary["outputs"][name]
        path = run_dir / spec["filename"]
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if (
            rows != expected
            or spec["row_total"] != len(expected)
            or spec["sha256"] != file_sha256(path)
            or spec["row_digest"] != canonical_json_sha256(expected)
        ):
            raise ContractError(f"O3a coincidence {name} output changed")
    compact = {
        "schema_version": 1,
        "status": "PASS_VERIFIED_O3A_NATIVE_COINCIDENCE",
        "contract_digest": contract["contract_digest"],
        "run_key": run_key,
        "run_artifact_digest": summary["artifact_digest"],
        "summary_sha256": file_sha256(run_dir / "native_coincidence_summary.json"),
        "external_run_dir_wsl": str(run_dir),
        "event_summary": event_summary,
        "outputs": summary["outputs"],
        "scientific_boundary": contract["scientific_boundary"],
        "pre_registered_limitation": contract["pre_registered_limitation"],
    }
    _atomic_json(
        root / COMPACT_REL,
        {**compact, "artifact_digest": canonical_json_sha256(compact)},
    )
    return summary, run_dir


__all__ = [
    "archive_infrastructure_failure",
    "build_contract",
    "freeze_contract",
    "load_contract",
    "measure_physical_arrays",
    "primary_null_threshold",
    "plan_sources",
    "preflight_sources",
    "run_native_coincidence",
    "split_seed_populations",
    "verify_native_coincidence",
]
