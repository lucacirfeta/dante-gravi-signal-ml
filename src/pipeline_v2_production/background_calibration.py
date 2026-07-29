"""Run-bounded, leakage-aware planning for DSD threshold backgrounds.

The threshold population is a scientific calibration sample, not a generic
cache of locally available strain. This module keeps the selection logic pure
and testable before any expensive strain read or model scoring occurs.
"""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
from math import ceil
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class RawBlock:
    """One locally available strain file with GPS bounds."""

    gps_start: float
    gps_end: float
    path: Path


@dataclass(frozen=True)
class CalibrationWindow:
    """One planned 32 s threshold-calibration window."""

    gps_start: float
    gps_end: float
    source_path: Path
    source_start: float
    source_end: float

    def as_record(self) -> dict[str, object]:
        return {
            "gps_start": float(self.gps_start),
            "gps_end": float(self.gps_end),
            "source_path": str(self.source_path),
            "source_start": float(self.source_start),
            "source_end": float(self.source_end),
        }


@dataclass(frozen=True)
class CalibrationBlock:
    """A complete contiguous block used as one bootstrap resampling unit."""

    windows: tuple[CalibrationWindow, ...]

    @property
    def gps_start(self) -> float:
        return self.windows[0].gps_start


def resolve_run_bounds(
    config: Mapping[str, object],
    run_name: str,
) -> tuple[float, float]:
    """Resolve explicit GPS bounds for a run or refuse implicit inference."""

    run_config = config.get("run_config", {})
    if isinstance(run_config, Mapping):
        entry = run_config.get(run_name)
        if isinstance(entry, Mapping):
            if "gps_start" in entry and "gps_end" in entry:
                start = float(entry["gps_start"])
                end = float(entry["gps_end"])
                if end <= start:
                    raise ValueError(f"Invalid GPS bounds for run {run_name!r}")
                return start, end

    if run_name.lower() == "o4a":
        entry = config.get("o4a_window", {})
        if isinstance(entry, Mapping):
            if "gps_start" in entry and "gps_end" in entry:
                start = float(entry["gps_start"])
                end = float(entry["gps_end"])
                if end <= start:
                    raise ValueError("Invalid O4a GPS bounds")
                return start, end

    raise ValueError(
        f"Run {run_name!r} requires explicit gps_start/gps_end in config.yaml"
    )


def _is_guarded_from_forbidden(
    start: float,
    end: float,
    forbidden_intervals: Sequence[tuple[float, float, str]],
    guard_s: float,
) -> bool:
    for forbidden_start, forbidden_end, _label in forbidden_intervals:
        if not (
            end + guard_s <= float(forbidden_start)
            or start >= float(forbidden_end) + guard_s
        ):
            return False
    return True


def _merged_forbidden(
    forbidden_intervals: Sequence[tuple[float, float, str]],
    guard_s: float,
) -> tuple[list[float], list[tuple[float, float]]]:
    expanded = sorted(
        (float(start) - guard_s, float(end) + guard_s)
        for start, end, _label in forbidden_intervals
    )
    merged: list[tuple[float, float]] = []
    for start, end in expanded:
        if end <= start:
            raise ValueError("Forbidden intervals must be increasing")
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return [start for start, _end in merged], merged


def _is_clear_of_merged(
    start: float,
    end: float,
    forbidden_starts: Sequence[float],
    merged_forbidden: Sequence[tuple[float, float]],
) -> bool:
    position = bisect_left(forbidden_starts, end)
    if position == 0:
        return True
    return merged_forbidden[position - 1][1] <= start


def _contiguous_runs(
    windows: Sequence[CalibrationWindow],
    stride_s: float,
) -> list[list[CalibrationWindow]]:
    if not windows:
        return []
    runs: list[list[CalibrationWindow]] = [[windows[0]]]
    for window in windows[1:]:
        if np.isclose(
            window.gps_start - runs[-1][-1].gps_start,
            stride_s,
            atol=1e-9,
            rtol=0.0,
        ):
            runs[-1].append(window)
        else:
            runs.append([window])
    return runs


