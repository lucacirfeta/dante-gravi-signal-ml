"""Exact matched-control transport geometry; no statistic or outcome selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256


def transport_intervals(
    blocks: Sequence[Mapping[str, Any]], duration: int
) -> list[list[int]]:
    """Merge containers, never statistical blocks, and never fill a rejected gap."""
    accepted = [b["context_starts_gps"] for b in blocks if b["eligible"]]
    starts = [s for b in accepted for s in b]
    if duration <= 0 or not starts or starts != sorted(set(starts)):
        raise ContractError("matched transport contexts unordered/duplicated/empty")
    grouped: list[list[int]] = []
    for start in starts:
        if not isinstance(start, int):
            raise ContractError("matched transport context GPS invalid")
        if grouped and start < grouped[-1][1]:
            raise ContractError("matched transport contexts overlap")
        if grouped and start == grouped[-1][1]:
            grouped[-1][1] = start + duration
        else:
            grouped.append([start, start + duration])
    if sum(end - start for start, end in grouped) != len(starts) * duration:
        raise ContractError("matched transport changes context exposure")
    return grouped


def auxiliary_specs(
    intervals: Sequence[Sequence[int]],
    *,
    channels: Sequence[str],
    rates: Mapping[str, int],
    target_gps: int,
) -> list[dict]:
    if (
        not channels
        or len(set(channels)) != len(channels)
        or set(channels) != set(rates)
        or any(not name.startswith("L1:") for name in channels)
    ):
        raise ContractError("matched native auxiliary channel set changed")
    specs = []
    for start, end in intervals:
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            raise ContractError("matched native auxiliary interval invalid")
        for channel in channels:
            rate = rates[channel]
            if not isinstance(rate, int) or rate <= 0:
                raise ContractError("matched native auxiliary rate invalid")
            identity = {
                "run": "O3a",
                "detector": "L1",
                "channel": channel,
                "interval_gps": [start, end],
            }
            specs.append(
                {
                    "key": canonical_json_sha256(identity),
                    **identity,
                    "sample_rate_hz": rate,
                    "sample_count": (end - start) * rate,
                    "uses": [{"target_gps": target_gps, "role": "background"}],
                }
            )
    if len({s["key"] for s in specs}) != len(specs):
        raise ContractError("matched native auxiliary duplicate interval")
    return specs
