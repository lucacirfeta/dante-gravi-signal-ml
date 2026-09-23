"""Freeze O3a native-calibration identities with O4a native-v2 method parity.

This stage reads only scan identities/candidate flags, index-training identities,
and validated frame geometry. It does not read a score or open strain.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from math import ceil
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import ROOT, RUNTIME_REL, load_runtime_contract
from src.dante_light.o3a_native_cohort import (
    _inventory_frames,
    _raw_frame_rows,
    _scan_identity_rows,
    _source_rows_for_context,
    verify_native_cohort,
)
from src.dante_light.o3a_native_index import verify_native_index
from src.dante_light.o3a_primary_scan import verify_primary_scan
from src.dante_light.o3a_raw_acquisition import load_source_inventory
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_light.o3a_scale_adequacy import load_stage_contract


SCHEMA_VERSION = 1
AMENDMENT_REL = "config/dante_o3a_native_calibration_selector_amendment_v1.json"
CONTRACT_REL = "config/dante_o3a_native_calibration_cohort_v1.json"
O4A_CONTRACT_REL = "config/dante_o4a_corrected_native_calibration_v2.json"
O4A_SOURCE_REL = "src/dante_light/o4a_corrected_native_calibration.py"
PRIMARY_REL = "artifacts/dante_light/o3a_native_v1/primary_scan.json"
COHORT_REL = "artifacts/dante_light/o3a_native_v1/native_cohort.json"
INDEX_REL = "artifacts/dante_light/o3a_native_v1/native_index.json"
IMPLEMENTATION_REL = "src/dante_light/o3a_native_calibration_cohort.py"
ENTRYPOINT_REL = "scripts/freeze_dante_o3a_native_calibration_cohort.py"
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _binding(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    return {"path": relative, "sha256": file_sha256(root / relative), **extra}


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if _read_json(path) != value:
            raise ContractError(f"refusing divergent O3a evidence: {path}")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        if existing != list(rows):
            raise ContractError(f"refusing divergent O3a evidence: {path}")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
    os.replace(temporary, path)


def load_amendment(*, root: Path = ROOT) -> dict[str, Any]:
    value = _read_json(root / AMENDMENT_REL)
    body = dict(value)
    declared = body.pop("amendment_digest", None)
    if (
        declared != canonical_json_sha256(body)
        or value.get("status") != "AUTHOR_APPROVED_NATIVE_CALIBRATION_SELECTOR_AMENDMENT"
        or value.get("run") != "O3A"
        or value.get("selection", {}).get("algorithm")
        != "O4A_NATIVE_V2_EVENLY_SPACED_COMPLETE_BLOCKS_WITH_CONTEXT_FALLBACK"
    ):
        raise ContractError("O3a native-calibration amendment changed")
    stage = load_stage_contract(root=root)
    historical = _read_json(root / O4A_CONTRACT_REL)
    if (
        stage["contract_digest"] != value["parent_stage_contract"]["contract_digest"]
        or historical["contract_digest"] != value["method_reference"]["contract_digest"]
        or value["parent_stage_contract"]["path"]
        != "config/dante_o3a_native_v1_stage_contract.json"
        or value["method_reference"]["path"] != O4A_CONTRACT_REL
        or value["method_reference"]["selector_source"] != O4A_SOURCE_REL
        or stage["author_decisions"]["population_firewall"]["selection_priority"]
        != "SHA256_CONTRACT_DETECTOR_GPS"
    ):
        raise ContractError("O3a native selector amendment does not bind its parents")
    return value


def build_cohort_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Build the frozen contract without reading the scan database or outcomes."""
    root = root.resolve()
    amendment = load_amendment(root=root)
    stage = load_stage_contract(root=root)
    runtime = load_runtime_contract(root=root)
    o4a = _read_json(root / O4A_CONTRACT_REL)
    firewall = stage["author_decisions"]["population_firewall"]
    statistics = stage["author_decisions"]["native_threshold_statistics"]
    historical = o4a["population"]
    if (
        statistics["native_calibration_rows_per_detector"]
        != historical["target_rows_by_detector"]["H1"]
        or historical["target_rows_by_detector"]["H1"]
        != historical["target_rows_by_detector"]["L1"]
        or statistics["block_length_rows"] != historical["temporal_block_length"]
        or firewall["native_calibration_guard_start_delta_s"]
        != historical["equivalent_start_delta_s"]
        or firewall["native_calibration_guard_interval_gap_s"]
        != historical["forbidden_guard_s"]
    ):
        raise ContractError("O3a/O4a native calibration method parity changed")
    primary = _read_json(root / PRIMARY_REL)
    cohort = _read_json(root / COHORT_REL)
    index = _read_json(root / INDEX_REL)
    for label, value, expected in (
        ("primary", primary, "PASS_COMPLETE_O3A_PRIMARY_SCAN"),
        ("cohort", cohort, "PASS_FROZEN_O3A_NATIVE_COHORT"),
        ("index", index, "PASS_BUILT_O3A_NATIVE_INDEX"),
    ):
        body = dict(value)
        if body.pop("artifact_digest", None) != canonical_json_sha256(body) or value.get("status") != expected:
            raise ContractError(f"O3a {label} parent is not verified compact evidence")
    if (
        index["cohort_artifact_digest"] != cohort["artifact_digest"]
        or cohort["primary_scan_artifact_digest"] != primary["artifact_digest"]
    ):
        raise ContractError("O3a native-calibration parent chain changed")
    if o4a["references"]["implementation"]["sha256"] != file_sha256(root / O4A_SOURCE_REL):
        raise ContractError("corrected-O4a native selector source bytes changed")
    target = int(statistics["native_calibration_rows_per_detector"])
    block = int(statistics["block_length_rows"])
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_NATIVE_CALIBRATION_COHORT_V1",
        "run": "O3A",
        "parents": {
            "selector_amendment": _binding(root, AMENDMENT_REL, amendment_digest=amendment["amendment_digest"]),
            "approved_stage_contract": _binding(root, amendment["parent_stage_contract"]["path"], contract_digest=stage["contract_digest"]),
            "o4a_native_calibration_method": _binding(root, O4A_CONTRACT_REL, contract_digest=o4a["contract_digest"]),
            "o4a_selector_source": _binding(root, O4A_SOURCE_REL),
            "primary_scan": _binding(root, PRIMARY_REL, artifact_digest=primary["artifact_digest"], run_key=primary["run_key"], database_sha256=primary["database"]["sha256"]),
            "native_cohort": _binding(root, COHORT_REL, artifact_digest=cohort["artifact_digest"], ledger_sha256=cohort["ledger"]["sha256"]),
            "native_index": _binding(root, INDEX_REL, artifact_digest=index["artifact_digest"], run_key=index["run_key"]),
            "runtime": _binding(root, RUNTIME_REL, environment_digest=runtime["runtime_environment"]["environment_digest"]),
        },
        "selection": {
            "algorithm": amendment["selection"]["algorithm"],
            "detectors": ["H1", "L1"],
            "target_rows_per_detector": target,
            "block_length_rows": block,
            "window_duration_s": int(stage["author_decisions"]["initial_calibration_and_scan"]["analysis_duration_s"]),
            "stride_s": int(stage["author_decisions"]["initial_calibration_and_scan"]["window_stride_s"]),
            "pad_s": int(stage["author_decisions"]["initial_calibration_and_scan"]["whitening_pad_s"]),
            "candidate_and_index_guard_start_delta_s": int(firewall["native_calibration_guard_start_delta_s"]),
            "bootstrap_rows_per_detector": (target // block) * block,
            "selector_database_columns": ["detector", "gps_start", "is_candidate"],
            "forbidden_outcome_fields": list(amendment["selection"]["data_forbidden"]),
        },
        "execution": {
            "runtime": "canonical WSL",
            "root_wsl": str(DEFAULT_EXTERNAL_ROOT),
            "strain_or_native_score_opened": False,
            "atomic_outputs": True,
        },
        "implementation_sources": {
            relative: file_sha256(root / relative)
            for relative in (IMPLEMENTATION_REL, ENTRYPOINT_REL)
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def load_cohort_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = _read_json(root / CONTRACT_REL)
    if value != build_cohort_contract(root=root):
        raise ContractError("O3a native-calibration frozen contract changed")
    return value


def write_cohort_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_cohort_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def _near(value: int, sorted_times: Sequence[int], delta: int) -> bool:
    position = bisect.bisect_left(sorted_times, value - delta)
    return position < len(sorted_times) and sorted_times[position] <= value + delta


def select_native_calibration_rows(
    identities: Sequence[tuple[str, int, bool]],
    index_identities: Sequence[tuple[str, int]],
    *,
    target_rows: int,
    block_length: int,
    window_s: int,
    stride_s: int,
    guard_delta_s: int,
    context_sources: Callable[[str, int], Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Reproduce the O4a native-v2 full-block priority, independent of scores."""
    if target_rows <= 0 or block_length <= 0 or target_rows < block_length:
        raise ContractError("invalid O3a native calibration target/block geometry")
    candidates = sorted({gps for _, gps, candidate in identities if candidate})
    index_times = sorted({gps for _, gps in index_identities})
    rows: list[dict[str, Any]] = []
    audit: dict[str, dict[str, int]] = {}
    for detector in ("H1", "L1"):
        eligible: set[int] = set()
        counts = {"guarded_candidates": 0, "guarded_index": 0, "context_rejected_blocks": 0}
        for row_detector, gps, candidate in identities:
            if row_detector != detector or candidate:
                continue
            if _near(gps, candidates, guard_delta_s):
                counts["guarded_candidates"] += 1
            elif _near(gps, index_times, guard_delta_s):
                counts["guarded_index"] += 1
            else:
                eligible.add(gps)
        if not eligible:
            raise ContractError(f"O3a {detector} has no guarded native-calibration pool")
        phases: dict[int, list[int]] = defaultdict(list)
        for gps in sorted(eligible):
            phases[gps % stride_s].append(gps)
        candidate_blocks: list[list[int]] = []
        for phase in sorted(phases):
            runs: list[list[int]] = []
            for gps in phases[phase]:
                if not runs or gps - runs[-1][-1] != stride_s:
                    runs.append([gps])
                else:
                    runs[-1].append(gps)
            for run in runs:
                for offset in range(0, len(run), block_length):
                    chunk = run[offset : offset + block_length]
                    if len(chunk) == block_length:
                        candidate_blocks.append(chunk)
        candidate_blocks.sort(key=lambda block: (block[0], block[-1]))
        available: list[list[int]] = []
        previous_end = -1
        for block in candidate_blocks:
            if block[0] >= previous_end:
                available.append(block)
                previous_end = block[-1] + window_s
        needed = ceil(target_rows / block_length)
        if len(available) < needed:
            raise ContractError(f"O3a {detector} has only {len(available)} complete guarded blocks; needs {needed}")
        chosen = [0] if needed == 1 else [
            int(position * (len(available) - 1) / (needed - 1))
            for position in range(needed)
        ]
        preferred = set(chosen)
        priority = chosen + [i for i in range(len(available)) if i not in preferred]
        accepted: list[dict[str, Any]] = []
        accepted_blocks = 0
        for rank, index in enumerate(priority):
            enriched: list[dict[str, Any]] = []
            try:
                for gps in available[index]:
                    sources = list(context_sources(detector, gps))
                    if not sources:
                        raise ContractError("O3a calibration context is incomplete")
                    enriched.append({
                        "detector": detector,
                        "gps_start": gps,
                        "gps_end": gps + window_s,
                        "context_sources": sources,
                        "context_sources_digest": canonical_json_sha256(sources),
                        "plan_priority_rank": rank,
                    })
            except ContractError:
                counts["context_rejected_blocks"] += 1
                continue
            accepted.extend(enriched)
            accepted_blocks += 1
            if accepted_blocks == needed:
                break
        if accepted_blocks != needed:
            raise ContractError(f"O3a {detector} context-complete pool is too small")
        accepted = sorted(accepted[:target_rows], key=lambda row: row["gps_start"])
        bootstrap_count = (target_rows // block_length) * block_length
        for offset in range(0, bootstrap_count, block_length):
            block = accepted[offset : offset + block_length]
            if len(block) != block_length or any(
                right["gps_start"] - left["gps_start"] != stride_s
                for left, right in zip(block, block[1:])
            ):
                raise ContractError("O3a native-calibration bootstrap block is not complete")
        for position, row in enumerate(accepted):
            row["row_number"] = position
            row["bootstrap_block_index"] = position // block_length
        if len(accepted) != target_rows or len({row["gps_start"] for row in accepted}) != target_rows:
            raise ContractError(f"O3a {detector} selected identities are incomplete or duplicated")
        rows.extend(accepted)
        audit[detector] = {
            **counts,
            "eligible_scan_windows": len(eligible),
            "candidate_blocks_before_non_overlap": len(candidate_blocks),
            "available_nonoverlapping_blocks": len(available),
            "accepted_complete_blocks": accepted_blocks,
            "selected_rows": len(accepted),
        }
    return rows, audit


def _parents(*, root: Path, contract: Mapping[str, Any], external_root: Path) -> tuple[Path, Path, Path]:
    primary, scan_dir = verify_primary_scan(root=root, external_root=external_root)
    cohort, cohort_dir = verify_native_cohort(root=root, primary_external_root=external_root, external_root=external_root)
    index, index_dir = verify_native_index(root=root, external_root=external_root)
    for key, value in (("primary_scan", primary), ("native_cohort", cohort), ("native_index", index)):
        if value["artifact_digest"] != contract["parents"][key]["artifact_digest"]:
            raise ContractError(f"O3a {key} parent changed")
    return scan_dir, cohort_dir, index_dir


def _expected_rows(*, root: Path, contract: Mapping[str, Any], scan_dir: Path, cohort_dir: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    identities = _scan_identity_rows(scan_dir / "primary_scan.sqlite")
    cohort_summary = _read_json(cohort_dir / "native_cohort_summary.json")
    cohort_ledger = cohort_dir / str(cohort_summary["ledger"]["filename"])
    if file_sha256(cohort_ledger) != contract["parents"]["native_cohort"]["ledger_sha256"]:
        raise ContractError("O3a native-index training ledger changed")
    index_rows = [json.loads(line) for line in cohort_ledger.read_text(encoding="utf-8").splitlines() if line]
    index_identities = [(str(row["detector"]), int(row["gps_start"])) for row in index_rows]
    frame_rows = _raw_frame_rows(scan_dir / "primary_scan.sqlite")
    inventory = load_source_inventory(root=root)
    frames = {detector: _inventory_frames(inventory, detector) for detector in ("H1", "L1")}
    starts = {detector: [int(frame["gps_start"]) for frame in frames[detector]] for detector in frames}

    def sources(detector: str, gps: int) -> Sequence[Mapping[str, Any]]:
        return _source_rows_for_context(
            detector=detector, gps=gps, frames=frames[detector],
            frame_starts=starts[detector], raw_frame_rows=frame_rows,
        )

    selection = contract["selection"]
    return select_native_calibration_rows(
        identities, index_identities,
        target_rows=int(selection["target_rows_per_detector"]),
        block_length=int(selection["block_length_rows"]),
        window_s=int(selection["window_duration_s"]),
        stride_s=int(selection["stride_s"]),
        guard_delta_s=int(selection["candidate_and_index_guard_start_delta_s"]),
        context_sources=sources,
    )


def _run_dir(contract: Mapping[str, Any], *, root: Path, external_root: Path) -> Path:
    runtime = load_runtime_contract(root=root, require_current=True)
    run_key = canonical_json_sha256({
        "stage": "o3a_native_calibration_identity_freeze",
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
    })
    return external_root.resolve() / f"native_calibration_cohort_{run_key}"


def freeze_native_calibration_cohort(*, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_cohort_contract(root=root)
    run_dir = _run_dir(contract, root=root, external_root=external_root)
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a native-calibration freeze failure artifact exists")
    if (run_dir / "native_calibration_summary.json").exists():
        return verify_native_calibration_cohort(root=root, external_root=external_root)
    scan_dir, cohort_dir, _ = _parents(root=root, contract=contract, external_root=external_root)
    rows, audit = _expected_rows(root=root, contract=contract, scan_dir=scan_dir, cohort_dir=cohort_dir)
    ledger_path = run_dir / "native_calibration_cohort.jsonl"
    _atomic_jsonl(ledger_path, rows)
    summary_body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_FROZEN_O3A_NATIVE_CALIBRATION_COHORT",
        "contract_digest": contract["contract_digest"],
        "run_key": run_dir.name.removeprefix("native_calibration_cohort_"),
        "counts_by_detector": {detector: sum(row["detector"] == detector for row in rows) for detector in ("H1", "L1")},
        "bootstrap_rows_by_detector": {detector: contract["selection"]["bootstrap_rows_per_detector"] for detector in ("H1", "L1")},
        "selection_audit": audit,
        "ledger": {
            "filename": ledger_path.name,
            "sha256": file_sha256(ledger_path),
            "row_digest": canonical_json_sha256(rows),
            "row_total": len(rows),
        },
        "scores_or_classes_read": False,
    }
    summary = {**summary_body, "artifact_digest": canonical_json_sha256(summary_body)}
    _atomic_json(run_dir / "native_calibration_summary.json", summary)
    return verify_native_calibration_cohort(root=root, external_root=external_root)


def verify_native_calibration_cohort(*, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_cohort_contract(root=root)
    run_dir = _run_dir(contract, root=root, external_root=external_root)
    if (run_dir / "failure.json").exists():
        raise ContractError("O3a native-calibration freeze failure artifact exists")
    summary = _read_json(run_dir / "native_calibration_summary.json")
    body = dict(summary)
    if (
        body.pop("artifact_digest", None) != canonical_json_sha256(body)
        or summary.get("status") != "PASS_FROZEN_O3A_NATIVE_CALIBRATION_COHORT"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key") != run_dir.name.removeprefix("native_calibration_cohort_")
        or summary.get("scores_or_classes_read") is not False
    ):
        raise ContractError("O3a native-calibration summary is invalid")
    ledger_path = run_dir / summary["ledger"]["filename"]
    if file_sha256(ledger_path) != summary["ledger"]["sha256"]:
        raise ContractError("O3a native-calibration ledger hash changed")
    rows = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line]
    selection = contract["selection"]
    target = int(selection["target_rows_per_detector"])
    if (
        len(rows) != 2 * target
        or summary["ledger"]["row_total"] != len(rows)
        or summary["ledger"]["row_digest"] != canonical_json_sha256(rows)
        or summary["counts_by_detector"] != {"H1": target, "L1": target}
        or summary["bootstrap_rows_by_detector"]
        != {"H1": selection["bootstrap_rows_per_detector"], "L1": selection["bootstrap_rows_per_detector"]}
    ):
        raise ContractError("O3a native-calibration cardinality changed")
    if any(set(row) - {"detector", "gps_start", "gps_end", "context_sources", "context_sources_digest", "plan_priority_rank", "row_number", "bootstrap_block_index"} for row in rows):
        raise ContractError("O3a native-calibration ledger contains an outcome field")
    scan_dir, cohort_dir, _ = _parents(root=root, contract=contract, external_root=external_root)
    expected, audit = _expected_rows(root=root, contract=contract, scan_dir=scan_dir, cohort_dir=cohort_dir)
    if rows != expected or summary["selection_audit"] != audit:
        raise ContractError("O3a native-calibration selection changed")
    return summary, run_dir


__all__ = [
    "build_cohort_contract", "load_amendment", "load_cohort_contract",
    "write_cohort_contract", "select_native_calibration_rows",
    "freeze_native_calibration_cohort", "verify_native_calibration_cohort",
]