def build_calibration_block_plan(
    records: Sequence[RawBlock],
    *,
    target_n: int,
    run_bounds: tuple[float, float],
    forbidden_intervals: Sequence[tuple[float, float, str]],
    guard_s: float,
    block_length: int | None = None,
    pad_s: float = 4.0,
    window_s: float = 32.0,
    stride_s: float = 64.0,
) -> list[CalibrationBlock]:
    """Build a full-run-stratified priority list of complete temporal blocks."""

    if target_n < 2:
        raise ValueError("target_n must be at least 2")
    if window_s <= 0 or stride_s <= 0 or pad_s < 0 or guard_s < 0:
        raise ValueError("Window, stride, pad and guard must be valid")
    run_start, run_end = (float(run_bounds[0]), float(run_bounds[1]))
    if run_end <= run_start:
        raise ValueError("run_bounds must be increasing")

    length = block_length or max(1, int(target_n ** (1 / 3)))
    if length < 1:
        raise ValueError("block_length must be positive")

    forbidden_starts, merged_forbidden = _merged_forbidden(
        forbidden_intervals,
        guard_s,
    )
    available: list[CalibrationBlock] = []
    first_offset = float(ceil(pad_s))
    for record in sorted(records, key=lambda item: (item.gps_start, str(item.path))):
        raw_start = float(record.gps_start)
        raw_end = float(record.gps_end)
        if raw_end <= run_start or raw_start >= run_end:
            continue

        starts = np.arange(
            raw_start + first_offset,
            raw_end - window_s - float(ceil(pad_s)) + 1e-9,
            stride_s,
            dtype=np.float64,
        )
        windows: list[CalibrationWindow] = []
        for start in starts:
            end = float(start + window_s)
            if start < run_start or end > run_end:
                continue
            if not _is_clear_of_merged(
                float(start),
                end,
                forbidden_starts,
                merged_forbidden,
            ):
                continue
            windows.append(
                CalibrationWindow(
                    gps_start=float(start),
                    gps_end=end,
                    source_path=record.path,
                    source_start=raw_start,
                    source_end=raw_end,
                )
            )

        for run in _contiguous_runs(windows, stride_s):
            for offset in range(0, len(run), length):
                chunk = run[offset : offset + length]
                if len(chunk) == length:
                    available.append(CalibrationBlock(tuple(chunk)))

    # Raw archives can contain mirrors or partially overlapping files. Keep one
    # temporally independent block at each epoch so duplicated storage cannot
    # increase the calibration weight of the same strain.
    available.sort(
        key=lambda block: (
            block.gps_start,
            str(block.windows[0].source_path),
        )
    )
    independent: list[CalibrationBlock] = []
    previous_end = float("-inf")
    for block in available:
        if block.windows[0].gps_start >= previous_end:
            independent.append(block)
            previous_end = block.windows[-1].gps_end
    available = independent

    n_blocks_needed = int(ceil(target_n / length))
    if len(available) < n_blocks_needed:
        raise RuntimeError(
            f"Only {len(available)} complete calibration blocks available; "
            f"{n_blocks_needed} required for {target_n} windows"
        )

    selected_indices = np.unique(
        np.linspace(
            0,
            len(available) - 1,
            num=n_blocks_needed,
            dtype=int,
        )
    ).tolist()
    selected = set(selected_indices)
    priority = selected_indices + [
        index for index in range(len(available)) if index not in selected
    ]
    return [available[index] for index in priority]


def validate_calibration_ledger(
    windows: Sequence[CalibrationWindow],
    *,
    run_bounds: tuple[float, float],
    forbidden_intervals: Sequence[tuple[float, float, str]],
    guard_s: float,
) -> dict[str, int]:
    """Return hard-failure counts for a completed calibration ledger."""

    run_start, run_end = run_bounds
    outside = 0
    forbidden = 0
    forbidden_starts, merged_forbidden = _merged_forbidden(
        forbidden_intervals,
        guard_s,
    )
    for window in windows:
        if window.gps_start < run_start or window.gps_end > run_end:
            outside += 1
        if not _is_clear_of_merged(
            window.gps_start,
            window.gps_end,
            forbidden_starts,
            merged_forbidden,
        ):
            forbidden += 1
    ordered = sorted(
        windows,
        key=lambda window: (window.gps_start, window.gps_end),
    )
    self_overlap = sum(
        current.gps_start < previous.gps_end
        for previous, current in zip(ordered, ordered[1:])
    )
    return {
        "n_windows": len(windows),
        "outside_run": outside,
        "forbidden_overlap": forbidden,
        "self_overlap": self_overlap,
    }
