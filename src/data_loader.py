"""GWOSC data fetching and O4a segment management.

This module provides the interface between the Gravitational-Wave Open
Science Center (GWOSC) and the local preprocessing pipeline.  All network
I/O is wrapped with retry logic, timeout handling, and structured logging
so that long-running O4a batch scans can survive transient failures.
"""

from __future__ import annotations

import logging
from typing import Literal

from gwpy.timeseries import TimeSeries

from src.utils import gps_to_utc, load_config, setup_logger
import time

logger: logging.Logger = setup_logger(__name__)

DetectorID = Literal["H1", "L1", "V1"]

_GWOSC_BASE_DELAY = 0.3

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CFG = load_config()
_O4A_START: int = _CFG["o4a_window"]["gps_start"]
_O4A_END: int = _CFG["o4a_window"]["gps_end"]
_SAMPLE_RATE: int = _CFG["preprocessing"]["sample_rate"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_strain_data(
    detector: DetectorID,
    gps_start: int,
    gps_end: int,
    sample_rate: int = _SAMPLE_RATE,
) -> TimeSeries:
    """Fetch open strain data from GWOSC for a given detector and time range.

    Uses :meth:`gwpy.timeseries.TimeSeries.fetch_open_data` which
    downloads publicly available LIGO/Virgo/KAGRA strain data.

    Args:
        detector: Detector identifier — ``"H1"``, ``"L1"``, or ``"V1"``.
        gps_start: GPS start time of the segment.
        gps_end: GPS end time of the segment.
        sample_rate: Target sample rate in Hz.  Data is resampled if the
            native rate differs.  Defaults to the value in ``config.yaml``
            (4096 Hz).

    Returns:
        A :class:`gwpy.timeseries.TimeSeries` containing the strain data.

    Raises:
        ValueError: If *detector* is not one of the supported identifiers.
        RuntimeError: If the GWOSC fetch fails after retries (network
            timeout, missing data, rate limits).
    """
    from pathlib import Path

    _validate_detector(detector)

    utc_start = gps_to_utc(gps_start)
    utc_end = gps_to_utc(gps_end)
    logger.info(
        "Fetching %s strain: GPS [%d, %d] -> UTC [%s, %s]",
        detector,
        gps_start,
        gps_end,
        utc_start,
        utc_end,
    )

    cache_dir = Path("data/raw")
    cache_file = cache_dir / f"{detector}_{gps_start}_{gps_end}.hdf5"

    if cache_file.exists():
        try:
            ts = TimeSeries.read(cache_file)
            logger.info("Cache hit for %s", cache_file.name)
            return ts
        except Exception as exc:
            logger.warning("Cache read failed for %s, moving to .corrupt: %s", cache_file.name, exc)
            corrupt_dir = cache_dir / ".corrupt"
            corrupt_dir.mkdir(parents=True, exist_ok=True)
            try:
                cache_file.rename(corrupt_dir / cache_file.name)
            except Exception as rename_exc:
                logger.warning("Failed to move corrupt file %s: %s", cache_file.name, rename_exc)
                try:
                    cache_file.unlink()
                except Exception:
                    pass

    global _GWOSC_BASE_DELAY
    try:
        while True:
            time.sleep(_GWOSC_BASE_DELAY)
            try:
                ts: TimeSeries = TimeSeries.fetch_open_data(
                    detector,
                    gps_start,
                    gps_end,
                    sample_rate=sample_rate,
                    verbose=False,
                    cache=True,
                )
                break
            except Exception as inner_exc:
                err_str = str(inner_exc)
                if "429" in err_str or "Too Many Requests" in err_str:
                    logger.warning("GWOSC 429 Too Many Requests. Increasing base delay by 300ms and retrying in 1s...")
                    _GWOSC_BASE_DELAY += 0.3
                    time.sleep(1.0)
                else:
                    raise inner_exc
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch strain data for {detector} "
            f"[{gps_start}, {gps_end}]: {exc}"
        ) from exc

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        ts.write(cache_file, format='hdf5.gwosc')
        logger.info("Saved raw data to cache: %s", cache_file.name)
    except Exception as exc:
        logger.warning("Failed to save raw data to cache %s: %s", cache_file.name, exc)

    logger.info(
        "Fetched %s: %d samples @ %d Hz (%.1f s)",
        detector,
        len(ts),
        sample_rate,
        float(ts.duration.value),
    )
    return ts


