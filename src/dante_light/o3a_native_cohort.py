"""Freeze the detector-aware O3a native-index cohort fail closed.

The selector reads only ``detector``, integer ``gps_start``, and the already
frozen primary-candidate boolean.  It never reads a primary score, class, or
native outcome.  Exact 40 s raw contexts are retained only for accepted rows
so the later native-index build can replay preprocessing without retaining
the complete O3a frame archive.
"""

from __future__ import annotations

import bisect
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import (
    ROOT,
    RUNTIME_REL,
    load_runtime_contract,
)
from src.dante_light.o3a_initial_calibration_acceptance import (
    load_acceptance_contract,
)
from src.dante_light.o3a_primary_scan import (
    CONTRACT_REL as PRIMARY_CONTRACT_REL,
    FrameGroupReader,
    InfrastructureError,
    _download_frame,
    _retained_raw_map,
    verify_primary_scan,
)
from src.dante_light.o3a_raw_acquisition import (
    INVENTORY_REL,
    _cover_interval,
    _inventory_frames,
    load_source_inventory,
)
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_light.o3a_scale_adequacy import (
    STAGE_CONTRACT_REL,
    load_stage_contract,
)


SCHEMA_VERSION = 1
CONTRACT_REL = "config/dante_o3a_native_cohort_v1.json"
COMPACT_PRIMARY_REL = "artifacts/dante_light/o3a_native_v1/primary_scan.json"
COMPACT_OUTPUT_REL = "artifacts/dante_light/o3a_native_v1/native_cohort.json"
O4A_REFERENCE_REL = "config/dante_o4a_corrected_native_v1.json"
VETO_SOURCE_REL = "src/pipeline_v3_multiscale/micro_mdc_multiscale.py"
PREPROCESSOR_REL = "src/core/preprocessor.py"
IMPLEMENTATION_REL = "src/dante_light/o3a_native_cohort.py"
FREEZE_ENTRYPOINT_REL = "scripts/freeze_dante_o3a_native_cohort.py"
RUN_ENTRYPOINT_REL = "scripts/run_dante_o3a_native_cohort.py"
DEFAULT_PRIMARY_EXTERNAL_ROOT = Path(
    "/mnt/e/dante_cache/dante_light/o3a_native_v1"
)
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")
DEFAULT_RAW_ROOT = Path("/mnt/e/o3a")
DEFAULT_WORKERS = 8
DEFAULT_QUALITY_BATCH_SIZE = 32
DEFAULT_DOWNLOAD_RETRIES = 5
DEFAULT_RESERVE_BYTES = 16 * 1024**3
SAMPLE_RATE_HZ = 4096
ANALYSIS_DURATION_S = 32
WHITENING_PAD_S = 4


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _atomic_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            )
    os.replace(temporary, path)


