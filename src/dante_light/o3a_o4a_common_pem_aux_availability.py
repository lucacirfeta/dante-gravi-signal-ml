"""Metadata-only NDS2 availability checks for frozen common-PEM inputs.

This is a transport preflight. It neither fetches samples nor certifies the
auxiliary time series that will enter the paired PEM measurement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.dante_light.contracts import ContractError


def requirements(
    span_plan: Mapping[str, Any], comparison: Mapping[str, Any]
) -> list[dict]:
    """Derive event and background intervals from sealed, frozen inputs only."""
    window = int(comparison["method"]["measurement"]["event_window_s"])
    if window <= 0:
        raise ContractError("common PEM event window is invalid")
    rows: list[dict] = []
    for run in ("O3a", "O4a"):
        spans = span_plan["spans"][run]
        if len(spans) != comparison["runs"][run]["targets"]["expected_count"]:
            raise ContractError("common PEM auxiliary target population changed")
        for span in spans:
            detector = span["detector"]
            if detector not in ("H1", "L1"):
                raise ContractError("common PEM auxiliary detector changed")
            channels = comparison["method"]["channels"][detector]
            if len(channels) != len(set(channels)) or not all(
                name.startswith(f"{detector}:") for name in channels
            ):
                raise ContractError("common PEM auxiliary channel set changed")
            gps = int(span["gps_start"])
            left, right = (int(value) for value in span["interval_gps"])
            if gps != span["gps_start"] or right <= left:
                raise ContractError("common PEM auxiliary interval is invalid")
            rows.append(
                {
                    "run": run,
                    "detector": detector,
                    "target_gps": gps,
                    "channels": channels,
                    "event_interval_gps": [gps, gps + window],
                    "background_interval_gps": [left, right],
                }
            )
    return rows


def check_availability(
    availability: Sequence[Any], channels: Sequence[str], start: int, end: int
) -> list[dict]:
    """Require exact channel identities and gap-free coverage of an interval."""
    if end <= start or len(set(channels)) != len(channels):
        raise ContractError("common PEM auxiliary availability request is invalid")
    found = {item.name: item for item in availability}
    if len(found) != len(availability) or set(found) != set(channels):
        raise ContractError("common PEM auxiliary availability channel set changed")
    result: list[dict] = []
    for name in channels:
        cursor = start
        segments: list[dict] = []
        for item in sorted(found[name].data, key=lambda seg: seg.gps_start):
            left, right = int(item.gps_start), int(item.gps_stop)
            if right <= left or left > cursor:
                raise ContractError(f"common PEM auxiliary coverage gap: {name}")
            if right <= cursor:
                continue
            if not isinstance(item.frame_type, str) or not item.frame_type:
                raise ContractError(f"common PEM auxiliary frame type absent: {name}")
            segments.append(
                {"gps_start": left, "gps_end": right, "frame_type": item.frame_type}
            )
            cursor = right
            if cursor >= end:
                break
        if cursor < end:
            raise ContractError(f"common PEM auxiliary coverage incomplete: {name}")
        result.append({"channel": name, "segments": segments})
    return result
