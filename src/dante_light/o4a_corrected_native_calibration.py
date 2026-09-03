"""Freeze an outcome-blind native-threshold calibration cohort for O4a.

The historical 5,000-row detector ledgers are not reused as a population.
This stage selects new detector-aware temporal blocks from the verified WSL
primary scan while guarding both corrected candidates and every window used
to train the corrected native index.  No score, threshold, class, or taxonomy
field is read or computed here.
"""

from __future__ import annotations

import bisect
import json
from math import ceil
import os
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from src.core.index_contract import sha256_file
from src.core.patch_producer import load_frozen_raw_manifest
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_execution import verify_primary_scan
from src.dante_light.o4a_corrected_native import verify_native_cohort
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.pipeline_v2_production.background_calibration import RawBlock


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_calibration_v2.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_calibration_v2"
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


def validate_native_calibration_contract(
    payload: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    """Validate the frozen population contract and all repository references."""

    value = dict(payload)
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("corrected native-calibration contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported corrected native-calibration schema")
    population = value.get("population", {})
    if population.get("detectors") != ["H1", "L1"]:
        raise ContractError("corrected native-calibration detector order changed")
    if population.get("target_rows_by_detector") != {"H1": 5000, "L1": 5000}:
        raise ContractError("corrected native-calibration cardinality changed")
    if population.get("selection_algorithm") != (
        "verified_scan_grid_full_run_stratified_nonoverlapping_blocks"
    ):
        raise ContractError("corrected native-calibration selector changed")
    if (
        int(population.get("temporal_block_length", -1)) != 17
        or float(population.get("window_duration_s", -1.0)) != 32.0
        or float(population.get("window_stride_s", -1.0)) != 64.0
        or float(population.get("forbidden_guard_s", -1.0)) != 96.0
        or float(population.get("equivalent_start_delta_s", -1.0)) != 128.0
    ):
        raise ContractError("corrected native-calibration geometry changed")
    boundary = value.get("scientific_boundary", {})
    required_boundary = {
        "selection_reads_identity_and_candidate_firewall_only": True,
        "candidate_guard_is_cross_detector": True,
        "native_index_guard_is_cross_detector": True,
        "complete_temporal_blocks_required": True,
        "historical_calibration_population_reused": False,
        "context_provenance_from_frozen_raw_manifest": True,
    }
    if any(boundary.get(name) is not expected for name, expected in required_boundary.items()):
        raise ContractError("corrected native-calibration scientific boundary changed")
    forbidden = set(boundary.get("forbidden_fields", []))
    if not {
        "primary_score",
        "native_score",
        "score",
        "score_hex",
        "threshold",
        "threshold_lower",
        "threshold_upper",
        "class",
        "robustness_class",
        "taxonomy",
        "taxonomy_family",
        "disposition",
    } <= forbidden:
        raise ContractError("corrected native-calibration outcome firewall changed")
    bootstrap = value.get("future_threshold_contract", {})
    if (
        int(bootstrap.get("bootstrap_replicates", -1)) != 1_000_000
        or int(bootstrap.get("bootstrap_seed", -1)) != 42
        or int(bootstrap.get("bootstrap_chunk_size", -1)) != 500
        or bootstrap.get("percentile") != 99
        or bootstrap.get("confidence_percentiles") != [2.5, 97.5]
    ):
        raise ContractError("corrected native-calibration bootstrap boundary changed")
    for reference in value.get("references", {}).values():
        path = root / str(reference["path"])
        if not path.is_file() or sha256_file(path) != str(reference["sha256"]):
            raise ContractError(f"corrected native-calibration reference mismatch: {path}")
    return value


def load_native_calibration_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_REL
    return validate_native_calibration_contract(
        json.loads(path.read_text(encoding="utf-8")), root.resolve()
    )


def _scan_geometry(
    database_path: Path,
) -> tuple[
    dict[str, dict[float, dict[str, str | bool]]],
    list[float],
]:
    """Read only identity, image hash, and the frozen candidate firewall."""

    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT detector,gps_start,image_sha256,is_candidate,identity_digest "
            "FROM windows ORDER BY detector,gps_start"
        ).fetchall()
    finally:
        connection.close()
    geometry: dict[str, dict[float, dict[str, str | bool]]] = {
        "H1": {},
        "L1": {},
    }
    candidate_times: list[float] = []
    for detector, gps_start, image_sha256, is_candidate, identity_digest in rows:
        detector = str(detector)
        if detector not in geometry:
            raise ContractError("unexpected detector in corrected primary scan")
        gps = float(gps_start)
        if gps in geometry[detector]:
            raise ContractError("duplicate detector/GPS in corrected primary scan")
        image_digest = str(image_sha256)
        identity = str(identity_digest)
        if len(image_digest) != 64 or len(identity) != 64:
            raise ContractError("corrected primary scan identity hashes are incomplete")
        candidate = bool(is_candidate)
        geometry[detector][gps] = {
            "image_sha256": image_digest,
            "identity_digest": identity,
            "is_candidate": candidate,
        }
        if candidate:
            candidate_times.append(gps)
    return geometry, sorted(set(candidate_times))


