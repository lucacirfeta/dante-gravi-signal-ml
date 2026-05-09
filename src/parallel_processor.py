"""Parallel fetch + preprocessing pipeline for gravi-signal-ml.

Uses a producer-consumer pattern:
  - ThreadPoolExecutor: parallel GWOSC fetch (I/O bound, rate-limited)
  - ProcessPoolExecutor: parallel Q-transform (CPU bound)

Safe for Windows (spawn method), backward compatible with workers=1.
"""

from __future__ import annotations

import logging
import os
import queue
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src.utils import setup_logger

logger = setup_logger(__name__)


def get_optimal_workers() -> int:
    """Return recommended --workers value for current hardware."""
    cpu_count = os.cpu_count() or 4
    return max(1, cpu_count - 2)


def _process_single_segment(args: tuple) -> tuple[str, bool]:
    """Top-level function for processing a single segment.
    
    Safe for Windows ProcessPoolExecutor (spawn).
    """
    if len(args) == 6:
        gps_start, gps_end, ts, detector, output_dir, config = args
    else:
        gps_start, gps_end, ts, detector, output_dir = args

    segment_id = f"{detector}_{gps_start}_{gps_end}"

    if ts is None:
        return segment_id, False

    try:
        from src.preprocessor import bandpass, generate_qtransform, whiten
        
        # 1. Whiten
        ts_white = whiten(ts)
        
        # 2. Bandpass
        ts_bp = bandpass(ts_white)
        
        # 3. Q-transform -> PNG
        filename = f"{segment_id}.png"
        save_path = Path(output_dir) / filename
        generate_qtransform(ts_bp, save_path=save_path)
        
        return segment_id, True
    except Exception as exc:
        # Catch all exceptions and return False
        return segment_id, False


def batch_process_parallel(
    segments: list[tuple[int, int]],
    detector: str,
    output_dir: Path | str,
    config: dict[str, Any],
    workers: int = 1,
    fetch_workers: int = 4,
) -> tuple[int, int]:
    """Run preprocessing pipeline in parallel.
    
    Returns (saved_count, skipped_count).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if workers == 1:
        from src.preprocessor import batch_process
        saved_paths = batch_process(segments, detector, output_dir)
        return len(saved_paths), len(segments) - len(saved_paths)

    fetch_workers = min(fetch_workers, 4)
    cpu_workers = max(1, workers - 2)
    
    logger.info(
        "Parallel pipeline: fetch_workers=%d (threads) + cpu_workers=%d (processes)",
        fetch_workers,
        cpu_workers,
    )
    
    q: queue.Queue = queue.Queue(maxsize=min(workers * 2, 16))
    
    def fetch_worker(segment: tuple[int, int]) -> None:
        gps_start, gps_end = segment
        time.sleep(0.3)
        try:
            from src.data_loader import fetch_strain_data
            ts = fetch_strain_data(detector, gps_start, gps_end)
            q.put((gps_start, gps_end, ts))
        except Exception:
            q.put((gps_start, gps_end, None))

    saved_count = 0
    skipped_count = 0

    with ThreadPoolExecutor(max_workers=fetch_workers) as fetch_pool:
        # Submit all fetches
        for segment in segments:
            fetch_pool.submit(fetch_worker, segment)
            
        with ProcessPoolExecutor(max_workers=cpu_workers) as cpu_pool:
            futures = []
            
            # Consume from queue
            for _ in range(len(segments)):
                gps_start, gps_end, ts = q.get()
                if ts is None:
                    skipped_count += 1
                else:
                    args = (gps_start, gps_end, ts, detector, output_dir, config)
                    futures.append(cpu_pool.submit(_process_single_segment, args))
                    
            for future in as_completed(futures):
                segment_id, success = future.result()
                if success:
                    saved_count += 1
                else:
                    skipped_count += 1

    logger.info("Parallel batch complete: %d saved, %d skipped", saved_count, skipped_count)
    return saved_count, skipped_count