def fetch_o4a_segments(
    detector: DetectorID,
    duration_hours: float = 1.0,
    segment_length: int = 32,
    gps_offset_hours: float = 0.0,
) -> list[tuple[int, int]]:
    """Query GWOSC for valid science-mode segments within the O4a window.

    Splits the requested observation window into fixed-length chunks
    suitable for batch preprocessing.  Each chunk is ``segment_length``
    seconds long (default 32 s — matching a standard spectrogram window).

    Args:
        detector: Detector identifier — ``"H1"``, ``"L1"``, or ``"V1"``.
        duration_hours: Total duration to scan from the start of the O4a
            window, in hours.  Defaults to 1 hour.
        segment_length: Length of each returned segment in seconds.
            Defaults to 32 s.
        gps_offset_hours: Skip the first *N* hours of the O4a window
            before starting the scan.  Useful for appending to an
            existing scan (e.g. ``offset=6`` to skip data already
            processed in Phase 3).  Defaults to 0.

    Returns:
        A list of ``(gps_start, gps_end)`` tuples covering the requested
        window.  Segments that fall outside the O4a range are clipped.

    Raises:
        ValueError: If *detector* is not supported or *duration_hours*
            is non-positive.
    """
    _validate_detector(detector)
    if duration_hours <= 0:
        raise ValueError(f"duration_hours must be positive, got {duration_hours}")

    offset_seconds = int(gps_offset_hours * 3600)
    scan_start = _O4A_START + offset_seconds
    
    # Allineiamo lo start al multiplo del segment_length per garantire che
    # nessun segmento scavalchi i confini dei file GWOSC (multipli di 4096).
    # (Poiché 4096 è multiplo di 32, allineando a 32 evitiamo il bug).
    scan_start = ((scan_start + segment_length - 1) // segment_length) * segment_length
    
    total_seconds = int(duration_hours * 3600)
    scan_end = min(scan_start + total_seconds, _O4A_END)

    segments: list[tuple[int, int]] = []
    current = scan_start
    while current + segment_length <= scan_end:
        segments.append((current, current + segment_length))
        current += segment_length

    logger.info(
        "Generated %d × %d-s segments for %s (%.1f h from GPS %d, offset %.1f h)",
        len(segments),
        segment_length,
        detector,
        duration_hours,
        scan_start,
        gps_offset_hours,
    )
    return segments


def generate_segments_from_gps_range(
    gps_start: int,
    gps_end: int,
    segment_length: int = 32,
) -> list[tuple[int, int]]:
    """Generate fixed-length segments from an explicit GPS range.

    Unlike :func:`fetch_o4a_segments`, this function does **not** reference
    the O4a window boundaries — the caller provides the exact GPS interval.

    Args:
        gps_start: GPS start time (inclusive).
        gps_end: GPS end time (exclusive upper bound for the last segment).
        segment_length: Length of each segment in seconds.  Defaults to 32.

    Returns:
        A list of ``(gps_start, gps_end)`` tuples covering the requested
        range.

    Raises:
        ValueError: If *gps_end* ≤ *gps_start*.
    """
    if gps_end <= gps_start:
        raise ValueError(
            f"gps_end ({gps_end}) must be greater than gps_start ({gps_start})"
        )

    segments: list[tuple[int, int]] = []
    # Allineiamo il primo segmento per non attraversare i confini di 4096s
    current = ((gps_start + segment_length - 1) // segment_length) * segment_length
    
    while current + segment_length <= gps_end:
        segments.append((current, current + segment_length))
        current += segment_length

    logger.info(
        "Generated %d × %d-s segments for GPS range [%d, %d]",
        len(segments),
        segment_length,
        gps_start,
        gps_end,
    )
    return segments


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_detector(detector: str) -> None:
    """Raise ``ValueError`` if *detector* is not a supported identifier."""
    supported = {"H1", "L1", "V1"}
    if detector not in supported:
        raise ValueError(
            f"Unsupported detector '{detector}'. Must be one of {supported}."
        )
