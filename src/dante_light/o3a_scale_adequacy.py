"""Outcome-blind scale audit and approved stage contract for O3a.

The audit uses only the frozen CBC_CAT1 segment geometry and checked-in
method contracts. It does not read strain, scores, classes, or candidate
outcomes. Its narrow purpose is to establish that the approved O4a-parity
cardinalities fit inside O3a and retain the same nominal p99/block design.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import (
    ROOT,
    load_dq_snapshot,
    load_stage_decision_gate,
)


SCALE_AUDIT_REL = "artifacts/dante_light/o3a_native_v1/o3a_scale_adequacy.json"
STAGE_CONTRACT_REL = "config/dante_o3a_native_v1_stage_contract.json"
O4A_SCAN_REL = "artifacts/dante_light/o4a_v1_parity/corrected_primary_scan.json"
O4A_INDEX_CONTRACT_REL = "config/dante_o4a_corrected_native_index_v1.json"
SCHEMA_VERSION = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _aligned_starts(
    segments: Iterable[Iterable[int]],
    *,
    stride_s: int,
    analysis_duration_s: int,
    whitening_pad_s: int,
) -> Iterable[int]:
    """Yield globally aligned starts with complete symmetric context."""
    for raw_left, raw_right in segments:
        left = int(raw_left) + whitening_pad_s
        right = int(raw_right) - analysis_duration_s - whitening_pad_s
        first = ((left + stride_s - 1) // stride_s) * stride_s
        if first <= right:
            yield from range(first, right + 1, stride_s)


def _separated_capacity(starts: Iterable[int], minimum_separation_s: int) -> int:
    count = 0
    previous: int | None = None
    for start in starts:
        if previous is None or start - previous >= minimum_separation_s:
            count += 1
            previous = start
    return count


def build_scale_adequacy_audit(*, root: Path = ROOT) -> dict[str, Any]:
    gate = load_stage_decision_gate(root=root)
    dq = load_dq_snapshot(root=root)
    recommendations = gate["recommendations"]
    initial = recommendations["initial_calibration_and_scan"]
    firewall = recommendations["population_firewall"]
    statistics = recommendations["native_threshold_statistics"]
    architecture = recommendations["native_index_architecture"]

    scan_path = root / O4A_SCAN_REL
    index_path = root / O4A_INDEX_CONTRACT_REL
    o4a_scan = json.loads(scan_path.read_text(encoding="utf-8"))
    o4a_index = json.loads(index_path.read_text(encoding="utf-8"))
    o4a_counts = o4a_scan["window_counts"]
    patch_tokens = int(o4a_index["representation"]["patch_tokens_per_image"])

    duration = int(initial["analysis_duration_s"])
    pad = int(initial["whitening_pad_s"])
    scan_stride = 32
    calibration_stride = int(initial["window_stride_s"])
    calibration_target = int(initial["calibration_rows_per_detector"])
    index_target = int(firewall["index_cohort_rows_per_detector"])
    separation = int(firewall["index_same_detector_minimum_separation_s"])
    block_length = int(statistics["block_length_rows"])
    percentile = int(statistics["score_percentile"])

    detector_results: dict[str, dict[str, Any]] = {}
    for detector in initial["detectors"]:
        segments = dq["segments"][detector]
        scan_starts = list(
            _aligned_starts(
                segments,
                stride_s=scan_stride,
                analysis_duration_s=duration,
                whitening_pad_s=pad,
            )
        )
        calibration_starts = list(
            _aligned_starts(
                segments,
                stride_s=calibration_stride,
                analysis_duration_s=duration,
                whitening_pad_s=pad,
            )
        )
        separated_capacity = _separated_capacity(scan_starts, separation)
        detector_results[detector] = {
            "cbc_cat1_livetime_s": dq["summaries"][detector]["livetime_s"],
            "eligible_scan_starts": len(scan_starts),
            "o4a_corrected_eligible_scan_starts": int(o4a_counts[detector]),
            "o3a_to_o4a_eligible_ratio": len(scan_starts)
            / int(o4a_counts[detector]),
            "eligible_calibration_starts": len(calibration_starts),
            "calibration_target_rows": calibration_target,
            "calibration_pool_fraction": calibration_target
            / len(calibration_starts),
            "calibration_capacity_multiple": len(calibration_starts)
            / calibration_target,
            "greedy_index_capacity_at_required_separation": separated_capacity,
            "index_target_rows": index_target,
            "index_pool_fraction": index_target / separated_capacity,
            "index_capacity_multiple": separated_capacity / index_target,
            "capacity_gates_pass": (
                len(calibration_starts) >= calibration_target
                and separated_capacity >= index_target
            ),
        }

    native_rows = int(statistics["native_calibration_rows_per_detector"])
    complete_blocks = native_rows // block_length
    rows_outside_complete_blocks = native_rows % block_length
    expected_upper_tail = native_rows * (100 - percentile) / 100
    cohort_rows = index_target * len(detector_results)
    token_total = cohort_rows * patch_tokens
    centroid_count = int(architecture["centroid_count"])
    raw_sample_size = int(architecture["raw_embedding_sample_size"])

    parity = {
        "calibration_rows_per_detector": native_rows,
        "score_percentile": percentile,
        "nominal_expected_upper_tail_observations": expected_upper_tail,
        "block_length_rows": block_length,
        "complete_non_overlapping_blocks": complete_blocks,
        "rows_excluded_from_complete_block_resampling": rows_outside_complete_blocks,
        "point_estimate_uses_all_rows": statistics[
            "point_percentile_uses_all_rows"
        ],
        "index_rows_total": cohort_rows,
        "patch_tokens_per_window": patch_tokens,
        "exact_patch_token_total": token_total,
        "centroid_count": centroid_count,
        "tokens_per_centroid": token_total / centroid_count,
        "raw_embedding_sample_size": raw_sample_size,
        "matches_corrected_o4a_design": (
            native_rows == 5000
            and percentile == 99
            and block_length == 17
            and complete_blocks == 294
            and rows_outside_complete_blocks == 2
            and cohort_rows == 1294
            and token_total == int(o4a_index["gates"]["exact_patch_token_total"])
            and centroid_count == int(o4a_index["clustering"]["centroid_count"])
            and raw_sample_size
            == int(o4a_index["clustering"]["raw_embedding_sample_size"])
        ),
    }
    capacity_pass = all(
        item["capacity_gates_pass"] for item in detector_results.values()
    )
    status = (
        "PASS_METHOD_PARITY_SCALE_ADEQUATE"
        if capacity_pass and parity["matches_corrected_o4a_design"]
        else "FAIL_SCALE_OR_PARITY"
    )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run": "O3A",
        "read_only_geometry_audit": True,
        "strain_data_accessed": False,
        "outcome_data_accessed": False,
        "stage_decision_gate": {
            "path": "config/dante_o3a_native_v1_stage_decision_gate.json",
            "sha256": _sha256_file(
                root / "config/dante_o3a_native_v1_stage_decision_gate.json"
            ),
            "gate_digest": gate["gate_digest"],
        },
        "dq_snapshot_digest": dq["snapshot_digest"],
        "reference_evidence": {
            "corrected_o4a_scan": {
                "path": O4A_SCAN_REL,
                "sha256": _sha256_file(scan_path),
            },
            "corrected_o4a_native_index_contract": {
                "path": O4A_INDEX_CONTRACT_REL,
                "sha256": _sha256_file(index_path),
            },
            "scale_audit_implementation": {
                "path": "src/dante_light/o3a_scale_adequacy.py",
                "sha256": _sha256_file(
                    root / "src/dante_light/o3a_scale_adequacy.py"
                ),
            },
            "freeze_entrypoint": {
                "path": "scripts/freeze_dante_o3a_stage_contract.py",
                "sha256": _sha256_file(
                    root / "scripts/freeze_dante_o3a_stage_contract.py"
                ),
            },
        },
        "geometry": {
            "analysis_duration_s": duration,
            "whitening_pad_s": pad,
            "scan_alignment_s": scan_stride,
            "calibration_alignment_s": calibration_stride,
            "index_minimum_separation_s": separation,
            "complete_symmetric_context_required": True,
        },
        "detectors": detector_results,
        "nominal_statistical_and_representation_parity": parity,
        "interpretation_boundary": {
            "establishes_geometric_capacity": True,
            "preserves_nominal_p99_tail_count_and_block_count": True,
            "index_cardinality_is_architectural_parity_not_a_power_claim": True,
            "does_not_guarantee_realized_threshold_ci_width": True,
            "does_not_guarantee_post_guard_population_completion": True,
            "execution_time_selection_must_fail_closed_on_shortfall": True,
            "realized_ci_must_be_finite_nondegenerate_and_contain_point": True,
            "new_post_hoc_ci_width_cutoff_introduced": False,
        },
    }
    return {**body, "audit_digest": canonical_json_sha256(body)}


def validate_scale_adequacy_audit(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    expected = build_scale_adequacy_audit(root=root)
    if dict(value) != expected:
        raise ContractError("O3a scale-adequacy audit mismatch")
    if value.get("status") != "PASS_METHOD_PARITY_SCALE_ADEQUATE":
        raise ContractError("O3a scale adequacy did not pass")
    return dict(value)


def load_scale_adequacy_audit(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / SCALE_AUDIT_REL
    if not path.is_file():
        raise ContractError("O3a scale-adequacy audit is absent")
    return validate_scale_adequacy_audit(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def build_stage_contract(*, root: Path = ROOT) -> dict[str, Any]:
    gate = load_stage_decision_gate(root=root)
    audit = load_scale_adequacy_audit(root=root)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "AUTHOR_APPROVED_METHOD_PARITY_STAGE_CONTRACT",
        "run": "O3A",
        "approval_date": "2026-09-19",
        "historical_unresolved_gate_preserved": True,
        "source_gate_digest": gate["gate_digest"],
        "scale_adequacy": {
            "path": SCALE_AUDIT_REL,
            "sha256": _sha256_file(root / SCALE_AUDIT_REL),
            "audit_digest": audit["audit_digest"],
            "status": audit["status"],
        },
        "author_decisions": gate["recommendations"],
        "methodological_parity": {
            "architecture_and_statistics_preserved": True,
            "fresh_o3a_populations_required": True,
            "o4a_scientific_rows_or_outputs_imported": False,
            "post_hoc_o3a_hyperparameter_tuning_allowed": False,
        },
        "execution_boundary": {
            "outcome_blind_identity_manifest_preparation_allowed": True,
            "public_dq_metadata_use_allowed": True,
            "strain_access_allowed": False,
            "scoring_allowed": False,
            "threshold_fitting_allowed": False,
            "full_scan_allowed": False,
            "next_gate": (
                "freeze and verify disjoint outcome-blind O3a population identity "
                "manifests before any strain access"
            ),
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_stage_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    expected = build_stage_contract(root=root)
    if dict(value) != expected:
        raise ContractError("O3a approved stage contract mismatch")
    boundary = value["execution_boundary"]
    if (
        boundary["strain_access_allowed"] is not False
        or boundary["scoring_allowed"] is not False
        or boundary["threshold_fitting_allowed"] is not False
        or boundary["full_scan_allowed"] is not False
    ):
        raise ContractError("O3a stage contract execution boundary was weakened")
    return dict(value)


def load_stage_contract(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / STAGE_CONTRACT_REL
    if not path.is_file():
        raise ContractError("O3a approved stage contract is absent")
    return validate_stage_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def write_scale_audit_and_stage_contract(
    *, root: Path = ROOT
) -> tuple[dict[str, Any], dict[str, Any]]:
    audit = build_scale_adequacy_audit(root=root)
    if audit["status"] != "PASS_METHOD_PARITY_SCALE_ADEQUATE":
        raise ContractError("refusing to freeze a failed O3a scale audit")
    _write_json(root / SCALE_AUDIT_REL, audit)
    contract = build_stage_contract(root=root)
    _write_json(root / STAGE_CONTRACT_REL, contract)
    return audit, contract


__all__ = [
    "SCALE_AUDIT_REL",
    "STAGE_CONTRACT_REL",
    "build_scale_adequacy_audit",
    "build_stage_contract",
    "load_scale_adequacy_audit",
    "load_stage_contract",
    "validate_scale_adequacy_audit",
    "validate_stage_contract",
    "write_scale_audit_and_stage_contract",
]