def _manifest_source_map(
    *, manifest_path: Path, raw_root: Path
) -> dict[str, dict[Path, tuple[str, set[tuple[float, float]]]]]:
    """Resolve the frozen raw sources without reading strain values."""

    resolved: dict[str, dict[Path, tuple[str, set[tuple[float, float]]]]] = {}
    for detector in ("H1", "L1"):
        manifest = load_frozen_raw_manifest(
            manifest_path, raw_root=raw_root, detector=detector
        )
        spans: dict[Path, set[tuple[float, float]]] = {}
        for start, end, source in manifest.entries:
            spans.setdefault(source.resolve(), set()).add((float(start), float(end)))
        resolved[detector] = {
            source: (str(manifest.expected_sha256[source]), source_spans)
            for source, source_spans in spans.items()
        }
    return resolved


def _within_start_guard(value: float, sorted_values: Sequence[float], delta: float) -> bool:
    position = bisect.bisect_right(sorted_values, value - delta)
    return position < len(sorted_values) and sorted_values[position] < value + delta


def _logical_raw_records(
    *,
    records: Sequence[RawBlock],
    expected_sha256: Mapping[Path, str],
) -> list[tuple[float, float, Path, str]]:
    grouped: dict[tuple[float, float], list[Path]] = {}
    for record in records:
        grouped.setdefault(
            (float(record.gps_start), float(record.gps_end)), []
        ).append(record.path.resolve())
    logical: list[tuple[float, float, Path, str]] = []
    for (start, end), paths in grouped.items():
        copies = sorted(set(paths), key=str)
        hashes = {str(expected_sha256.get(path, "")) for path in copies}
        if len(hashes) != 1 or len(next(iter(hashes), "")) != 64:
            raise ContractError("raw manifest copies do not have one frozen hash")
        logical.append((start, end, copies[0], next(iter(hashes))))
    return sorted(logical, key=lambda item: (item[0], item[1], str(item[2])))


def _context_provenance(
    *,
    logical_records: Sequence[tuple[float, float, Path, str]],
    gps_start: float,
    gps_end: float,
    raw_root: Path,
) -> list[dict[str, Any]]:
    """Resolve exact manifest coverage without opening any raw strain file."""

    logical = [
        item
        for item in logical_records
        if item[1] > gps_start and item[0] < gps_end
    ]
    cursor = float(gps_start)
    selected: list[dict[str, Any]] = []
    while cursor < gps_end - 1e-9:
        candidates = [
            item for item in logical if item[0] <= cursor + 1e-9 and item[1] > cursor + 1e-9
        ]
        if not candidates:
            raise ContractError("raw manifest has incomplete whitening context")
        block_start, block_end, source, digest = sorted(
            candidates, key=lambda item: (-item[1], item[0], str(item[2]))
        )[0]
        used_end = min(float(gps_end), block_end)
        selected.append(
            {
                "source_relative_path": str(
                    source.relative_to(raw_root.resolve())
                ).replace("\\", "/"),
                "source_sha256": digest,
                "block_interval": [block_start, block_end],
                "used_interval": [cursor, used_end],
            }
        )
        cursor = used_end
    return selected


