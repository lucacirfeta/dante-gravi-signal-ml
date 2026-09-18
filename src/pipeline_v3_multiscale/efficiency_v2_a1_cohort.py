"""Outcome-blind held-out cohort for the multiscale A1 confirmation.

The selector reads only geometry, candidate times, and provenance identities.
It excludes every raw block used by the canonical native reference and by the
complete exploratory multiscale-efficiency-v2 cohort before allocating the
held-out background and injection roles.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import (
    FORBIDDEN_OUTCOME_FIELDS,
    ROOT,
    _atomic_json,
    _atomic_jsonl,
    _block_for_gps,
    _block_key,
    _canonical_forbidden_blocks,
    _load_raw_manifest,
    _priority,
    _read_jsonl,
    _row_digest,
    _scan_geometry,
    _verify_external,
    _within_guard,
    sha256_file,
    verify_cohort,
)

A1_COHORT_CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2_a1_cohort.json")
SCHEMA_VERSION = 1
ROLE_ORDER = (
    "heldout_background",
    "heldout_primary_injection",
    "heldout_secondary_control",
)


def _environment_path(reference: Mapping[str, Any]) -> Path:
    import os

    key = "windows" if os.name == "nt" else "wsl"
    return Path(reference["path_by_environment"][key])


def _assert_file_reference(
    root: Path, reference: Mapping[str, Any], label: str
) -> None:
    path = root / str(reference.get("path", ""))
    if not path.is_file() or sha256_file(path) != str(reference.get("sha256", "")):
        raise ContractError(f"A1 cohort {label} mismatch")


def validate_a1_cohort_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("A1 cohort contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported A1 cohort schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-a1-cohort":
        raise ContractError("A1 cohort contract id changed")
    if value.get("status") != "APPROVED_OUTCOME_BLIND_A1_CONFIRMATION_COHORT":
        raise ContractError("A1 cohort is not approved")

    parent = value.get("parent_contract", {})
    _assert_file_reference(root.resolve(), parent, "parent contract")
    exploratory = value.get("exploratory_cohort", {})
    summary_path = _environment_path(exploratory["summary"])
    ledger_path = _environment_path(exploratory["ledger"])
    if (
        not summary_path.is_file()
        or sha256_file(summary_path) != exploratory["summary"]["sha256"]
        or not ledger_path.is_file()
        or sha256_file(ledger_path) != exploratory["ledger"]["sha256"]
    ):
        raise ContractError("A1 exploratory cohort reference mismatch")

    population = value.get("population", {})
    if population != {
        "detectors": ["H1", "L1"],
        "roles": {
            "heldout_background": {"source_blocks_per_detector": 1000},
            "heldout_primary_injection": {
                "source_blocks_per_detector": 100,
                "morphologies": [
                    "Blip",
                    "NarrowChirp",
                    "Whistle",
                    "ScatteredLight",
                    "NoiseBlob",
                ],
                "target_snr": [8, 12, 16, 24, 32, 48],
            },
            "heldout_secondary_control": {
                "source_blocks_per_detector": 40,
                "morphologies": ["HarmonicComb", "WallOfLines", "KoiFish"],
                "target_snr": [8, 12, 16, 24, 32, 48],
            },
        },
    }:
        raise ContractError("approved A1 held-out population changed")

    selection = value.get("selection", {})
    if selection != {
        "algorithm": "sha256_role_block_then_identity_priority",
        "role_allocation_order": list(ROLE_ORDER),
        "selection_reads_identity_and_candidate_firewall_only": True,
        "candidate_guard_is_cross_detector": True,
        "candidate_start_guard_s": 128.0,
        "within_role_minimum_separation_s": 96.0,
        "single_raw_block_context_required": True,
        "one_identity_per_raw_block": True,
        "raw_block_roles_mutually_disjoint": True,
        "canonical_index_blocks_excluded": True,
        "canonical_calibration_blocks_excluded": True,
        "complete_exploratory_cohort_blocks_excluded": True,
        "raw_strain_or_model_opened_during_freeze": False,
    }:
        raise ContractError("approved A1 selection boundary changed")

    expected = value.get("expected_cardinality", {})
    if expected != {
        "rows_per_detector": 1140,
        "rows_total": 2280,
        "unique_blocks_per_detector": 1140,
        "unique_blocks_total": 2280,
    }:
        raise ContractError("approved A1 cohort cardinality changed")

    boundary = value.get("scientific_boundary", {})
    forbidden = set(boundary.get("forbidden_fields", []))
    if not FORBIDDEN_OUTCOME_FIELDS <= forbidden:
        raise ContractError("A1 outcome firewall changed")
    if (
        boundary.get("heldout_outcomes_opened") is not False
        or boundary.get("production_endpoint_changed") is not False
        or boundary.get("O3_transfer_validity_established") is not False
    ):
        raise ContractError("A1 cohort scientific boundary changed")
    for label, reference in value.get("references", {}).items():
        _assert_file_reference(root.resolve(), reference, label)
    return value


def load_a1_cohort_contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    path = root / A1_COHORT_CONTRACT_REL
    return validate_a1_cohort_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def _old_cohort_rows(
    contract: Mapping[str, Any], *, root: Path
) -> list[dict[str, Any]]:
    exploratory = contract["exploratory_cohort"]
    summary_path = _environment_path(exploratory["summary"])
    ledger_path = _environment_path(exploratory["ledger"])
    summary = verify_cohort(run_dir=summary_path.parent, root=root)
    if (
        summary["artifact_digest"] != exploratory["artifact_digest"]
        or summary["run_key"] != exploratory["run_key"]
    ):
        raise ContractError("A1 exploratory cohort identity changed")
    return _read_jsonl(ledger_path)


def _globally_separated(
    rows: Sequence[Mapping[str, Any]], gps: float, minimum_separation_s: float
) -> bool:
    return all(
        abs(gps - float(row["gps_start"])) >= minimum_separation_s for row in rows
    )


def select_a1_cohort_rows(
    *,
    contract: Mapping[str, Any],
    raw_blocks: Mapping[str, Sequence[Mapping[str, Any]]],
    scan_geometry: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate_times: Sequence[float],
    canonical_forbidden_blocks: set[tuple[str, float, float, str]],
    exploratory_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    digest = str(contract["contract_digest"])
    selection = contract["selection"]
    guard = float(selection["candidate_start_guard_s"])
    separation = float(selection["within_role_minimum_separation_s"])
    pad = 4.0
    duration = 32.0
    old_by_detector: dict[str, set[tuple[str, float, float, str]]] = defaultdict(set)
    for row in exploratory_rows:
        old_by_detector[str(row["detector"])].add(_block_key(row["raw_block"]))

    selected: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    for detector in contract["population"]["detectors"]:
        candidates_by_block: dict[
            tuple[str, float, float, str], list[dict[str, Any]]
        ] = defaultdict(list)
        rejected = {
            "candidate_guard": 0,
            "canonical_block": 0,
            "exploratory_block": 0,
            "single_block_context": 0,
        }
        for geometry_row in scan_geometry[detector]:
            gps = float(geometry_row["gps_start"])
            if _within_guard(gps, candidate_times, guard):
                rejected["candidate_guard"] += 1
                continue
            block = _block_for_gps(raw_blocks[detector], gps)
            key = _block_key(block)
            if key in canonical_forbidden_blocks:
                rejected["canonical_block"] += 1
                continue
            if key in old_by_detector[detector]:
                rejected["exploratory_block"] += 1
                continue
            if gps - pad < float(block["gps_start"]) or gps + duration + pad > float(
                block["gps_end"]
            ):
                rejected["single_block_context"] += 1
                continue
            candidates_by_block[key].append(
                {
                    **dict(geometry_row),
                    "gps_end": gps + duration,
                    "context_interval": [gps - pad, gps + duration + pad],
                    "raw_block": dict(block),
                }
            )

        used_blocks: set[tuple[str, float, float, str]] = set()
        detector_rows: list[dict[str, Any]] = []
        role_audit: dict[str, Any] = {}
        for role in ROLE_ORDER:
            target = int(
                contract["population"]["roles"][role]["source_blocks_per_detector"]
            )
            keys = [key for key in candidates_by_block if key not in used_blocks]
            keys.sort(
                key=lambda key: _priority(
                    digest, role, detector, f"{key[1]:.9f}|{key[2]:.9f}|{key[3]}"
                )
            )
            role_rows: list[dict[str, Any]] = []
            for key in keys:
                ordered = sorted(
                    candidates_by_block[key],
                    key=lambda row: _priority(
                        digest, role, detector, f"{float(row['gps_start']):.9f}"
                    ),
                )
                row = next(
                    (
                        candidate
                        for candidate in ordered
                        if _globally_separated(
                            role_rows,
                            float(candidate["gps_start"]),
                            separation,
                        )
                    ),
                    None,
                )
                if row is None:
                    continue
                role_rows.append(
                    {
                        **row,
                        "role": role,
                        "role_block_index": len(role_rows),
                        "selection_priority": _priority(
                            digest, role, detector, f"{float(row['gps_start']):.9f}"
                        ),
                    }
                )
                used_blocks.add(key)
                if len(role_rows) == target:
                    break
            if len(role_rows) != target:
                raise ContractError(f"{detector} {role} held-out pool is incomplete")
            for role_index, row in enumerate(role_rows):
                row["role_index"] = role_index
                row["identity_digest"] = canonical_json_sha256(
                    {
                        "contract_digest": digest,
                        "role": role,
                        "detector": detector,
                        "gps_start": float(row["gps_start"]),
                        "raw_source_sha256": str(row["raw_block"]["source_sha256"]),
                    }
                )
            detector_rows.extend(role_rows)
            role_audit[role] = {
                "selected_rows": len(role_rows),
                "selected_blocks": len(role_rows),
            }
        selected.extend(detector_rows)
        audit[detector] = {
            "candidate_blocks_after_exclusions": len(candidates_by_block),
            "exploratory_blocks_excluded": len(old_by_detector[detector]),
            "rejections": rejected,
            "roles": role_audit,
        }

    selected.sort(
        key=lambda row: (str(row["detector"]), str(row["role"]), int(row["role_index"]))
    )
    for row_number, row in enumerate(selected):
        row["row_number"] = row_number
        if FORBIDDEN_OUTCOME_FIELDS & set(row):
            raise ContractError("A1 cohort contains a forbidden outcome field")
    return selected, audit


def _input_paths(contract: Mapping[str, Any]) -> dict[str, Path]:
    return {
        name: _environment_path(reference)
        for name, reference in contract["external_inputs"].items()
    }


def _expected_run_key(contract: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "stage": "freeze_multiscale_efficiency_v2_a1_cohort",
            "contract_digest": contract["contract_digest"],
            "primary_scan_sha256": contract["external_inputs"]["primary_scan_database"][
                "sha256"
            ],
            "exploratory_cohort_artifact_digest": contract["exploratory_cohort"][
                "artifact_digest"
            ],
        }
    )


def _build_expected(
    contract: Mapping[str, Any], *, root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    paths = _input_paths(contract)
    for label, reference in contract["external_inputs"].items():
        _verify_external(paths[label], reference["sha256"], label)
    parent = json.loads(
        (root / contract["parent_contract"]["path"]).read_text(encoding="utf-8")
    )
    raw_blocks = _load_raw_manifest(root / parent["references"]["raw_manifest"]["path"])
    geometry, candidate_times = _scan_geometry(paths["primary_scan_database"])
    canonical_forbidden = _canonical_forbidden_blocks(
        raw_blocks=raw_blocks,
        native_index_manifest=paths["native_index_manifest"],
        native_index_cohort_ledger=paths["native_index_cohort_ledger"],
        native_calibration_ledger=paths["native_calibration_ledger"],
    )
    old_rows = _old_cohort_rows(contract, root=root)
    rows, audit = select_a1_cohort_rows(
        contract=contract,
        raw_blocks=raw_blocks,
        scan_geometry=geometry,
        candidate_times=candidate_times,
        canonical_forbidden_blocks=canonical_forbidden,
        exploratory_rows=old_rows,
    )
    return rows, audit, len(canonical_forbidden)


def freeze_a1_cohort(
    *, output_root: Path, root: Path = ROOT
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_a1_cohort_contract(root)
    rows, audit, canonical_count = _build_expected(contract, root=root)
    run_key = _expected_run_key(contract)
    run_dir = output_root.resolve() / f"a1_cohort_{run_key}"
    ledger_path = run_dir / "a1_heldout_cohort.jsonl"
    summary_path = run_dir / "a1_heldout_cohort_summary.json"
    if summary_path.is_file():
        return verify_a1_cohort(run_dir=run_dir, root=root), run_dir
    run_dir.mkdir(parents=True, exist_ok=False)
    _atomic_jsonl(ledger_path, rows)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_FROZEN_MULTISCALE_EFFICIENCY_V2_A1_COHORT",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "ledger": {
            "filename": ledger_path.name,
            "row_total": len(rows),
            "row_digest": _row_digest(rows),
            "sha256": sha256_file(ledger_path),
        },
        "canonical_forbidden_raw_blocks": canonical_count,
        "exploratory_cohort_artifact_digest": contract["exploratory_cohort"][
            "artifact_digest"
        ],
        "audit": audit,
        "scientific_boundary": contract["scientific_boundary"],
    }
    _atomic_json(summary_path, {**body, "artifact_digest": canonical_json_sha256(body)})
    return verify_a1_cohort(run_dir=run_dir, root=root), run_dir


def verify_a1_cohort(*, run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    contract = load_a1_cohort_contract(root)
    summary_path = run_dir / "a1_heldout_cohort_summary.json"
    ledger_path = run_dir / "a1_heldout_cohort.jsonl"
    if not summary_path.is_file() or not ledger_path.is_file():
        raise ContractError("A1 held-out cohort output is incomplete")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("A1 held-out cohort artifact digest mismatch")
    expected_rows, expected_audit, expected_canonical = _build_expected(
        contract, root=root
    )
    expected_run_key = _expected_run_key(contract)
    if (
        summary.get("status") != "PASS_FROZEN_MULTISCALE_EFFICIENCY_V2_A1_COHORT"
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"a1_cohort_{expected_run_key}"
        or summary.get("contract_digest") != contract["contract_digest"]
    ):
        raise ContractError("A1 held-out cohort identity changed")
    rows = _read_jsonl(ledger_path)
    if (
        rows != expected_rows
        or summary["ledger"]["row_total"] != len(expected_rows)
        or summary["ledger"]["row_digest"] != _row_digest(expected_rows)
        or summary["ledger"]["sha256"] != sha256_file(ledger_path)
        or summary["audit"] != expected_audit
        or summary["canonical_forbidden_raw_blocks"] != expected_canonical
    ):
        raise ContractError("A1 held-out cohort deterministic replay mismatch")
    expected = contract["expected_cardinality"]
    if len(rows) != int(expected["rows_total"]):
        raise ContractError("A1 held-out cohort cardinality changed")
    block_ids = {(str(row["detector"]), _block_key(row["raw_block"])) for row in rows}
    if len(block_ids) != int(expected["unique_blocks_total"]):
        raise ContractError("A1 held-out cohort block uniqueness changed")
    return summary


__all__ = [
    "A1_COHORT_CONTRACT_REL",
    "freeze_a1_cohort",
    "load_a1_cohort_contract",
    "select_a1_cohort_rows",
    "validate_a1_cohort_contract",
    "verify_a1_cohort",
]
