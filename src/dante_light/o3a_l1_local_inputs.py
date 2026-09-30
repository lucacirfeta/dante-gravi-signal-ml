"""Outcome-blind local follow-up DQ/auxiliary metadata input gate.

Coverage is not a validation of sample bytes, sensor safety or physical cause.
All blocks are accounted for before any new local coherence is calculated.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from src.dante_light.contracts import ContractError


def normalize_segments(
    segments: Sequence[Sequence[float]], bounds: Sequence[int]
) -> list[list[int]]:
    """Validate, clip and union half-open integer-second source coverage."""
    start, end = bounds
    if not isinstance(start, int) or not isinstance(end, int) or start >= end:
        raise ContractError("input coverage query bounds invalid")
    clipped = []
    for interval in segments:
        if len(interval) != 2:
            raise ContractError("input coverage interval malformed")
        left, right = interval
        if not all(math.isfinite(x) and int(x) == x for x in interval) or left >= right:
            raise ContractError("input coverage interval invalid")
        left, right = max(start, int(left)), min(end, int(right))
        if left < right:
            clipped.append([left, right])
    merged: list[list[int]] = []
    for left, right in sorted(clipped):
        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])
    return merged


def covers(segments: Sequence[Sequence[int]], interval: Sequence[float]) -> bool:
    left, right = interval
    if not math.isfinite(left) or not math.isfinite(right) or left >= right:
        raise ContractError("required coverage interval invalid")
    return any(start <= left and right <= end for start, end in segments)


def auxiliary_metadata(
    availability: Sequence[Any], channels: Sequence[str], bounds: Sequence[int]
) -> dict[str, Any]:
    """Preserve native NDS2 metadata and gaps; absent channels are not negative."""
    names = [item.name for item in availability]
    if len(names) != len(set(names)) or set(names) - set(channels):
        raise ContractError("input NDS2 channel identity duplicated or unexpected")
    found = {item.name: item for item in availability}
    result = {}
    for name in channels:
        rows = []
        if name in found:
            for piece in found[name].data:
                if not isinstance(piece.frame_type, str) or not piece.frame_type:
                    raise ContractError("input NDS2 frame type missing")
                rows.append(
                    {
                        "gps_start": piece.gps_start,
                        "gps_end": piece.gps_stop,
                        "frame_type": piece.frame_type,
                    }
                )
        result[name] = {
            "present": name in found,
            "source_segments": rows,
            "coverage_segments": normalize_segments(
                [[r["gps_start"], r["gps_end"]] for r in rows], bounds
            ),
        }
    return result


def assess_inputs(
    target: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    channels: Sequence[str],
    quality: Mapping[str, Sequence[Sequence[int]]],
    auxiliary: Mapping[str, Any],
) -> dict[str, Any]:
    """Select complete controls by frozen DQ/coverage only, never by T."""
    flags = design["input_preflight"]["quality_flags"]
    if set(quality) != set(flags) or set(auxiliary) != set(channels):
        raise ContractError("input gate flag/channel set changed")
    segment = target["same_cat1_segment_gps"]
    normalized = {
        key: normalize_segments(value, segment) for key, value in quality.items()
    }
    if normalized["L1_CBC_CAT1"] != [segment]:
        raise ContractError("live CBC_CAT1 differs from frozen contiguous segment")
    duration = design["controls"]["context_duration_s"]
    offset = target["local_offset_interval_s"]
    blocks = target["candidate_clean_control_blocks_gps"]
    if (
        len(blocks) != target["candidate_clean_blocks_before_cat2_cat3"]
        or len({tuple(b) for b in blocks}) != len(blocks)
        or not 0 <= offset[0] < offset[1] <= duration
    ):
        raise ContractError("input control accounting/region changed")
    rows = []
    for block in blocks:
        if (
            len(block) != design["controls"]["contexts_per_block"]
            or any(b - a != duration for a, b in zip(block, block[1:]))
            or not segment[0] <= block[0] < block[-1] + duration <= segment[1]
        ):
            raise ContractError("input control block geometry changed")
        reasons = []
        for start in block:
            if not covers(normalized["L1_CBC_CAT1"], [start, start + duration]):
                raise ContractError("input control CAT1 context changed")
            local = [start + offset[0], start + offset[1]]
            reasons.extend(
                flag for flag in flags if not covers(normalized[flag], local)
            )
            reasons.extend(
                f"AUX_METADATA_GAP:{channel}"
                for channel in channels
                if not covers(
                    auxiliary[channel]["coverage_segments"], [start, start + duration]
                )
            )
        rows.append(
            {
                "context_starts_gps": block,
                "eligible": not reasons,
                "reasons": sorted(set(reasons)),
            }
        )
    gps = target["gps_start"]
    event_local = [gps + offset[0], gps + offset[1]]
    event_reasons = [
        flag for flag in flags if not covers(normalized[flag], event_local)
    ]
    event_reasons.extend(
        f"AUX_METADATA_GAP:{channel}"
        for channel in channels
        if not covers(auxiliary[channel]["coverage_segments"], [gps, gps + duration])
    )
    count = sum(row["eligible"] for row in rows)
    feasible = (
        count >= design["controls"]["minimum_reference_blocks"] and not event_reasons
    )
    return {
        "detector": target["detector"],
        "gps_start": gps,
        "identity_digest": target["identity_digest"],
        "status": "PASS_DQ_AUX_METADATA_ONLY"
        if feasible
        else "INCONCLUSIVE_INPUT_COVERAGE",
        "eligible_reference_blocks": count,
        "accounted_reference_blocks": len(rows),
        "blocks": rows,
        "event_coverage_reasons": sorted(event_reasons),
        "sample_bytes_verified": False,
        "channel_veto_safety_verified": False,
        "new_local_outcome_computed": False,
    }
