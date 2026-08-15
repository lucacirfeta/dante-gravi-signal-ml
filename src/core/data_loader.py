"""GWOSC data fetching and O4a segment management.

This module provides the interface between the Gravitational-Wave Open
Science Center (GWOSC) and the local preprocessing pipeline.  All network
I/O is wrapped with retry logic, timeout handling, and structured logging
so that long-running O4a batch scans can survive transient failures.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

from gwpy.timeseries import TimeSeries

from src.core.utils import gps_to_utc, load_config, setup_logger
import time
import socket

# Imposta un timeout globale di 60 secondi per evitare che gwpy/requests
# rimangano appesi all'infinito in caso di network stall dal server GWOSC
socket.setdefaulttimeout(60.0)

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
_DATA_DIRECTORIES_CFG = _CFG.get("data_loading", {}).get("local_directories", [
    "E:/o4a",
    "/mnt/e/o4a",
    "data/raw",
])
# Machine-specific raw archives (external disks, other checkouts) are
# supplied via the DANTE_DATA_DIRS environment variable (os.pathsep-
# separated), searched BEFORE the repo-config directories.
_ENV_DATA_DIRS = [d for d in os.environ.get("DANTE_DATA_DIRS", "").split(os.pathsep) if d]
_DATA_DIRECTORIES: list[Path] = [Path(d) for d in _ENV_DATA_DIRS + list(_DATA_DIRECTORIES_CFG)]



# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# Per-process index of local raw blocks: {(dir, detector): [(start, end, Path)]}.
# The raw archives (E:/o4a) are immutable during a run, and the previous
# rglob-per-call scanned ~3600 files on EVERY fetch inside production loops.
# New cache_raw saves are registered via _register_local_block().
_LOCAL_BLOCK_INDEX: dict = {}


def _local_block_index(dir_path: Path, detector: str) -> list:
    key = (str(dir_path), detector)
    if key not in _LOCAL_BLOCK_INDEX:
        entries = []
        for file in dir_path.rglob(f"{detector}_*.hdf5"):
            parts = file.stem.split("_")
            if len(parts) >= 3:
                try:
                    entries.append((float(parts[1]), float(parts[2]), file))
                except ValueError:
                    continue
        entries.sort()
        _LOCAL_BLOCK_INDEX[key] = entries
        logger.debug("Indexed %d local %s blocks in %s", len(entries), detector, dir_path)
    return _LOCAL_BLOCK_INDEX[key]


def _register_local_block(file: Path, detector: str) -> None:
    """Keep the in-process index coherent when cache_raw writes a new block."""
    parts = file.stem.split("_")
    if len(parts) < 3:
        return
    try:
        entry = (float(parts[1]), float(parts[2]), file)
    except ValueError:
        return
    for (dir_str, det), entries in _LOCAL_BLOCK_INDEX.items():
        if det == detector and str(file).startswith(dir_str):
            entries.append(entry)
            entries.sort()


def fetch_strain_data(
        detector: DetectorID,
        gps_start: int,
        gps_end: int,
        sample_rate: int = _SAMPLE_RATE,
        cache_raw: bool = False,
        local_only: bool = False,
        remote_only: bool = False,
        edge_tolerance: float = 0.0,
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
    _validate_detector(detector)
    if local_only and remote_only:
        raise ValueError("local_only and remote_only are mutually exclusive")

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

    # 1. Tenta il caricamento da un blocco locale più grande (es. O4a 4096s) sui drive prioritari
    directories = [] if remote_only else _DATA_DIRECTORIES

    for dir_path in directories:
        if not dir_path.exists():
            continue

        try:
            for f_start, f_end, file in _local_block_index(dir_path, detector):
                if f_start <= gps_start + edge_tolerance and f_end >= gps_end - edge_tolerance:
                    try:
                        ts = TimeSeries.read(file)
                        crop_start = max(f_start, gps_start)
                        crop_end = min(f_end, gps_end)
                        ts_cropped = ts.crop(crop_start, crop_end)
                        if ts_cropped.sample_rate.value != sample_rate:
                            ts_cropped = ts_cropped.resample(sample_rate)
                        logger.info("Local block hit for %s covering [%d, %d] in %s", file.name, gps_start, gps_end, dir_path)
                        return ts_cropped
                    except Exception as exc:
                        logger.warning("Failed to read/crop local block %s: %s", file.name, exc)
        except Exception as exc:
            logger.warning(f"Error while searching in {dir_path}: {exc}")

    # 2. Controllo exact match nei _DATA_DIRECTORIES (nel caso non sia stato trovato dal rglob o sia formattato diversamente)
    cache_file_name = f"{detector}_{gps_start}_{gps_end}.hdf5"
    cache_file = None
    
    for dir_path in directories:
        if not dir_path.exists():
            continue
            
        target = dir_path / cache_file_name
        if target.exists():
            cache_file = target
            break
            
        # Also search in GPS subdirectories (dir_path/{gps_start}/)
        sub_matches = list(dir_path.glob(f"*/{cache_file_name}"))
        if sub_matches:
            cache_file = sub_matches[0]
            break

    if cache_file and cache_file.exists():
        try:
            ts = TimeSeries.read(cache_file)
            logger.info("Cache hit for %s in %s", cache_file.name, cache_file.parent)
            if ts.sample_rate.value != sample_rate:
                ts = ts.resample(sample_rate)
            return ts
        except Exception as exc:
            logger.warning("Cache read failed for %s, moving to .corrupt: %s", cache_file.name, exc)
            corrupt_dir = cache_file.parent / ".corrupt"
            corrupt_dir.mkdir(parents=True, exist_ok=True)
            try:
                cache_file.rename(corrupt_dir / cache_file.name)
            except Exception as rename_exc:
                logger.warning("Failed to move corrupt file %s: %s", cache_file.name, rename_exc)
                try:
                    cache_file.unlink()
                except Exception:
                    pass



    # === LOCAL ONLY MODE ===
    if local_only:
        raise RuntimeError(f"Local cache miss per {detector} [{gps_start}, {gps_end}]. GWOSC download disabilitato per velocizzare la run.")

    max_retries = 1
    base_delay = 1.0
    import random

    for attempt in range(max_retries):
        try:
            # Aggiungiamo un piccolo delay random per non colpire il server tutti i worker assieme
            time.sleep(random.uniform(1.0, 3.0))
            
            ts: TimeSeries = TimeSeries.fetch_open_data(
                detector,
                gps_start,
                gps_end,
                sample_rate=sample_rate,
                verbose=False,
                cache=True,
            )
            break  # Success
        except Exception as exc:
            err_str = str(exc)
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 2)
                logger.warning(
                    "Fetch error %s [%d-%d]: %s. "
                    "Retrying in %.1fs (Attempt %d/%d)",
                    detector, gps_start, gps_end, err_str, sleep_time, attempt+1, max_retries
                )
                time.sleep(sleep_time)
            else:
                raise RuntimeError(
                    f"Failed to fetch strain data for {detector} "
                    f"[{gps_start}, {gps_end}] after {max_retries} attempts: {exc}"
                ) from exc

    if cache_raw:
        try:
            # IMPORTANT: We MUST NOT write to the external directories (E:/o4a, /mnt/e/o4a) 
            # because they are read-only dataset storage.
            # Any new chunks downloaded from GWOSC must be cached locally in the project.
            cache_dir = Path("data/raw/o4a_cache")
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_write_path = cache_dir / cache_file_name
            ts.write(cache_write_path, format='hdf5')
            _register_local_block(cache_write_path, detector)
            logger.info("Saved raw data to cache: %s", cache_write_path.name)
        except Exception as exc:
            logger.warning("Failed to save raw data to cache %s: %s", cache_file_name, exc)

    logger.info(
        "Fetched %s: %d samples @ %d Hz (%.1f s)",
        detector,
        len(ts),
        sample_rate,
        float(ts.duration.value),
    )
    return ts


def fetch_local_or_remote_strain(
        detector: DetectorID,
        gps_start: float,
        gps_end: float,
        cache_raw: bool = False,
        edge_tolerance: float = 0.0,
) -> TimeSeries:
    """Fetch strain data, prioritizing local 4096s O4a blocks.
    
    If local blocks are not found, falls back to GWOSC open data fetch.
    """
    directories = _DATA_DIRECTORIES
    
    # Attempt local search
    for dir_path in directories:
        if not dir_path.exists():
            continue
            
        for file in dir_path.rglob(f"{detector}_*.hdf5"):
            parts = file.stem.split("_")
            if len(parts) >= 3:
                try:
                    f_start = float(parts[1])
                    f_end = float(parts[2])
                    if f_start <= gps_start + edge_tolerance and f_end >= gps_end - edge_tolerance:
                        logger.info(f"Found local block {file.name} covering [{gps_start}, {gps_end}] (tolerance: {edge_tolerance}s)")
                        ts = TimeSeries.read(file)
                        crop_start = max(f_start, gps_start)
                        crop_end = min(f_end, gps_end)
                        return ts.crop(crop_start, crop_end)
                except ValueError:
                    continue
                    
    logger.info(f"Local block not found for {detector} [{gps_start}, {gps_end}]. Fetching from GWOSC...")
    
    max_retries = 3
    base_delay = 2.0
    import random
    
    for attempt in range(max_retries):
        try:
            ts = TimeSeries.fetch_open_data(
                detector,
                gps_start,
                gps_end,
                cache=True,
                verbose=False
            )
            return ts
        except Exception as exc:
            if attempt < max_retries - 1:
                sleep_time = base_delay * (2 ** attempt) + random.uniform(0, 2)
                logger.warning(
                    f"Fetch error {detector} [{gps_start}-{gps_end}]: {exc}. "
                    f"Retrying in {sleep_time:.1f}s..."
                )
                time.sleep(sleep_time)
            else:
                logger.error(f"GWOSC fetch failed after {max_retries} attempts.")
                raise RuntimeError(f"GWOSC fetch failed: {exc}")


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


def _find_raw_session_by_id(session_id: str) -> Path | None:
    """Scans all configured data directories and returns the path to the folder matching the session_id."""
    for base_dir in _DATA_DIRECTORIES:
        if not base_dir.exists():
            continue
            
        target = base_dir / session_id
        if target.exists() and target.is_dir():
            return target
            
    return None


def _find_latest_raw_session() -> Path | None:
    """Scans all configured data directories and returns the path to the folder with the highest GPS name."""
    max_gps = -1
    latest_path = None
    
    for base_dir in _DATA_DIRECTORIES:
        if not base_dir.exists():
            continue
            
        for d in base_dir.iterdir():
            if d.is_dir():
                try:
                    gps_val = int(d.name)
                    if gps_val > max_gps:
                        max_gps = gps_val
                        latest_path = d
                except ValueError:
                    continue
                    
    return latest_path


def download_gwosc_4096s(detector: str, gps_start: int, gps_end: int, output_dir: Path) -> Path:
    """Download HDF5 file from GWOSC using gwosc.locate and requests.
    
    Returns the Path to the downloaded file.
    """
    import requests
    from gwosc.locate import get_urls
    import time
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    filename = f"{detector}_{gps_start}_{gps_end}.hdf5"
    output_path = output_dir / filename

    if output_path.exists():
        logger.info("Found cached GWOSC HDF5: %s", output_path)
        return output_path

    urls = get_urls(detector, gps_start, gps_end)
    if not urls:
        raise RuntimeError(f"No GWOSC URLs found for {detector} [{gps_start}, {gps_end}]")

    hdf5_urls = [u for u in urls if u.endswith('.hdf5')]
    if not hdf5_urls:
        raise RuntimeError(f"No HDF5 URLs found for {detector} [{gps_start}, {gps_end}]")

    url = hdf5_urls[-1]

    logger.info("Downloading %s from %s", filename, url)

    global _GWOSC_BASE_DELAY
    base_delay = _GWOSC_BASE_DELAY

    for attempt in range(5):
        try:
            time.sleep(base_delay)
            # Create session with retry on typical network errors (not 429, we handle 429 manually)
            session = requests.Session()
            retry = Retry(connect=3, backoff_factor=0.5)
            adapter = HTTPAdapter(max_retries=retry)
            session.mount('http://', adapter)
            session.mount('https://', adapter)

            with session.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(output_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            return output_path
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 429:
                logger.warning("429 Too Many Requests downloading %s. Retrying...", url)
                base_delay += 1.0
                time.sleep(1.0)
            else:
                raise RuntimeError(f"Failed to download {url}: {e}")
        except Exception as e:
            if attempt == 4:
                raise RuntimeError(f"Failed to download {url}: {e}")
            time.sleep(2.0)

    return output_path


def _validate_detector(detector: str) -> None:
    """Raise ``ValueError`` if *detector* is not a supported identifier."""
    supported = {"H1", "L1", "V1"}
    if detector not in supported:
        raise ValueError(
            f"Unsupported detector '{detector}'. Must be one of {supported}."
        )

def clear_astropy_cache() -> None:
    """Clear the astropy download cache to prevent disk space exhaustion."""
    try:
        from astropy.utils.data import clear_download_cache
        clear_download_cache()
        logger.info("Astropy download cache cleared successfully.")
    except Exception as exc:
        logger.warning("Failed to clear astropy cache: %s", exc)
