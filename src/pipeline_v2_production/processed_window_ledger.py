"""Coverage ledgers for catalogue cross-checks.

New scans persist every successfully scored 32 s window in the production HDF5
file. Historical scans predate that ledger; raw-block coverage can be
reconstructed as an explicitly labelled proxy, but must never be called exact
processed coverage.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import h5py

from src.core.data_loader import _DATA_DIRECTORIES

WINDOW_LENGTH_S = 32.0


def merge_intervals(
    intervals: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    valid = sorted((float(start), float(end)) for start, end in intervals if end > start)
    merged: list[tuple[float, float]] = []
    for start, end in valid:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _summary(
    detector: str,
    intervals: list[tuple[float, float]],
    *,
    source: str,
    quality: str,
    n_windows: int | None,
    files: list[str],
) -> dict:
    merged = merge_intervals(intervals)
    livetime_s = float(sum(end - start for start, end in merged))
    return {
        "detector": detector,
        "source": source,
        "quality": quality,
        "window_length_s": WINDOW_LENGTH_S,
        "n_windows": n_windows,
        "n_merged_intervals": len(merged),
        "livetime_s": livetime_s,
        "livetime_days": livetime_s / 86400.0,
        "files": files,
        "intervals": [[start, end] for start, end in merged],
    }


def load_exact_processed_coverage(
    production_dir: str | Path,
    detector: str,
) -> dict | None:
    """Load exact successfully-scored windows from new production HDF5 files."""
    production_dir = Path(production_dir)
    gps_values: set[float] = set()
    sources: list[str] = []
    pattern = f"novelties_*_{detector}.h5"
    for path in production_dir.glob(f"*/{pattern}"):
        try:
            with h5py.File(path, "r") as handle:
                if "processed_windows/gps_times" not in handle:
                    continue
                values = handle["processed_windows/gps_times"][:]
                gps_values.update(float(value) for value in values)
                sources.append(str(path))
        except (OSError, KeyError):
            continue
    if not sources:
        return None
    intervals = [(gps, gps + WINDOW_LENGTH_S) for gps in sorted(gps_values)]
    return _summary(
        detector,
        intervals,
        source="processed_windows_hdf5",
        quality="exact_successfully_scored_windows",
        n_windows=len(gps_values),
        files=sources,
    )


def _completed_sessions(production_dir: Path, detector: str) -> set[str]:
    sessions: set[str] = set()
    pattern = f"last_gps_*_{detector}.txt"
    for path in production_dir.glob(f"*/checkpoints/{pattern}"):
        try:
            if path.read_text(encoding="utf-8").strip() == "DONE":
                sessions.add(path.parents[1].name)
        except OSError:
            continue
    return sessions


def reconstruct_raw_block_coverage(
    production_dir: str | Path,
    detector: str,
    *,
    data_directories: list[Path] | None = None,
) -> dict | None:
    """Reconstruct a labelled upper-bound proxy from completed raw blocks.

    The proxy knows which raw blocks belonged to completed sessions but cannot
    identify individual NaN/zero windows or rare preprocessing failures in
    historical runs. It is therefore not exact processed coverage.
    """
    production_dir = Path(production_dir)
    sessions = _completed_sessions(production_dir, detector)
    if not sessions:
        return None
    directories = data_directories or list(_DATA_DIRECTORIES)
    window_starts: set[float] = set()
    sources: set[str] = set()
    for root in directories:
        if not root.exists():
            continue
        for session in sorted(sessions):
            session_dir = root / session
            if not session_dir.exists():
                continue
            for path in session_dir.rglob(f"{detector}_*.hdf5"):
                parts = path.stem.split("_")
                if len(parts) < 3:
                    continue
                try:
                    start, end = float(parts[-2]), float(parts[-1])
                except ValueError:
                    continue
                n_windows = int((end - start) // WINDOW_LENGTH_S)
                if n_windows < 1:
                    continue
                for index in range(n_windows):
                    window_starts.add(start + index * WINDOW_LENGTH_S)
                sources.add(str(path))
    if not sources:
        return None
    intervals = [
        (start, start + WINDOW_LENGTH_S)
        for start in sorted(window_starts)
    ]
    return _summary(
        detector,
        intervals,
        source="completed_session_raw_blocks",
        quality=(
            "upper_bound_proxy_excludes_no_nan_zero_or_preprocessing_failures"
        ),
        n_windows=len(window_starts),
        files=sorted(sources),
    )


def load_legacy_session_spans(
    production_dir: str | Path,
    detector: str,
) -> dict | None:
    """Load the pre-audit session-span proxy for explicit comparison only."""
    production_dir = Path(production_dir)
    intervals: list[tuple[float, float]] = []
    sources: list[str] = []
    for filename in glob.glob(
        str(production_dir / "*" / f"cluster_report_novelties_*_{detector}.json")
    ):
        path = Path(filename)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            start = payload.get("session_start_gps")
            end = payload.get("session_end_gps")
            if start is not None and end is not None:
                intervals.append((float(start), float(end)))
                sources.append(str(path))
        except (json.JSONDecodeError, OSError, ValueError):
            continue
    if not sources:
        return None
    return _summary(
        detector,
        intervals,
        source="cluster_report_session_spans",
        quality="legacy_proxy_includes_unprocessed_gaps",
        n_windows=None,
        files=sources,
    )


def resolve_coverage(
    production_dir: str | Path,
    detector: str,
    *,
    source: str = "auto",
    data_directories: list[Path] | None = None,
) -> dict:
    """Resolve coverage with an explicit quality hierarchy."""
    if source not in {"auto", "exact", "raw-blocks", "legacy-spans"}:
        raise ValueError(f"Unknown coverage source {source!r}")
    exact = load_exact_processed_coverage(production_dir, detector)
    if source in {"auto", "exact"} and exact is not None:
        return exact
    if source == "exact":
        raise RuntimeError(
            f"No exact processed-window ledger exists for {detector}. "
            "The historical scan must be rerun or a proxy selected explicitly."
        )
    if source in {"auto", "raw-blocks"}:
        proxy = reconstruct_raw_block_coverage(
            production_dir,
            detector,
            data_directories=data_directories,
        )
        if proxy is not None:
            return proxy
    if source == "raw-blocks":
        raise RuntimeError(f"No completed raw-block coverage found for {detector}")
    legacy = load_legacy_session_spans(production_dir, detector)
    if legacy is None:
        raise RuntimeError(f"No coverage information found for {detector}")
    return legacy
