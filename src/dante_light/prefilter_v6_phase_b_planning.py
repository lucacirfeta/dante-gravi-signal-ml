"""Outcome-blind capacity audit used only to plan DANTE-Light v6 Phase B."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_pre_phase_b import (
    load_jsonl,
    maximum_disjoint_starts,
    valid_starts_for_block,
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_planning_contract(path: Path, *, root: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    declared = payload.get("contract_digest")
    body = dict(payload)
    body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-B planning contract digest mismatch")
    if payload.get("status") != "FROZEN_PHASE_B_PLANNING_AUDIT_ONLY":
        raise ContractError("v6 Phase-B planning contract has the wrong status")
    if payload.get("allocation_selection_allowed") is not False:
        raise ContractError("planning audit cannot select an allocation")
    if any(payload["scientific_boundary"].values()):
        raise ContractError("planning audit authorizes a forbidden action")
    for name, reference in payload["source_references"].items():
        relative = Path(reference["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError(f"non-portable planning reference: {name}")
        source = root / relative
        if not source.is_file() or file_sha256(source) != reference["sha256"]:
            raise ContractError(f"planning source mismatch: {name}")
    return payload


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or not np.isfinite(array).all():
        raise ContractError("cannot summarize empty planning capacity")
    return {
        name: float(value)
        for name, value in zip(
            ("minimum", "p05", "p25", "median", "p75", "p95", "maximum"),
            np.quantile(array, (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)),
            strict=True,
        )
    }


def audit_official_capacity(
    *,
    contract: Mapping[str, Any],
    flags: Mapping[str, Any],
    identity_audit: Mapping[str, Any],
    v5_split_rows: Sequence[Mapping[str, Any]],
    pre_phase_b_audit: Mapping[str, Any],
) -> dict[str, Any]:
    spec = contract["capacity_contract"]
    block_duration = int(spec["block_duration_s"])
    duration = int(spec["window_duration_s"])
    pad = int(spec["whitening_pad_each_side_s"])
    step = int(spec["candidate_start_step_s"])
    required = int(spec["training_windows_per_block"])
    if block_duration != 4096:
        raise ContractError("planning audit requires the established 4096 s block")
    prior = set(identity_audit["prior_usage"]["union_o4a_block_keys"])
    used_v5 = {
        f"{row['detector']}:{int(row['stratum']['block_index'])}"
        for row in v5_split_rows
        if "block_index" in row.get("stratum", {})
    }
    thresholds = [
        int(value) for value in spec["reported_minimum_available_start_spans_s"]
    ]
    result: dict[str, Any] = {}
    for detector in spec["detectors"]:
        cat1 = flags[f"{detector}_O4A_CBC_CAT1"]["segments"]
        excluded = [
            segment
            for suffix in ("HW_INJ", "CBC_INJ", "BURST_INJ")
            for segment in flags[f"{detector}_O4A_{suffix}"]["segments"]
        ]
        blocks = {
            block
            for start, end in cat1
            for block in range(
                int(start) // block_duration,
                (int(end) - 1) // block_duration + 1,
            )
        }
        eligible: list[dict[str, Any]] = []
        for block in sorted(blocks):
            key = f"{detector}:{block}"
            if key in prior or key in used_v5:
                continue
            starts = valid_starts_for_block(
                block=block,
                local_intervals=cat1,
                cat1_intervals=cat1,
                excluded_intervals=excluded,
                duration_s=duration,
                pad_s=pad,
                step_s=step,
            )
            maximal = maximum_disjoint_starts(starts, duration_s=duration, pad_s=pad)
            if len(maximal) < required:
                continue
            eligible.append(
                {
                    "key": key,
                    "available_start_span_s": float(max(starts) - min(starts)),
                    "maximum_disjoint_window_count": len(maximal),
                }
            )
        local_count = int(
            pre_phase_b_audit["capacity"][detector][
                "mechanically_eight_window_capable_blocks"
            ]
        )
        result[detector] = {
            "official_eligible_block_count": len(eligible),
            "official_eligible_block_keys_digest": canonical_json_sha256(
                [row["key"] for row in eligible]
            ),
            "currently_local_eligible_block_count": local_count,
            "additional_not_currently_local_count": len(eligible) - local_count,
            "available_start_span_s": _quantiles(
                [row["available_start_span_s"] for row in eligible]
            ),
            "count_by_minimum_available_start_span_s": {
                str(threshold): sum(
                    row["available_start_span_s"] >= threshold for row in eligible
                )
                for threshold in thresholds
            },
        }
    scenarios = []
    for scenario in contract["allocation_scenarios"]:
        total = sum(int(value) for value in scenario["blocks_per_detector"].values())
        threshold = int(scenario["minimum_available_start_span_s"])
        available = {
            detector: (
                result[detector]["official_eligible_block_count"]
                if threshold == 0
                else result[detector]["count_by_minimum_available_start_span_s"][
                    str(threshold)
                ]
            )
            for detector in spec["detectors"]
        }
        scenarios.append(
            {
                **scenario,
                "total_required_blocks_per_detector": total,
                "available_blocks": available,
                "remaining_buffer_blocks": {
                    detector: available[detector] - total for detector in spec["detectors"]
                },
                "mechanically_feasible": all(
                    available[detector] >= total for detector in spec["detectors"]
                ),
                "selected": False,
            }
        )
    result["allocation_scenarios"] = scenarios
    result["interpretation_boundary"] = {
        "identity_only_capacity_not_download_success": True,
        "window_level_independence_established": False,
        "whole_block_resampling_required": True,
        "allocation_selected": False,
        "raw_fetch_performed": False,
    }
    return result


def build_planning_audit(*, contract: Mapping[str, Any], root: Path) -> dict[str, Any]:
    references = contract["source_references"]
    flags = json.loads((root / references["gwosc_segment_snapshot"]["path"]).read_text())
    identity = json.loads((root / references["v5_identity_audit"]["path"]).read_text())
    split_rows = load_jsonl(root / references["v5_split_entries"]["path"])
    pre_phase_b = json.loads((root / references["pre_phase_b_audit"]["path"]).read_text())
    capacity = audit_official_capacity(
        contract=contract,
        flags=flags["flags"],
        identity_audit=identity,
        v5_split_rows=split_rows,
        pre_phase_b_audit=pre_phase_b,
    )
    body: dict[str, Any] = {
        "schema_version": 1,
        "status": "PHASE_B_PLANNING_AUDIT_COMPLETE_AWAITING_DECISION",
        "audit_id": contract["audit_id"],
        "contract_digest": contract["contract_digest"],
        "scientific_boundary": contract["scientific_boundary"],
        "outcome_access": {
            "teacher_targets": [],
            "morphology_labels": [],
            "development": [],
            "confirmation": [],
            "o4b": [],
        },
        "capacity": capacity,
        "decision": {
            "phase_b_frozen": False,
            "allocation_selected": False,
            "objective_selected": False,
            "training_authorized": False,
        },
        "source_references": references,
    }
    body["artifact_digest"] = canonical_json_sha256(body)
    return body