def select_native_calibration_rows(
    *,
    raw_blocks_by_detector: Mapping[str, Sequence[RawBlock]],
    source_sha256_by_detector: Mapping[str, Mapping[Path, str]],
    scan_geometry: Mapping[str, Mapping[float, Mapping[str, str | bool]]],
    candidate_times: Sequence[float],
    native_index_times: Sequence[float],
    run_bounds: tuple[float, float],
    raw_root: Path,
    target_rows_by_detector: Mapping[str, int],
    block_length: int,
    guard_s: float,
    pad_s: float,
    window_s: float,
    stride_s: float,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Select full temporal blocks from the verified primary-scan grid."""

    selected: list[dict[str, Any]] = []
    audit: dict[str, dict[str, int]] = {}
    expected_start_delta = window_s + guard_s
    for detector in ("H1", "L1"):
        target = int(target_rows_by_detector[detector])
        geometry = scan_geometry[detector]
        logical_records = _logical_raw_records(
            records=raw_blocks_by_detector[detector],
            expected_sha256=source_sha256_by_detector[detector],
        )
        run_start, run_end = (float(run_bounds[0]), float(run_bounds[1]))
        eligible: dict[float, dict[str, Any]] = {}
        rejected_candidate_guard = 0
        rejected_index_guard = 0
        rejected_context = 0
        for gps, entry in sorted(geometry.items()):
            gps = float(gps)
            if gps < run_start or gps + window_s > run_end or bool(entry["is_candidate"]):
                continue
            if _within_start_guard(gps, candidate_times, expected_start_delta):
                rejected_candidate_guard += 1
                continue
            if _within_start_guard(gps, native_index_times, expected_start_delta):
                rejected_index_guard += 1
                continue
            eligible[gps] = {
                "detector": detector,
                "gps_start": gps,
                "gps_end": gps + window_s,
                "expected_image_sha256": str(entry["image_sha256"]),
                "identity_digest": str(entry["identity_digest"]),
            }

        phase_values = sorted({round(gps % stride_s, 9) for gps in eligible})
        candidate_blocks: list[list[dict[str, Any]]] = []
        for phase in phase_values:
            phase_gps = sorted(
                gps for gps in eligible if abs((gps % stride_s) - phase) <= 1e-9
            )
            runs: list[list[float]] = []
            for gps in phase_gps:
                if not runs or abs(gps - runs[-1][-1] - stride_s) > 1e-9:
                    runs.append([gps])
                else:
                    runs[-1].append(gps)
            for run in runs:
                for offset in range(0, len(run), block_length):
                    chunk = run[offset : offset + block_length]
                    if len(chunk) == block_length:
                        candidate_blocks.append([eligible[gps] for gps in chunk])

        candidate_blocks.sort(
            key=lambda block: (float(block[0]["gps_start"]), float(block[-1]["gps_start"]))
        )
        available_blocks: list[list[dict[str, Any]]] = []
        previous_end = float("-inf")
        for block in candidate_blocks:
            if float(block[0]["gps_start"]) >= previous_end:
                available_blocks.append(block)
                previous_end = float(block[-1]["gps_end"])
        blocks_needed = int(ceil(target / block_length))
        if len(available_blocks) < blocks_needed:
            raise ContractError(
                f"corrected native-calibration {detector} pool is incomplete: "
                f"{len(available_blocks) * block_length}/{target}"
            )
        if blocks_needed == 1:
            chosen_indices = [0]
        else:
            chosen_indices = [
                int(index * (len(available_blocks) - 1) / (blocks_needed - 1))
                for index in range(blocks_needed)
            ]
        chosen = set(chosen_indices)
        priority_indices = chosen_indices + [
            index for index in range(len(available_blocks)) if index not in chosen
        ]
        detector_rows: list[dict[str, Any]] = []
        accepted_blocks = 0
        for priority_rank, block_index in enumerate(priority_indices):
            enriched: list[dict[str, Any]] = []
            try:
                for row in available_blocks[block_index]:
                    gps = float(row["gps_start"])
                    context_sources = _context_provenance(
                        logical_records=logical_records,
                        gps_start=gps - pad_s,
                        gps_end=gps + window_s + pad_s,
                        raw_root=raw_root,
                    )
                    enriched.append(
                        {
                            **row,
                            "context_sources": context_sources,
                            "plan_priority_rank": priority_rank,
                        }
                    )
            except ContractError:
                rejected_context += 1
                continue
            detector_rows.extend(enriched)
            accepted_blocks += 1
            if accepted_blocks >= blocks_needed:
                break
        if accepted_blocks < blocks_needed:
            raise ContractError(
                f"corrected native-calibration {detector} context-complete pool is "
                f"incomplete: {accepted_blocks * block_length}/{target}"
            )
        detector_rows = detector_rows[:target]
        for row_number, row in enumerate(detector_rows):
            gps = float(row["gps_start"])
            if _within_start_guard(gps, candidate_times, expected_start_delta):
                raise ContractError("corrected native-calibration candidate guard failed")
            if _within_start_guard(gps, native_index_times, expected_start_delta):
                raise ContractError("corrected native-calibration index guard failed")
            row["row_number"] = int(row_number)
            row["bootstrap_block_index"] = int(row_number // block_length)
        selected.extend(detector_rows)
        audit[detector] = {
            "eligible_scan_windows": int(len(eligible)),
            "candidate_blocks_before_non_overlap": int(len(candidate_blocks)),
            "plan_blocks_available": int(len(available_blocks)),
            "accepted_complete_blocks": int(accepted_blocks),
            "rejected_candidate_guard": int(rejected_candidate_guard),
            "rejected_index_guard": int(rejected_index_guard),
            "rejected_incomplete_context_blocks": int(rejected_context),
            "selected_rows": int(len(detector_rows)),
        }
    selected.sort(key=lambda row: (str(row["detector"]), float(row["gps_start"])))
    for global_index, row in enumerate(selected):
        row["calibration_index"] = int(global_index)
    return selected, audit


def _run_key(
    contract: Mapping[str, Any],
    *,
    scan_summary: Mapping[str, Any],
    cohort_summary: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> str:
    return canonical_json_sha256(
        {
            "stage": "freeze_corrected_native_calibration_v2",
            "contract_digest": contract["contract_digest"],
            "primary_scan_artifact_digest": scan_summary["artifact_digest"],
            "native_cohort_artifact_digest": cohort_summary["artifact_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
        }
    )


def freeze_native_calibration_cohort(
    *,
    root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    primary_external_root: Path,
    native_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    """Freeze the corrected native-calibration identities before rescoring."""

    root = root.resolve()
    raw_root = raw_root.resolve()
    contract = load_native_calibration_contract(root)
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root.resolve()
    )
    cohort_summary, cohort_dir = verify_native_cohort(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        external_root=native_external_root.resolve(),
    )
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = _run_key(
        contract,
        scan_summary=scan_summary,
        cohort_summary=cohort_summary,
        runtime=runtime,
    )
    run_dir = external_root.resolve() / f"native_calibration_{run_key}"
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "primary_scan_artifact_digest": scan_summary["artifact_digest"],
        "native_cohort_artifact_digest": cohort_summary["artifact_digest"],
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file():
        if json.loads(identity_path.read_text(encoding="utf-8")) != identity:
            raise ContractError("corrected native-calibration run-key collision")
    else:
        _atomic_json(identity_path, identity)
    failure_path = run_dir / "failure.json"
    summary_path = run_dir / "native_calibration_summary.json"
    if failure_path.is_file():
        raise ContractError("corrected native-calibration failure artifact is present")
    if summary_path.is_file():
        return verify_native_calibration_cohort(
            root=root,
            primary_external_root=primary_external_root,
            native_external_root=native_external_root,
            external_root=external_root,
            device=device,
        )
    database_path = scan_dir / "primary_scan.sqlite"
    if sha256_file(database_path) != scan_summary["database"]["sha256"]:
        raise ContractError("corrected primary scan database changed before calibration freeze")
    geometry, candidate_times = _scan_geometry(database_path)
    if sum(len(rows) for rows in geometry.values()) != int(scan_summary["window_total"]):
        raise ContractError("corrected native-calibration saw incomplete scan geometry")
    cohort_rows = _load_jsonl(cohort_dir / cohort_summary["ledger"]["filename"])
    native_index_times = sorted(
        {float(row["gps_start"]) for row in cohort_rows}
    )
    manifest_path = root / contract["references"]["raw_manifest"]["path"]
    raw_blocks: dict[str, list[RawBlock]] = {"H1": [], "L1": []}
    manifests = {}
    for detector in ("H1", "L1"):
        manifest = load_frozen_raw_manifest(
            manifest_path, raw_root=raw_root, detector=detector
        )
        manifests[detector] = manifest
        raw_blocks[detector] = [
            RawBlock(float(start), float(end), Path(path).resolve())
            for start, end, path in manifest.entries
        ]
    population = contract["population"]
    try:
        rows, selection_audit = select_native_calibration_rows(
            raw_blocks_by_detector=raw_blocks,
            source_sha256_by_detector={
                detector: manifests[detector].expected_sha256
                for detector in ("H1", "L1")
            },
            scan_geometry=geometry,
            candidate_times=candidate_times,
            native_index_times=native_index_times,
            run_bounds=tuple(float(value) for value in population["run_bounds_gps"]),
            raw_root=raw_root,
            target_rows_by_detector=population["target_rows_by_detector"],
            block_length=int(population["temporal_block_length"]),
            guard_s=float(population["forbidden_guard_s"]),
            pad_s=float(population["whitening_pad_s"]),
            window_s=float(population["window_duration_s"]),
            stride_s=float(population["window_stride_s"]),
        )
    except BaseException as exc:
        failure = {
            **identity,
            "status": "FAILED_NATIVE_CALIBRATION_FREEZE",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise
    ledger_path = run_dir / "native_calibration_cohort.jsonl"
    _atomic_jsonl(ledger_path, rows)
    counts = {
        detector: sum(str(row["detector"]) == detector for row in rows)
        for detector in ("H1", "L1")
    }
    block_length = int(population["temporal_block_length"])
    threshold = contract["future_threshold_contract"]
    summary_body = {
        **identity,
        "status": "PASS_FROZEN_NATIVE_CALIBRATION_V2",
        "ledger": {
            "filename": ledger_path.name,
            "sha256": sha256_file(ledger_path),
            "size_bytes": ledger_path.stat().st_size,
            "row_digest": canonical_json_sha256(rows),
        },
        "counts_by_detector": counts,
        "row_total": len(rows),
        "candidate_identity_count": int(scan_summary["candidate_total"]),
        "native_index_identity_count": len(cohort_rows),
        "selection_audit": selection_audit,
        "bootstrap_geometry": {
            "block_length": block_length,
            "complete_blocks_per_detector": 5000 // block_length,
            "rows_used_per_bootstrap_draw": (5000 // block_length) * block_length,
            "tail_rows_excluded_from_bootstrap_draw": 5000 % block_length,
            "point_percentile_uses_all_rows": True,
            "bootstrap_replicates": int(threshold["bootstrap_replicates"]),
            "bootstrap_seed": int(threshold["bootstrap_seed"]),
        },
        "scientific_boundary": {
            "historical_calibration_population_reused": False,
            "primary_or_native_scores_read": False,
            "thresholds_or_classes_computed": False,
            "candidate_guard_is_cross_detector": True,
            "native_index_guard_is_cross_detector": True,
            "cohort_frozen_before_native_rescore": True,
        },
    }
    summary = {**summary_body, "artifact_digest": canonical_json_sha256(summary_body)}
    _atomic_json(summary_path, summary)
    return verify_native_calibration_cohort(
        root=root,
        primary_external_root=primary_external_root,
        native_external_root=native_external_root,
        external_root=external_root,
        device=device,
    )


def verify_native_calibration_cohort(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    native_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    """Verify the frozen cohort without opening any score or class field."""

    root = root.resolve()
    contract = load_native_calibration_contract(root)
    scan_summary, scan_dir = verify_primary_scan(
        root=root, external_root=primary_external_root.resolve()
    )
    cohort_summary, cohort_dir = verify_native_cohort(
        root=root,
        primary_external_root=primary_external_root.resolve(),
        external_root=native_external_root.resolve(),
    )
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = _run_key(
        contract,
        scan_summary=scan_summary,
        cohort_summary=cohort_summary,
        runtime=runtime,
    )
    run_dir = external_root.resolve() / f"native_calibration_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("corrected native-calibration failure artifact is present")
    summary_path = run_dir / "native_calibration_summary.json"
    ledger_path = run_dir / "native_calibration_cohort.jsonl"
    if not summary_path.is_file() or not ledger_path.is_file():
        raise ContractError("corrected native-calibration artifacts are incomplete")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("corrected native-calibration artifact digest mismatch")
    if (
        summary.get("status") != "PASS_FROZEN_NATIVE_CALIBRATION_V2"
        or summary.get("run_key") != run_key
        or summary.get("contract_digest") != contract["contract_digest"]
    ):
        raise ContractError("corrected native-calibration summary boundary changed")
    if sha256_file(ledger_path) != summary["ledger"]["sha256"]:
        raise ContractError("corrected native-calibration ledger SHA-256 mismatch")
    rows = _load_jsonl(ledger_path)
    if canonical_json_sha256(rows) != summary["ledger"]["row_digest"]:
        raise ContractError("corrected native-calibration row digest mismatch")
    counts = {
        detector: sum(str(row.get("detector")) == detector for row in rows)
        for detector in ("H1", "L1")
    }
    if counts != {"H1": 5000, "L1": 5000} or len(rows) != 10_000:
        raise ContractError("corrected native-calibration cardinality gate failed")
    forbidden_keys = set(contract["scientific_boundary"]["forbidden_fields"])
    if any(forbidden_keys & set(row) for row in rows):
        raise ContractError("corrected native-calibration ledger contains outcomes")
    manifest_path = root / contract["references"]["raw_manifest"]["path"]
    raw_root = Path(contract["execution"]["raw_root_by_environment"][
        "wsl" if os.name != "nt" else "windows"
    ]).resolve()
    source_map = _manifest_source_map(
        manifest_path=manifest_path,
        raw_root=raw_root,
    )
    geometry, candidate_times = _scan_geometry(scan_dir / "primary_scan.sqlite")
    index_rows = _load_jsonl(cohort_dir / cohort_summary["ledger"]["filename"])
    native_index_times = sorted({float(row["gps_start"]) for row in index_rows})
    delta = float(contract["population"]["equivalent_start_delta_s"])
    block_length = int(contract["population"]["temporal_block_length"])
    identities: set[tuple[str, float]] = set()
    for detector in ("H1", "L1"):
        detector_rows = [row for row in rows if str(row["detector"]) == detector]
        if detector_rows != sorted(detector_rows, key=lambda row: float(row["gps_start"])):
            raise ContractError("corrected native-calibration order changed")
        for row_number, row in enumerate(detector_rows):
            gps = float(row["gps_start"])
            identity = (detector, gps)
            if identity in identities:
                raise ContractError("corrected native-calibration identity duplicated")
            identities.add(identity)
            scan_row = geometry[detector].get(gps)
            if (
                scan_row is None
                or bool(scan_row["is_candidate"])
                or str(scan_row["image_sha256"]) != str(row["expected_image_sha256"])
                or str(scan_row["identity_digest"]) != str(row["identity_digest"])
            ):
                raise ContractError("corrected native-calibration scan replay failed")
            if int(row["row_number"]) != row_number:
                raise ContractError("corrected native-calibration row order changed")
            if int(row["bootstrap_block_index"]) != row_number // block_length:
                raise ContractError("corrected native-calibration block identity changed")
            context_sources = row.get("context_sources")
            if not isinstance(context_sources, list) or not context_sources:
                raise ContractError("corrected native-calibration context provenance is absent")
            cursor = gps - float(contract["population"]["whitening_pad_s"])
            context_end = gps + float(contract["population"]["window_duration_s"]) + float(
                contract["population"]["whitening_pad_s"]
            )
            for context_source in context_sources:
                source = (raw_root / str(context_source["source_relative_path"])).resolve()
                source_entry = source_map[detector].get(source)
                block_interval = tuple(
                    float(value) for value in context_source["block_interval"]
                )
                used_start, used_end = (
                    float(value) for value in context_source["used_interval"]
                )
                if (
                    source_entry is None
                    or str(context_source["source_sha256"]) != source_entry[0]
                    or block_interval not in source_entry[1]
                    or abs(used_start - cursor) > 1e-9
                    or used_end <= used_start
                    or used_end > block_interval[1] + 1e-9
                ):
                    raise ContractError("corrected native-calibration raw provenance changed")
                cursor = used_end
            if abs(cursor - context_end) > 1e-9:
                raise ContractError("corrected native-calibration context coverage changed")
            if _within_start_guard(gps, candidate_times, delta):
                raise ContractError("corrected native-calibration candidate leakage")
            if _within_start_guard(gps, native_index_times, delta):
                raise ContractError("corrected native-calibration index leakage")
        bootstrap_rows = detector_rows[: (len(detector_rows) // block_length) * block_length]
        stride = float(contract["population"]["window_stride_s"])
        for start in range(0, len(bootstrap_rows), block_length):
            block = bootstrap_rows[start : start + block_length]
            if any(
                abs(float(current["gps_start"]) - float(previous["gps_start"]) - stride)
                > 1e-9
                for previous, current in zip(block, block[1:])
            ):
                raise ContractError("corrected native-calibration temporal block changed")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "freeze_native_calibration_cohort",
    "load_native_calibration_contract",
    "select_native_calibration_rows",
    "validate_native_calibration_contract",
    "verify_native_calibration_cohort",
]
