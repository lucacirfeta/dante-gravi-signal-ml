"""Outcome-safe diagnostics required before a DANTE-Light v6 Phase-B freeze."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch
import torch.nn.functional as F

from src.dante_light.contracts import ContractError, canonical_json_sha256


SCHEMA_VERSION = 1
DETECTORS = ("H1", "L1")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_audit_contract(path: Path, *, root: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("v6 pre-Phase-B audit schema mismatch")
    if payload.get("status") != "FROZEN_PRE_PHASE_B_DIAGNOSTIC_ONLY":
        raise ContractError("v6 pre-Phase-B audit is not frozen")
    body = dict(payload)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 pre-Phase-B audit digest mismatch")
    boundary = payload["scientific_boundary"]
    false_fields = (
        "phase_b_frozen",
        "lambda_frozen",
        "partial_blocks_admitted",
        "population_changed",
        "training_allowed",
        "candidate_promotion_allowed",
        "development_access_allowed",
        "confirmation_access_allowed",
        "o4b_access_allowed",
        "teacher_targets_used_by_gradient_diagnostic",
        "morphology_labels_used",
    )
    if any(boundary.get(key) is not False for key in false_fields):
        raise ContractError("v6 pre-Phase-B audit permits a forbidden action")
    if payload["gradient_diagnostic"].get("lambda_selection_allowed") is not False:
        raise ContractError("gradient diagnostic cannot select lambda")
    if payload["capacity_audit"].get("report_only_no_admission_rule") is not True:
        raise ContractError("capacity diagnostic cannot admit partial blocks")
    for name, reference in payload["source_references"].items():
        relative = Path(reference["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError(f"non-portable audit source: {name}")
        source = root / relative
        if not source.is_file() or file_sha256(source) != reference["sha256"]:
            raise ContractError(f"v6 pre-Phase-B source mismatch: {name}")
    return payload


def merged_intervals(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[tuple[int, int]]]:
    by_detector: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for row in rows:
        by_detector[str(row["detector"])].add(
            (int(row["gps_start"]), int(row["gps_end"]))
        )
    result: dict[str, list[tuple[int, int]]] = {}
    for detector, intervals in by_detector.items():
        merged: list[list[int]] = []
        for start, end in sorted(intervals):
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        result[detector] = [(start, end) for start, end in merged]
    return result


def overlap_seconds(intervals: Sequence[Sequence[int]], left: int, right: int) -> int:
    return int(
        sum(
            max(0, min(right, int(end)) - max(left, int(start)))
            for start, end in intervals
            if int(start) < right and left < int(end)
        )
    )


def interval_intersection_seconds(
    first: Sequence[Sequence[int]],
    second: Sequence[Sequence[int]],
    left: int,
    right: int,
) -> int:
    total = 0
    for first_start, first_end in first:
        if int(first_start) >= right or int(first_end) <= left:
            continue
        for second_start, second_end in second:
            if int(second_start) >= right or int(second_end) <= left:
                continue
            total += max(
                0,
                min(right, int(first_end), int(second_end))
                - max(left, int(first_start), int(second_start)),
            )
    return int(total)


def valid_starts_for_block(
    *,
    block: int,
    local_intervals: Sequence[Sequence[int]],
    cat1_intervals: Sequence[Sequence[int]],
    excluded_intervals: Sequence[Sequence[int]],
    duration_s: int,
    pad_s: int,
    step_s: int,
) -> list[float]:
    left = block * 4096
    right = left + 4096
    local = [(int(a), int(b)) for a, b in local_intervals if int(a) < right and left < int(b)]
    cat1 = [(int(a), int(b)) for a, b in cat1_intervals if int(a) < right and left < int(b)]
    excluded = [
        (int(a), int(b))
        for a, b in excluded_intervals
        if int(a) < right and left < int(b)
    ]
    starts: list[float] = []
    stop = 4096 - (duration_s + pad_s)
    for offset in range(pad_s, stop + 1, step_s):
        start = left + offset
        padded_left = start - pad_s
        padded_right = start + duration_s + pad_s
        if not any(a <= padded_left and padded_right <= b for a, b in local):
            continue
        if not any(a <= padded_left and padded_right <= b for a, b in cat1):
            continue
        if any(a < padded_right and padded_left < b for a, b in excluded):
            continue
        starts.append(float(start))
    return starts


def maximum_disjoint_starts(starts: Sequence[float], *, duration_s: int, pad_s: int) -> list[float]:
    selected: list[float] = []
    occupied: list[tuple[float, float]] = []
    for start in sorted(float(value) for value in starts):
        interval = (start - pad_s, start + duration_s + pad_s)
        if any(left < interval[1] and interval[0] < right for left, right in occupied):
            continue
        selected.append(start)
        occupied.append(interval)
    return selected


def diagnostic_start_selection(
    starts: Sequence[float], *, count: int, contract_digest: str, block_key: str
) -> list[float]:
    if len(starts) < count:
        raise ContractError("insufficient starts for spacing diagnostic")
    return sorted(
        sorted(
            (float(value) for value in starts),
            key=lambda value: (
                canonical_json_sha256(
                    {
                        "contract_digest": contract_digest,
                        "purpose": "v6_partial_block_spacing_only",
                        "block": block_key,
                        "start": value,
                    }
                ),
                value,
            ),
        )[:count]
    )


def _quantiles(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or not np.isfinite(array).all():
        raise ContractError("cannot summarize empty or non-finite audit values")
    probabilities = (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)
    return {
        name: float(value)
        for name, value in zip(
            ("minimum", "p05", "p25", "median", "p75", "p95", "maximum"),
            np.quantile(array, probabilities),
            strict=True,
        )
    }


def audit_remaining_capacity(
    *,
    raw_rows: Sequence[Mapping[str, Any]],
    identity_audit: Mapping[str, Any],
    v5_split_rows: Sequence[Mapping[str, Any]],
    flags: Mapping[str, Any],
    specification: Mapping[str, Any],
    contract_digest: str,
) -> dict[str, Any]:
    block_duration = int(specification["block_duration_s"])
    if block_duration != 4096:
        raise ContractError("v6 audit requires the established 4096 s block unit")
    duration = int(specification["window_duration_s"])
    pad = int(specification["whitening_pad_each_side_s"])
    step = int(specification["candidate_start_step_s"])
    required = int(specification["windows_per_block"])
    local = merged_intervals(raw_rows)
    prior = set(identity_audit["prior_usage"]["union_o4a_block_keys"])
    used_v5 = {
        f"{row['detector']}:{int(row['stratum']['block_index'])}"
        for row in v5_split_rows
        if "block_index" in row.get("stratum", {})
    }
    records: list[dict[str, Any]] = []
    for detector in DETECTORS:
        intervals = local[detector]
        blocks: set[int] = set()
        for start, end in intervals:
            blocks.update(range(start // block_duration, (end - 1) // block_duration + 1))
        cat1 = flags[f"{detector}_O4A_CBC_CAT1"]["segments"]
        excluded = [
            segment
            for suffix in ("HW_INJ", "CBC_INJ", "BURST_INJ")
            for segment in flags[f"{detector}_O4A_{suffix}"]["segments"]
        ]
        for block in sorted(blocks):
            key = f"{detector}:{block}"
            if key in prior or key in used_v5:
                continue
            left, right = block * block_duration, (block + 1) * block_duration
            local_seconds = overlap_seconds(intervals, left, right)
            cat1_seconds = overlap_seconds(cat1, left, right)
            starts = valid_starts_for_block(
                block=block,
                local_intervals=intervals,
                cat1_intervals=cat1,
                excluded_intervals=excluded,
                duration_s=duration,
                pad_s=pad,
                step_s=step,
            )
            maximal = maximum_disjoint_starts(starts, duration_s=duration, pad_s=pad)
            eligible = len(maximal) >= required
            diagnostic_selected = (
                diagnostic_start_selection(
                    maximal,
                    count=required,
                    contract_digest=contract_digest,
                    block_key=key,
                )
                if eligible
                else []
            )
            local_cat1_overlap = interval_intersection_seconds(
                intervals, cat1, left, right
            )
            records.append(
                {
                    "detector": detector,
                    "block": block,
                    "local_seconds": local_seconds,
                    "cat1_seconds": cat1_seconds,
                    "local_CAT1_intersection_seconds": local_cat1_overlap,
                    "local_full": local_seconds == block_duration,
                    "cat1_full": cat1_seconds == block_duration,
                    "valid_start_count": len(starts),
                    "maximum_disjoint_window_count": len(maximal),
                    "eight_window_mechanical_capacity": eligible,
                    "available_valid_start_span_s": (
                        float(max(starts) - min(starts)) if starts else 0.0
                    ),
                    "diagnostic_selected_start_span_s": (
                        float(max(diagnostic_selected) - min(diagnostic_selected))
                        if diagnostic_selected
                        else 0.0
                    ),
                }
            )

    result: dict[str, Any] = {}
    for detector in DETECTORS:
        rows = [row for row in records if row["detector"] == detector]
        eligible = [row for row in rows if row["eight_window_mechanical_capacity"]]
        partial = [row for row in eligible if not row["local_full"]]
        result[detector] = {
            "CAT1_segment_provenance": {
                "flag": flags[f"{detector}_O4A_CBC_CAT1"]["flag"],
                "source": flags[f"{detector}_O4A_CBC_CAT1"]["source"],
                "segments_digest": flags[f"{detector}_O4A_CBC_CAT1"]["segments_digest"],
            },
            "remaining_locally_touched_blocks": len(rows),
            "remaining_local_full_blocks": sum(row["local_full"] for row in rows),
            "remaining_local_partial_blocks": sum(not row["local_full"] for row in rows),
            "remaining_partial_cause_counts": {
                "official_CAT1_partial": sum(
                    not row["local_full"] and not row["cat1_full"] for row in rows
                ),
                "official_CAT1_full_local_mirror_gap": sum(
                    not row["local_full"] and row["cat1_full"] for row in rows
                ),
            },
            "mechanically_eight_window_capable_blocks": len(eligible),
            "capable_local_full_blocks": sum(row["local_full"] for row in eligible),
            "capable_local_partial_blocks": len(partial),
            "capable_partial_cause_counts": {
                "official_CAT1_partial": sum(not row["cat1_full"] for row in partial),
                "official_CAT1_full_local_mirror_gap": sum(row["cat1_full"] for row in partial),
            },
            "local_seconds_outside_CAT1": sum(
                row["local_seconds"] - row["local_CAT1_intersection_seconds"]
                for row in rows
            ),
            "CAT1_seconds_missing_from_local_mirror": sum(
                row["cat1_seconds"] - row["local_CAT1_intersection_seconds"]
                for row in rows
            ),
            "available_valid_start_span_s_for_capable_partial_blocks": _quantiles(
                [row["available_valid_start_span_s"] for row in partial]
            ),
            "diagnostic_selected_start_span_s_for_capable_partial_blocks": _quantiles(
                [row["diagnostic_selected_start_span_s"] for row in partial]
            ),
        }
    result["block_identity"] = {
        "duration_s": block_duration,
        "unchanged": True,
        "bootstrap_must_resample_whole_blocks": True,
        "window_level_Wilson_independence_established": False,
    }
    return result


def v5_training_spacing(v5_split_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_block: dict[tuple[str, int], list[float]] = defaultdict(list)
    for row in v5_split_rows:
        if row.get("partition") != "training" or row.get("role") != "background":
            continue
        by_block[(str(row["detector"]), int(row["stratum"]["block_index"]))].append(
            float(row["window"]["gps_start"])
        )
    result: dict[str, Any] = {}
    for detector in DETECTORS:
        spans = []
        gaps = []
        for (current, _block), starts in by_block.items():
            if current != detector:
                continue
            ordered = sorted(starts)
            if len(ordered) != 8:
                raise ContractError("v5 training block does not contain eight windows")
            spans.append(ordered[-1] - ordered[0])
            gaps.extend(np.diff(ordered).tolist())
        result[detector] = {
            "block_count": len(spans),
            "selected_start_span_s": _quantiles(spans),
            "adjacent_start_gap_s": _quantiles(gaps),
        }
    return result


def ranknet_block_loss(
    predictions: torch.Tensor, targets: torch.Tensor
) -> torch.Tensor:
    if predictions.shape != targets.shape or predictions.ndim != 3:
        raise ContractError("RankNet diagnostic expects (detector, block, window)")
    if predictions.shape[0] != 2 or predictions.shape[2] != 8:
        raise ContractError("RankNet diagnostic block structure mismatch")
    first, second = torch.triu_indices(8, 8, offset=1, device=predictions.device)
    block_losses = []
    for detector in range(predictions.shape[0]):
        detector_losses = []
        for block in range(predictions.shape[1]):
            prediction = predictions[detector, block]
            target = targets[detector, block]
            signs = torch.sign(target[first] - target[second])
            keep = signs != 0
            if not torch.any(keep):
                raise ContractError("RankNet diagnostic block contains only target ties")
            differences = prediction[first[keep]] - prediction[second[keep]]
            detector_losses.append(F.softplus(-signs[keep] * differences).mean())
        block_losses.append(torch.stack(detector_losses).mean())
    return torch.stack(block_losses).mean()


def smooth_l1_detector_loss(
    predictions: torch.Tensor, targets: torch.Tensor, *, beta: float
) -> torch.Tensor:
    if predictions.shape != targets.shape or predictions.ndim != 3:
        raise ContractError("SmoothL1 diagnostic block structure mismatch")
    return torch.stack(
        [F.smooth_l1_loss(predictions[index], targets[index], beta=beta) for index in range(2)]
    ).mean()


def l2_gradient_norm(parameters: Iterable[torch.nn.Parameter]) -> float:
    total = 0.0
    for parameter in parameters:
        if parameter.grad is not None:
            total += float(torch.sum(parameter.grad.detach() ** 2).item())
    return math.sqrt(total)