def _atomic_npy(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.save(stream, values, allow_pickle=False)
    os.replace(temporary, path)


def _binding(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    path = root / relative
    return {
        "path": relative,
        "sha256": file_sha256(path),
        **extra,
    }


def _implementation_sources(root: Path) -> dict[str, str]:
    return {
        relative: file_sha256(root / relative)
        for relative in (
            IMPLEMENTATION_REL,
            FREEZE_ENTRYPOINT_REL,
            RUN_ENTRYPOINT_REL,
        )
    }


def _validated_compact_primary(root: Path) -> dict[str, Any]:
    value = _read_json(root / COMPACT_PRIMARY_REL)
    body = dict(value)
    declared = body.pop("artifact_digest", None)
    if (
        value.get("status") != "PASS_COMPLETE_O3A_PRIMARY_SCAN"
        or declared != canonical_json_sha256(body)
        or int(value.get("invalid_or_silent_drop_count", -1)) != 0
    ):
        raise ContractError("compact O3a primary scan is not verified")
    return value


def build_cohort_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Build the explicit O3a cohort contract from frozen parent evidence."""

    root = root.resolve()
    stage = load_stage_contract(root=root)
    runtime = load_runtime_contract(root=root)
    primary = _validated_compact_primary(root)
    reference = _read_json(root / O4A_REFERENCE_REL)
    firewall = stage["author_decisions"]["population_firewall"]
    veto_sha256 = file_sha256(root / VETO_SOURCE_REL)
    preprocessor_sha256 = file_sha256(root / PREPROCESSOR_REL)
    if (
        reference.get("contract_digest")
        != "66f5796aecdea5a1009257a96a351e960c0801eadb60dc40bbf01bdfa74378c2"
        or reference["preprocessing"]["excess_power_veto"]["source_path"]
        != VETO_SOURCE_REL
        or reference["preprocessing"]["excess_power_veto"]["source_sha256"]
        != veto_sha256
        or reference["references"]["preprocessor"]["path"]
        != PREPROCESSOR_REL
        or reference["references"]["preprocessor"]["sha256"]
        != preprocessor_sha256
    ):
        raise ContractError("corrected-O4a cohort method reference changed")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_NATIVE_COHORT_V1",
        "run": "O3A",
        "parents": {
            "approved_stage_contract": _binding(
                root,
                STAGE_CONTRACT_REL,
                contract_digest=stage["contract_digest"],
            ),
            "primary_scan_contract": _binding(
                root,
                str(PRIMARY_CONTRACT_REL),
                contract_digest=primary["contract_digest"],
            ),
            "primary_scan_compact_evidence": _binding(
                root,
                COMPACT_PRIMARY_REL,
                run_key=primary["run_key"],
                artifact_digest=primary["artifact_digest"],
                database_sha256=primary["database"]["sha256"],
            ),
            "source_inventory": _binding(root, INVENTORY_REL),
            "canonical_runtime": _binding(
                root,
                RUNTIME_REL,
                contract_digest=runtime["contract_digest"],
                environment_digest=runtime["runtime_environment"][
                    "environment_digest"
                ],
            ),
            "corrected_o4a_method_reference": _binding(
                root,
                O4A_REFERENCE_REL,
                contract_digest=reference["contract_digest"],
            ),
        },
        "selection": {
            "detectors": ["H1", "L1"],
            "target_rows_per_detector": int(
                firewall["index_cohort_rows_per_detector"]
            ),
            "identity_unit": "detector_plus_integer_32s_analysis_window_start",
            "priority_algorithm": (
                "sha256(stage_contract_digest|detector|integer_gps_start)"
            ),
            "selection_priority_contract": firewall["selection_priority"],
            "candidate_guard_cross_detector": bool(
                firewall["candidate_guard_cross_detector"]
            ),
            "candidate_guard_start_delta_s": int(
                firewall["candidate_guard_start_delta_s"]
            ),
            "candidate_guard_boundary": "INCLUSIVE",
            "direct_primary_candidates_excluded": True,
            "minimum_same_detector_separation_s": int(
                firewall["index_same_detector_minimum_separation_s"]
            ),
            "minimum_separation_boundary": "EXACT_DISTANCE_ALLOWED",
            "proposal_stream_limit": None,
            "selector_database_columns": [
                "detector",
                "gps_start",
                "is_candidate",
            ],
            "primary_score_or_class_read": False,
            "native_score_or_class_read": False,
        },
        "preprocessing": {
            "analysis_duration_s": ANALYSIS_DURATION_S,
            "whitening_pad_s": WHITENING_PAD_S,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "require_exact_symmetric_context": bool(
                firewall["complete_symmetric_context_required"]
            ),
            "require_finite_raw_context": True,
            "require_finite_clean_window": True,
            "whitening_before_analysis_crop": True,
            "preprocessor": {
                "source_path": PREPROCESSOR_REL,
                "source_sha256": preprocessor_sha256,
            },
            "excess_power_veto": {
                "parity_source_contract": O4A_REFERENCE_REL,
                "source_path": VETO_SOURCE_REL,
                "source_sha256": veto_sha256,
                "function": "excess_power_veto",
            },
        },
        "population_firewall": {
            "native_calibration_selected_after_index_manifest": True,
            "native_calibration_must_be_disjoint_from_index": bool(
                firewall["validation_population_disjoint"]
            ),
            "native_calibration_candidate_guard_start_delta_s": int(
                firewall["native_calibration_guard_start_delta_s"]
            ),
            "native_calibration_index_guard_interval_gap_s": int(
                firewall["native_calibration_guard_interval_gap_s"]
            ),
            "initial_calibration_is_seed_only_not_final_validation": True,
            "initial_calibration_membership_used_by_selector": False,
        },
        "execution": {
            "canonical_environment": "WSL_CUDA_RUNTIME_IDENTITY",
            "quality_workers": DEFAULT_WORKERS,
            "quality_batch_size": DEFAULT_QUALITY_BATCH_SIZE,
            "download_retries": DEFAULT_DOWNLOAD_RETRIES,
            "raw_frame_cache": "TRANSIENT_BATCH_ONLY",
            "accepted_context_format": "NUMPY_FLOAT64_NPY",
            "accepted_context_duration_s": (
                ANALYSIS_DURATION_S + 2 * WHITENING_PAD_S
            ),
            "atomic_outputs": True,
            "resume_unit": "QUALITY_PROPOSAL_SHARD",
        },
        "storage": {
            "primary_external_root_wsl": (
                "/mnt/e/dante_cache/dante_light/o3a_native_v1"
            ),
            "raw_root_wsl": "/mnt/e/o3a",
            "external_root_wsl": (
                "/mnt/e/dante_cache/dante_light/o3a_native_v1"
            ),
            "retained_scope": "ACCEPTED_40S_RAW_CONTEXTS_ONLY",
            "full_o3a_frame_archive_retained": False,
        },
        "gates": {
            "exact_rows_by_detector": {
                "H1": int(firewall["index_cohort_rows_per_detector"]),
                "L1": int(firewall["index_cohort_rows_per_detector"]),
            },
            "zero_candidate_or_guard_overlap": True,
            "zero_same_detector_separation_violation": True,
            "all_rows_pass_raw_quality": True,
            "all_context_and_source_hashes_verified": True,
            "no_native_embedding_or_score_computed": True,
            "fail_closed": True,
        },
        "implementation_sources": _implementation_sources(root),
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_cohort_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    body = dict(value)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("O3a native-cohort contract digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_O3A_NATIVE_COHORT_V1"
        or value.get("run") != "O3A"
        or value.get("implementation_sources") != _implementation_sources(root)
    ):
        raise ContractError("O3a native-cohort contract boundary changed")
    if value["selection"]["primary_score_or_class_read"] is not False:
        raise ContractError("O3a native-cohort selector is not outcome blind")
    if value["population_firewall"][
        "native_calibration_selected_after_index_manifest"
    ] is not True:
        raise ContractError("O3a downstream validation firewall changed")
    for reference in value["parents"].values():
        path = root / str(reference["path"])
        if not path.is_file() or file_sha256(path) != reference["sha256"]:
            raise ContractError(f"O3a native-cohort parent changed: {path}")
    veto = value["preprocessing"]["excess_power_veto"]
    if file_sha256(root / veto["source_path"]) != veto["source_sha256"]:
        raise ContractError("O3a native-cohort excess-power veto changed")
    preprocessor = value["preprocessing"]["preprocessor"]
    if (
        file_sha256(root / preprocessor["source_path"])
        != preprocessor["source_sha256"]
    ):
        raise ContractError("O3a native-cohort preprocessor changed")
    stage = load_stage_contract(root=root)
    firewall = stage["author_decisions"]["population_firewall"]
    if (
        value["parents"]["approved_stage_contract"]["contract_digest"]
        != stage["contract_digest"]
        or value["selection"]["target_rows_per_detector"]
        != firewall["index_cohort_rows_per_detector"]
        or value["selection"]["candidate_guard_start_delta_s"]
        != firewall["candidate_guard_start_delta_s"]
        or value["selection"]["minimum_same_detector_separation_s"]
        != firewall["index_same_detector_minimum_separation_s"]
    ):
        raise ContractError("O3a native-cohort approved parameters changed")
    return dict(value)


def load_cohort_contract(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_REL
    if not path.is_file():
        raise ContractError("O3a native-cohort contract is absent")
    return validate_cohort_contract(_read_json(path), root=root)


def write_cohort_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_cohort_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def proposal_priority(
    stage_contract_digest: str, detector: str, gps_start: int
) -> str:
    text = f"{stage_contract_digest}|{detector}|{int(gps_start)}"
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def _within_separation(
    value: int, sorted_values: Sequence[int], minimum_separation_s: int
) -> bool:
    position = bisect.bisect_left(sorted_values, value)
    return (
        position > 0
        and value - sorted_values[position - 1] < minimum_separation_s
    ) or (
        position < len(sorted_values)
        and sorted_values[position] - value < minimum_separation_s
    )


def select_native_proposals(
    identities: Iterable[tuple[str, int, bool]],
    *,
    stage_contract_digest: str,
    candidate_guard_delta_s: int,
    minimum_separation_s: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, int]]]:
    """Return the complete deterministic proposal stream for each detector."""

    rows = [(str(detector), int(gps), bool(candidate)) for detector, gps, candidate in identities]
    candidate_times = sorted({gps for _detector, gps, candidate in rows if candidate})
    pools: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    counts = {
        detector: {
            "eligible_seen": 0,
            "direct_candidate": 0,
            "candidate_guard": 0,
            "proposal_separation": 0,
        }
        for detector in ("H1", "L1")
    }
    for detector, gps, candidate in rows:
        if detector not in pools:
            raise ContractError(f"unexpected O3a detector: {detector}")
        counts[detector]["eligible_seen"] += 1
        if candidate:
            counts[detector]["direct_candidate"] += 1
            continue
        left = bisect.bisect_left(candidate_times, gps - candidate_guard_delta_s)
        if (
            left < len(candidate_times)
            and candidate_times[left] <= gps + candidate_guard_delta_s
        ):
            counts[detector]["candidate_guard"] += 1
            continue
        pools[detector].append(
            {
                "detector": detector,
                "gps_start": gps,
                "priority": proposal_priority(
                    stage_contract_digest, detector, gps
                ),
            }
        )
    proposals: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    for detector in ("H1", "L1"):
        accepted_gps: list[int] = []
        for row in sorted(
            pools[detector], key=lambda item: (item["priority"], item["gps_start"])
        ):
            gps = int(row["gps_start"])
            if _within_separation(gps, accepted_gps, minimum_separation_s):
                counts[detector]["proposal_separation"] += 1
                continue
            bisect.insort(accepted_gps, gps)
            proposals[detector].append(row)
    return proposals, counts


def _scan_identity_rows(database_path: Path) -> list[tuple[str, int, bool]]:
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT detector,gps_start,is_candidate FROM windows "
            "ORDER BY detector,gps_start"
        ).fetchall()
    finally:
        connection.close()
    return [
        (str(detector), int(gps), bool(candidate))
        for detector, gps, candidate in rows
    ]


def _raw_frame_rows(database_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT detector,gps_start,gps_end,filename,url,sha256,size_bytes "
            "FROM raw_frames ORDER BY detector,gps_start,filename"
        ).fetchall()
    finally:
        connection.close()
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for detector, start, end, filename, url, digest, size in rows:
        key = (str(detector), str(filename))
        if key in result:
            raise ContractError("O3a primary raw-frame ledger is duplicated")
        result[key] = {
            "detector": str(detector),
            "gps_start": int(start),
            "gps_end": int(end),
            "filename": str(filename),
            "url": str(url),
            "sha256": str(digest),
            "size_bytes": int(size),
        }
    return result


def _run_key(
    contract: Mapping[str, Any], *, environment_digest: str
) -> str:
    return canonical_json_sha256(
        {
            "stage": "o3a_detector_aware_native_cohort",
            "contract_digest": contract["contract_digest"],
            "primary_scan_artifact_digest": contract["parents"][
                "primary_scan_compact_evidence"
            ]["artifact_digest"],
            "runtime_environment_digest": environment_digest,
        }
    )


def _proposal_rows(
    proposals: Mapping[str, Sequence[Mapping[str, Any]]]
) -> Iterable[dict[str, Any]]:
    for detector in ("H1", "L1"):
        for rank, row in enumerate(proposals[detector]):
            yield {**dict(row), "proposal_rank": rank}


def _proposal_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return canonical_json_sha256(list(rows))


def _source_rows_for_context(
    *,
    detector: str,
    gps: int,
    frames: Sequence[Mapping[str, Any]],
    frame_starts: Sequence[int],
    raw_frame_rows: Mapping[tuple[str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    start = gps - WHITENING_PAD_S
    end = gps + ANALYSIS_DURATION_S + WHITENING_PAD_S
    position = max(0, bisect.bisect_right(frame_starts, start) - 1)
    nearby: list[Mapping[str, Any]] = []
    while position < len(frames) and int(frames[position]["gps_start"]) < end:
        if int(frames[position]["gps_end"]) > start:
            nearby.append(frames[position])
        position += 1
    coverage = _cover_interval(nearby, start, end)
    sources: list[dict[str, Any]] = []
    cursor = start
    for frame in coverage:
        key = (detector, str(frame["filename"]))
        ledger = raw_frame_rows.get(key)
        if ledger is None or (
            int(ledger["gps_start"]) != int(frame["gps_start"])
            or int(ledger["gps_end"]) != int(frame["gps_end"])
            or str(ledger["url"]) != str(frame["url"])
        ):
            raise ContractError("O3a cohort source-frame provenance mismatch")
        used_start = max(cursor, int(frame["gps_start"]))
        used_end = min(end, int(frame["gps_end"]))
        sources.append(
            {
                "detector": detector,
                "gps_start": int(frame["gps_start"]),
                "gps_end": int(frame["gps_end"]),
                "filename": str(frame["filename"]),
                "url": str(frame["url"]),
                "sha256": str(ledger["sha256"]),
                "size_bytes": int(ledger["size_bytes"]),
                "used_interval_gps": [used_start, used_end],
            }
        )
        cursor = used_end
    if cursor != end:
        raise ContractError("O3a cohort context coverage is incomplete")
    return sources


def preflight_native_cohort(
    *,
    root: Path = ROOT,
    primary_external_root: Path = DEFAULT_PRIMARY_EXTERNAL_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
) -> tuple[dict[str, Any], Path]:
    """Freeze proposals and storage/provenance checks without opening strain."""

    root = root.resolve()
    primary_external_root = primary_external_root.resolve()
    external_root = external_root.resolve()
    contract = load_cohort_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    run_key = _run_key(
        contract,
        environment_digest=runtime["runtime_environment"]["environment_digest"],
    )
    run_dir = external_root / f"native_cohort_{run_key}"
    preflight_path = run_dir / "preflight.json"
    if preflight_path.is_file():
        return (
            _load_preflight(
                contract=contract,
                run_dir=run_dir,
                run_key=run_key,
            ),
            run_dir,
        )
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root
    )
    compact = contract["parents"]["primary_scan_compact_evidence"]
    if (
        scan_summary["artifact_digest"] != compact["artifact_digest"]
        or scan_summary["database"]["sha256"] != compact["database_sha256"]
    ):
        raise ContractError("O3a cohort primary-scan binding changed")
    run_dir.mkdir(parents=True, exist_ok=True)
    database_path = scan_dir / "primary_scan.sqlite"
    identities = _scan_identity_rows(database_path)
    if len(identities) != int(scan_summary["window_total"]):
        raise ContractError("O3a cohort selector saw an incomplete scan")
    selection = contract["selection"]
    proposals, selection_counts = select_native_proposals(
        identities,
        stage_contract_digest=contract["parents"]["approved_stage_contract"][
            "contract_digest"
        ],
        candidate_guard_delta_s=int(selection["candidate_guard_start_delta_s"]),
        minimum_separation_s=int(
            selection["minimum_same_detector_separation_s"]
        ),
    )
    target = int(selection["target_rows_per_detector"])
    counts = {detector: len(proposals[detector]) for detector in ("H1", "L1")}
    if any(counts[detector] < target for detector in counts):
        raise ContractError("O3a native-cohort proposal capacity is insufficient")
    rows = list(_proposal_rows(proposals))
    proposal_path = run_dir / "proposals.jsonl"
    _atomic_jsonl(proposal_path, rows)
    inventory = load_source_inventory(root=root)
    frames_by_detector = {
        detector: _inventory_frames(inventory, detector)
        for detector in ("H1", "L1")
    }
    frame_starts_by_detector = {
        detector: [int(frame["gps_start"]) for frame in frames]
        for detector, frames in frames_by_detector.items()
    }
    frame_rows = _raw_frame_rows(database_path)
    required_frames: set[tuple[str, str]] = set()
    for row in rows:
        for source in _source_rows_for_context(
            detector=str(row["detector"]),
            gps=int(row["gps_start"]),
            frames=frames_by_detector[str(row["detector"])],
            frame_starts=frame_starts_by_detector[str(row["detector"])],
            raw_frame_rows=frame_rows,
        ):
            required_frames.add((source["detector"], source["filename"]))
    context_bytes = (
        2
        * target
        * (ANALYSIS_DURATION_S + 2 * WHITENING_PAD_S)
        * SAMPLE_RATE_HZ
        * np.dtype(np.float64).itemsize
    )
    external_root.mkdir(parents=True, exist_ok=True)
    free_bytes = shutil.disk_usage(external_root).free
    if free_bytes < context_bytes + reserve_bytes:
        raise ContractError("O3a native-cohort retained contexts do not fit")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_O3A_NATIVE_COHORT_PREFLIGHT",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "primary_scan_artifact_digest": scan_summary["artifact_digest"],
        "primary_scan_database_sha256": scan_summary["database"]["sha256"],
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
        "proposal_manifest": {
            "filename": proposal_path.name,
            "sha256": file_sha256(proposal_path),
            "row_digest": _proposal_digest(rows),
            "counts_by_detector": counts,
            "row_total": len(rows),
        },
        "selection_counts": selection_counts,
        "source_frame_ledger_count": len(frame_rows),
        "proposal_source_frame_count": len(required_frames),
        "retained_context_bytes_upper_bound": context_bytes,
        "reserve_bytes": reserve_bytes,
        "free_bytes_at_preflight": free_bytes,
        "scientific_boundary": {
            "strain_opened": False,
            "primary_score_or_class_read": False,
            "native_embedding_or_score_computed": False,
        },
    }
    value = {**body, "preflight_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "preflight.json", value)
    return value, run_dir


def _load_preflight(
    *, contract: Mapping[str, Any], run_dir: Path, run_key: str
) -> dict[str, Any]:
    value = _read_json(run_dir / "preflight.json")
    body = dict(value)
    declared = body.pop("preflight_digest", None)
    proposal_path = run_dir / str(value["proposal_manifest"]["filename"])
    rows = _read_jsonl(proposal_path)
    if (
        declared != canonical_json_sha256(body)
        or value.get("status") != "PASS_O3A_NATIVE_COHORT_PREFLIGHT"
        or value.get("run_key") != run_key
        or value.get("contract_digest") != contract["contract_digest"]
        or file_sha256(proposal_path) != value["proposal_manifest"]["sha256"]
        or _proposal_digest(rows) != value["proposal_manifest"]["row_digest"]
    ):
        raise ContractError("O3a native-cohort preflight changed")
    return value


def _quality_check_values(
    task: tuple[np.ndarray, int, str]
) -> dict[str, Any]:
    values, gps, detector = task
    from gwpy.timeseries import TimeSeries

    from src.core.preprocessor import extract_clean_subwindow, whiten_context
    from src.pipeline_v3_multiscale.micro_mdc_multiscale import excess_power_veto

    context_start = gps - WHITENING_PAD_S
    series = TimeSeries(
        values,
        t0=context_start,
        sample_rate=SAMPLE_RATE_HZ,
        name=f"{detector}:GWOSC-4KHZ_R1_STRAIN",
    )
    whitened, pad_info = whiten_context(
        series, gps, gps + ANALYSIS_DURATION_S, pad=WHITENING_PAD_S
    )
    tolerance = 1.0 / SAMPLE_RATE_HZ
    if (
        float(pad_info["effective_left"]) < WHITENING_PAD_S - tolerance
        or float(pad_info["effective_right"]) < WHITENING_PAD_S - tolerance
        or not np.isfinite(np.asarray(whitened.value)).all()
    ):
        raise ContractError("O3a native-cohort whitening context is incomplete")
    clean = extract_clean_subwindow(
        whitened, gps, gps + ANALYSIS_DURATION_S
    )
    clean_values = np.ascontiguousarray(clean.value, dtype=np.float64)
    if (
        clean_values.shape != (ANALYSIS_DURATION_S * SAMPLE_RATE_HZ,)
        or not np.isfinite(clean_values).all()
    ):
        raise ContractError("O3a native-cohort clean window is invalid")
    vetoed = bool(excess_power_veto(clean, sample_rate=SAMPLE_RATE_HZ))
    return {
        "quality_disposition": (
            "EXCESS_POWER_VETO" if vetoed else "PASS_CLEAN"
        ),
        "clean_window_sha256": hashlib.sha256(clean_values.tobytes()).hexdigest(),
        "clean_window_shape": list(clean_values.shape),
        "clean_window_dtype": str(clean_values.dtype),
    }


def _context_sources_and_values(
    *,
    row: Mapping[str, Any],
    frames: Sequence[Mapping[str, Any]],
    frame_starts: Sequence[int],
    frame_rows: Mapping[tuple[str, str], Mapping[str, Any]],
    retained: Mapping[tuple[str, str], Mapping[str, Any]],
    transient_root: Path,
    retries: int,
) -> tuple[np.ndarray, list[dict[str, Any]], list[Path]]:
    detector = str(row["detector"])
    gps = int(row["gps_start"])
    sources = _source_rows_for_context(
        detector=detector,
        gps=gps,
        frames=frames,
        frame_starts=frame_starts,
        raw_frame_rows=frame_rows,
    )
    paths: dict[str, Path] = {}
    downloaded: list[Path] = []
    frames: list[dict[str, Any]] = []
    inventory_lookup = {str(frame["filename"]): frame for frame in frames}
    for source in sources:
        frame = dict(inventory_lookup[source["filename"]])
        retained_row = retained.get((detector, source["filename"]))
        target = (
            Path(str(retained_row["path"]))
            if retained_row is not None
            else transient_root / detector / source["filename"]
        )
        result = _download_frame(
            frame=frame,
            target=target,
            retries=retries,
            expected_sha256=(
                str(retained_row["sha256"])
                if retained_row is not None
                else source["sha256"]
            ),
        )
        if (
            result["sha256"] != source["sha256"]
            or int(result["size_bytes"]) != int(source["size_bytes"])
        ):
            raise ContractError("O3a cohort downloaded frame identity changed")
        paths[source["filename"]] = target
        if retained_row is None:
            downloaded.append(target)
        frames.append(frame)
    with FrameGroupReader(frames, paths) as reader:
        values = reader.read(
            gps - WHITENING_PAD_S,
            gps + ANALYSIS_DURATION_S + WHITENING_PAD_S,
        )
    expected_shape = (
        (ANALYSIS_DURATION_S + 2 * WHITENING_PAD_S) * SAMPLE_RATE_HZ,
    )
    if values.shape != expected_shape or not np.isfinite(values).all():
        raise ContractError("O3a native-cohort raw context is invalid")
    return np.ascontiguousarray(values, dtype=np.float64), sources, downloaded


def _shard_path(run_dir: Path, row: Mapping[str, Any]) -> Path:
    return (
        run_dir
        / "quality_shards"
        / str(row["detector"])
        / f"{int(row['proposal_rank']):06d}_{row['priority']}.json"
    )


def _validate_shard(
    *, run_dir: Path, row: Mapping[str, Any], value: Mapping[str, Any]
) -> dict[str, Any]:
    body = dict(value)
    declared = body.pop("shard_digest", None)
    if (
        declared != canonical_json_sha256(body)
        or value.get("detector") != row["detector"]
        or int(value.get("gps_start", -1)) != int(row["gps_start"])
        or value.get("priority") != row["priority"]
        or int(value.get("proposal_rank", -1)) != int(row["proposal_rank"])
        or value.get("quality_disposition")
        not in {"PASS_CLEAN", "EXCESS_POWER_VETO"}
    ):
        raise ContractError("O3a native-cohort quality shard changed")
    if value["quality_disposition"] == "PASS_CLEAN":
        context = run_dir / str(value["raw_context"]["relative_path"])
        if (
            not context.is_file()
            or file_sha256(context) != value["raw_context"]["file_sha256"]
        ):
            raise ContractError("O3a native-cohort retained context changed")
    return dict(value)


def _write_quality_shard(
    *,
    run_dir: Path,
    row: Mapping[str, Any],
    quality: Mapping[str, Any],
    values: np.ndarray,
    sources: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    disposition = str(quality["quality_disposition"])
    raw_context: dict[str, Any] | None = None
    if disposition == "PASS_CLEAN":
        relative = Path("contexts") / str(row["detector"]) / (
            f"{int(row['gps_start'])}.npy"
        )
        context_path = run_dir / relative
        _atomic_npy(context_path, values)
        raw_context = {
            "relative_path": relative.as_posix(),
            "file_sha256": file_sha256(context_path),
            "values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
            "shape": list(values.shape),
            "dtype": str(values.dtype),
            "context_interval_gps": [
                int(row["gps_start"]) - WHITENING_PAD_S,
                int(row["gps_start"])
                + ANALYSIS_DURATION_S
                + WHITENING_PAD_S,
            ],
        }
    body = {
        "schema_version": SCHEMA_VERSION,
        "detector": str(row["detector"]),
        "gps_start": int(row["gps_start"]),
        "gps_end": int(row["gps_start"]) + ANALYSIS_DURATION_S,
        "priority": str(row["priority"]),
        "proposal_rank": int(row["proposal_rank"]),
        **dict(quality),
        "raw_context": raw_context,
        "context_sources": list(sources),
        "context_sources_digest": canonical_json_sha256(list(sources)),
    }
    value = {**body, "shard_digest": canonical_json_sha256(body)}
    _atomic_json(_shard_path(run_dir, row), value)
    return value


def _progress(
    run_dir: Path,
    *,
    status: str,
    checked: Mapping[str, int],
    proposal_counts: Mapping[str, int],
) -> None:
    _atomic_json(
        run_dir / "progress.json",
        {
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "checked_proposals_by_detector": dict(checked),
            "proposal_counts_by_detector": dict(proposal_counts),
            "candidate_or_quality_outcomes_disclosed": False,
        },
    )


def _execute_native_cohort_locked(
    *,
    root: Path = ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT,
    primary_external_root: Path = DEFAULT_PRIMARY_EXTERNAL_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    workers: int = DEFAULT_WORKERS,
    quality_batch_size: int = DEFAULT_QUALITY_BATCH_SIZE,
) -> tuple[dict[str, Any], Path]:
    """Execute the raw-quality freeze under the immutable proposal stream."""

    if workers < 1 or quality_batch_size < 1:
        raise ValueError("O3a native-cohort worker settings must be positive")
    root = root.resolve()
    raw_root = raw_root.resolve()
    primary_external_root = primary_external_root.resolve()
    external_root = external_root.resolve()
    contract = load_cohort_contract(root=root)
    if (
        workers != int(contract["execution"]["quality_workers"])
        or quality_batch_size
        != int(contract["execution"]["quality_batch_size"])
    ):
        raise ContractError("O3a native-cohort execution settings changed")
    runtime = load_runtime_contract(root=root, require_current=True)
    environment_digest = runtime["runtime_environment"]["environment_digest"]
    run_key = _run_key(contract, environment_digest=environment_digest)
    run_dir = external_root / f"native_cohort_{run_key}"
    preflight = _load_preflight(
        contract=contract, run_dir=run_dir, run_key=run_key
    )
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("O3a native-cohort failure artifact is present")
    summary_path = run_dir / "native_cohort_summary.json"
    if summary_path.is_file():
        verified, verified_dir = verify_native_cohort(
            root=root,
            primary_external_root=primary_external_root,
            external_root=external_root,
        )
        _atomic_json(root / COMPACT_OUTPUT_REL, verified)
        return verified, verified_dir
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root
    )
    if scan_summary["artifact_digest"] != preflight["primary_scan_artifact_digest"]:
        raise ContractError("O3a native-cohort primary scan changed")
    database_path = scan_dir / "primary_scan.sqlite"
    inventory = load_source_inventory(root=root)
    frames_by_detector = {
        detector: _inventory_frames(inventory, detector)
        for detector in ("H1", "L1")
    }
    frame_starts_by_detector = {
        detector: [int(frame["gps_start"]) for frame in frames]
        for detector, frames in frames_by_detector.items()
    }
    frame_rows = _raw_frame_rows(database_path)
    retained = _retained_raw_map(
        raw_root=raw_root,
        acceptance=load_acceptance_contract(root=root),
    )
    proposals = _read_jsonl(run_dir / "proposals.jsonl")
    proposal_by_detector = {
        detector: [row for row in proposals if row["detector"] == detector]
        for detector in ("H1", "L1")
    }
    target = int(contract["selection"]["target_rows_per_detector"])
    checked = {"H1": 0, "L1": 0}
    selected: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    vetoed = {"H1": 0, "L1": 0}
    transient_root = run_dir / "transient_raw"
    _progress(
        run_dir,
        status="RUNNING",
        checked=checked,
        proposal_counts=preflight["proposal_manifest"]["counts_by_detector"],
    )
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for detector in ("H1", "L1"):
                rows = proposal_by_detector[detector]
                offset = 0
                while offset < len(rows) and len(selected[detector]) < target:
                    row = rows[offset]
                    shard_path = _shard_path(run_dir, row)
                    if shard_path.is_file():
                        shard = _validate_shard(
                            run_dir=run_dir,
                            row=row,
                            value=_read_json(shard_path),
                        )
                        checked[detector] += 1
                        if shard["quality_disposition"] == "PASS_CLEAN":
                            selected[detector].append(shard)
                        else:
                            vetoed[detector] += 1
                        offset += 1
                        continue
                    batch = rows[offset : offset + quality_batch_size]
                    contexts: list[np.ndarray] = []
                    source_rows: list[list[dict[str, Any]]] = []
                    downloaded: list[Path] = []
                    batch_complete = False
                    try:
                        for batch_row in batch:
                            values, sources, paths = _context_sources_and_values(
                                row=batch_row,
                                frames=frames_by_detector[detector],
                                frame_starts=frame_starts_by_detector[detector],
                                frame_rows=frame_rows,
                                retained=retained,
                                transient_root=transient_root,
                                retries=int(contract["execution"]["download_retries"]),
                            )
                            contexts.append(values)
                            source_rows.append(sources)
                            downloaded.extend(paths)
                        quality_rows = list(
                            pool.map(
                                _quality_check_values,
                                [
                                    (
                                        values,
                                        int(batch_row["gps_start"]),
                                        str(batch_row["detector"]),
                                    )
                                    for batch_row, values in zip(
                                        batch, contexts, strict=True
                                    )
                                ],
                            )
                        )
                        for batch_row, values, sources, quality in zip(
                            batch,
                            contexts,
                            source_rows,
                            quality_rows,
                            strict=True,
                        ):
                            if len(selected[detector]) == target:
                                break
                            shard = _write_quality_shard(
                                run_dir=run_dir,
                                row=batch_row,
                                quality=quality,
                                values=values,
                                sources=sources,
                            )
                            checked[detector] += 1
                            if shard["quality_disposition"] == "PASS_CLEAN":
                                selected[detector].append(shard)
                            else:
                                vetoed[detector] += 1
                            offset += 1
                        batch_complete = True
                    finally:
                        if batch_complete:
                            for path in set(downloaded):
                                if path.is_file():
                                    path.unlink()
                        _progress(
                            run_dir,
                            status="RUNNING",
                            checked=checked,
                            proposal_counts=preflight["proposal_manifest"][
                                "counts_by_detector"
                            ],
                        )
                if len(selected[detector]) != target:
                    raise ContractError(
                        f"O3a {detector} clean cohort is incomplete: "
                        f"{len(selected[detector])}/{target}"
                    )
    except BaseException as exc:
        category = (
            "INFRASTRUCTURE_INTERRUPTION"
            if isinstance(exc, (InfrastructureError, OSError, KeyboardInterrupt))
            else "STRUCTURAL_OR_SCIENTIFIC_FAILURE"
        )
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_O3A_NATIVE_COHORT",
            "failure_category": category,
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "error_type": type(exc).__name__,
            "error": str(exc),
            "checked_proposals_by_detector": checked,
        }
        _atomic_json(
            failure_path,
            {**body, "artifact_digest": canonical_json_sha256(body)},
        )
        _progress(
            run_dir,
            status="FAILED",
            checked=checked,
            proposal_counts=preflight["proposal_manifest"]["counts_by_detector"],
        )
        raise
    ledger_rows: list[dict[str, Any]] = []
    for detector in ("H1", "L1"):
        for detector_index, shard in enumerate(selected[detector]):
            ledger_rows.append(
                {
                    **shard,
                    "cohort_detector_index": detector_index,
                    "identity_digest": canonical_json_sha256(
                        {
                            "run": "O3A",
                            "detector": detector,
                            "gps_start": int(shard["gps_start"]),
                            "duration_s": ANALYSIS_DURATION_S,
                        }
                    ),
                }
            )
    ledger_path = run_dir / "native_cohort.jsonl"
    _atomic_jsonl(ledger_path, ledger_rows)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_FROZEN_O3A_NATIVE_COHORT",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "primary_scan_artifact_digest": scan_summary["artifact_digest"],
        "runtime_environment_digest": environment_digest,
        "ledger": {
            "filename": ledger_path.name,
            "sha256": file_sha256(ledger_path),
            "row_digest": canonical_json_sha256(ledger_rows),
            "size_bytes": ledger_path.stat().st_size,
        },
        "counts_by_detector": {
            detector: len(selected[detector]) for detector in ("H1", "L1")
        },
        "row_total": len(ledger_rows),
        "quality_counts": {
            detector: {
                "checked": checked[detector],
                "pass_clean": len(selected[detector]),
                "excess_power_veto": vetoed[detector],
            }
            for detector in ("H1", "L1")
        },
        "scientific_boundary": {
            "primary_score_or_class_read": False,
            "native_embedding_or_score_computed": False,
            "cohort_frozen_before_native_index": True,
            "native_calibration_not_selected": True,
        },
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(summary_path, summary)
    verified, verified_dir = verify_native_cohort(
        root=root,
        primary_external_root=primary_external_root,
        external_root=external_root,
    )
    _atomic_json(root / COMPACT_OUTPUT_REL, verified)
    _progress(
        run_dir,
        status="COMPLETE",
        checked=checked,
        proposal_counts=preflight["proposal_manifest"]["counts_by_detector"],
    )
    if transient_root.is_dir():
        residual = [path for path in transient_root.rglob("*") if path.is_file()]
        if residual:
            raise ContractError("O3a cohort transient raw cache is not empty")
    return verified, verified_dir


def execute_native_cohort(
    *,
    root: Path = ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT,
    primary_external_root: Path = DEFAULT_PRIMARY_EXTERNAL_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    workers: int = DEFAULT_WORKERS,
    quality_batch_size: int = DEFAULT_QUALITY_BATCH_SIZE,
) -> tuple[dict[str, Any], Path]:
    """Own one immutable run key and reject duplicate cohort processes."""

    import fcntl

    resolved_root = root.resolve()
    resolved_external = external_root.resolve()
    contract = load_cohort_contract(root=resolved_root)
    runtime = load_runtime_contract(root=resolved_root, require_current=True)
    run_key = _run_key(
        contract,
        environment_digest=runtime["runtime_environment"]["environment_digest"],
    )
    run_dir = resolved_external / f"native_cohort_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "run.lock").open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError(
                "another O3a native-cohort process owns this run key"
            ) from exc
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()) + "\n")
        lock.flush()
        try:
            return _execute_native_cohort_locked(
                root=resolved_root,
                raw_root=raw_root,
                primary_external_root=primary_external_root,
                external_root=resolved_external,
                workers=workers,
                quality_batch_size=quality_batch_size,
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def verify_native_cohort(
    *,
    root: Path = ROOT,
    primary_external_root: Path = DEFAULT_PRIMARY_EXTERNAL_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    """Independently verify the frozen cohort without computing native scores."""

    root = root.resolve()
    contract = load_cohort_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    environment_digest = runtime["runtime_environment"]["environment_digest"]
    run_key = _run_key(contract, environment_digest=environment_digest)
    run_dir = external_root.resolve() / f"native_cohort_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("O3a native-cohort failure artifact is present")
    preflight = _load_preflight(
        contract=contract, run_dir=run_dir, run_key=run_key
    )
    summary_path = run_dir / "native_cohort_summary.json"
    ledger_path = run_dir / "native_cohort.jsonl"
    if not summary_path.is_file() or not ledger_path.is_file():
        raise ContractError("O3a native-cohort artifacts are incomplete")
    summary = _read_json(summary_path)
    summary_body = dict(summary)
    declared = summary_body.pop("artifact_digest", None)
    if (
        declared != canonical_json_sha256(summary_body)
        or summary.get("status") != "PASS_FROZEN_O3A_NATIVE_COHORT"
        or summary.get("run_key") != run_key
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("preflight_digest") != preflight["preflight_digest"]
    ):
        raise ContractError("O3a native-cohort summary changed")
    rows = _read_jsonl(ledger_path)
    if (
        file_sha256(ledger_path) != summary["ledger"]["sha256"]
        or canonical_json_sha256(rows) != summary["ledger"]["row_digest"]
    ):
        raise ContractError("O3a native-cohort ledger changed")
    target = int(contract["selection"]["target_rows_per_detector"])
    counts = {
        detector: sum(row.get("detector") == detector for row in rows)
        for detector in ("H1", "L1")
    }
    if counts != {"H1": target, "L1": target} or len(rows) != 2 * target:
        raise ContractError("O3a native-cohort cardinality changed")
    identities = [(str(row["detector"]), int(row["gps_start"])) for row in rows]
    if len(identities) != len(set(identities)):
        raise ContractError("O3a native-cohort identities are duplicated")
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root.resolve()
    )
    scan_rows = _scan_identity_rows(scan_dir / "primary_scan.sqlite")
    scan_lookup = {(detector, gps): candidate for detector, gps, candidate in scan_rows}
    candidate_times = sorted({gps for _detector, gps, candidate in scan_rows if candidate})
    guard = int(contract["selection"]["candidate_guard_start_delta_s"])
    separation = int(
        contract["selection"]["minimum_same_detector_separation_s"]
    )
    for detector in ("H1", "L1"):
        detector_gps = sorted(gps for row_detector, gps in identities if row_detector == detector)
        if any(
            right - left < separation
            for left, right in zip(detector_gps, detector_gps[1:], strict=False)
        ):
            raise ContractError("O3a native-cohort separation gate failed")
    frame_rows = _raw_frame_rows(scan_dir / "primary_scan.sqlite")
    inventory = load_source_inventory(root=root)
    frames_by_detector = {
        detector: _inventory_frames(inventory, detector)
        for detector in ("H1", "L1")
    }
    frame_starts_by_detector = {
        detector: [int(frame["gps_start"]) for frame in frames]
        for detector, frames in frames_by_detector.items()
    }
    for row in rows:
        identity = (str(row["detector"]), int(row["gps_start"]))
        if identity not in scan_lookup or scan_lookup[identity]:
            raise ContractError("O3a native-cohort contains a primary candidate")
        gps = identity[1]
        position = bisect.bisect_left(candidate_times, gps - guard)
        if position < len(candidate_times) and candidate_times[position] <= gps + guard:
            raise ContractError("O3a native-cohort violates the candidate guard")
        if row.get("quality_disposition") != "PASS_CLEAN":
            raise ContractError("O3a native-cohort contains a failed quality row")
        shard = _validate_shard(
            run_dir=run_dir,
            row=row,
            value=_read_json(_shard_path(run_dir, row)),
        )
        comparable = {
            key: value
            for key, value in row.items()
            if key not in {"cohort_detector_index", "identity_digest"}
        }
        if comparable != shard:
            raise ContractError("O3a native-cohort ledger/shard mismatch")
        context_path = run_dir / row["raw_context"]["relative_path"]
        values = np.load(context_path, allow_pickle=False)
        if (
            values.shape
            != ((ANALYSIS_DURATION_S + 2 * WHITENING_PAD_S) * SAMPLE_RATE_HZ,)
            or str(values.dtype) != "float64"
            or not np.isfinite(values).all()
            or hashlib.sha256(values.tobytes()).hexdigest()
            != row["raw_context"]["values_sha256"]
        ):
            raise ContractError("O3a native-cohort retained values changed")
        expected_sources = _source_rows_for_context(
            detector=identity[0],
            gps=identity[1],
            frames=frames_by_detector[identity[0]],
            frame_starts=frame_starts_by_detector[identity[0]],
            raw_frame_rows=frame_rows,
        )
        if (
            row["context_sources"] != expected_sources
            or row["context_sources_digest"]
            != canonical_json_sha256(expected_sources)
        ):
            raise ContractError("O3a native-cohort source provenance changed")
    if scan_summary["artifact_digest"] != summary["primary_scan_artifact_digest"]:
        raise ContractError("O3a native-cohort primary parent changed")
    transient_root = run_dir / "transient_raw"
    if transient_root.is_dir() and any(
        path.is_file() for path in transient_root.rglob("*")
    ):
        raise ContractError("O3a native-cohort transient cache is not empty")
    return summary, run_dir


def clear_infrastructure_failure(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> Path:
    contract = load_cohort_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    run_key = _run_key(
        contract,
        environment_digest=runtime["runtime_environment"]["environment_digest"],
    )
    run_dir = external_root.resolve() / f"native_cohort_{run_key}"
    failure_path = run_dir / "failure.json"
    failure = _read_json(failure_path)
    body = dict(failure)
    declared = body.pop("artifact_digest", None)
    if (
        declared != canonical_json_sha256(body)
        or failure.get("run_key") != run_key
        or failure.get("contract_digest") != contract["contract_digest"]
        or failure.get("failure_category") != "INFRASTRUCTURE_INTERRUPTION"
    ):
        raise ContractError("failure is not a verified infrastructure interruption")
    archive = run_dir / "failures" / f"failure_{declared}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    os.replace(failure_path, archive)
    return archive


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "DEFAULT_PRIMARY_EXTERNAL_ROOT",
    "DEFAULT_RAW_ROOT",
    "build_cohort_contract",
    "clear_infrastructure_failure",
    "execute_native_cohort",
    "load_cohort_contract",
    "preflight_native_cohort",
    "proposal_priority",
    "select_native_proposals",
    "validate_cohort_contract",
    "verify_native_cohort",
    "write_cohort_contract",
]
