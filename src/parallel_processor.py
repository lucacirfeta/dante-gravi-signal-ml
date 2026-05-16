"""Parallel fetch + preprocessing pipeline for gravi-signal-ml.

Uses a producer-consumer pattern:
  - ThreadPoolExecutor: parallel GWOSC fetch (I/O bound, rate-limited)
  - ProcessPoolExecutor: parallel Q-transform (CPU bound)

Safe for Windows (spawn method), backward compatible with workers=1.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from src.utils import setup_logger

logger = setup_logger(__name__)


def get_optimal_workers() -> int:
    """Return recommended --workers value for current hardware."""
    cpu_count = os.cpu_count() or 4
    return max(1, cpu_count - 2)


def _process_single_segment(args: tuple) -> tuple[str, bool]:
    """
    Autonomous worker: fetch + whiten + bandpass + Q-transform + save PNG.
    Receives only picklable primitives — safe for Windows spawn.
    """
    gps_start, gps_end, detector, output_dir_str, config, cache_raw = args
    output_dir = Path(output_dir_str)
    
    filename = f"{detector}_{gps_start}_{gps_end}.png"
    save_path = output_dir / filename
    segment_id = f"{detector}_{gps_start}_{gps_end}"
    
    # Skip existing spectrograms (resumable pipeline)
    if save_path.exists():
        print(f"Skipping existing spectrogram: {filename}")
        return (segment_id, True)
    
    try:
        # Import inside function to avoid pickling issues
        from src.data_loader import fetch_strain_data
        from src.preprocessor import whiten, bandpass, generate_qtransform
        
        # Fetch
        ts = fetch_strain_data(detector, gps_start, gps_end,
                               sample_rate=config.get('sample_rate', 4096),
                               cache_raw=cache_raw)
        
        # Preprocess
        ts_w = whiten(ts)
        ts_bp = bandpass(ts_w,
                         f_low=config.get('f_low', 20.0),
                         f_high=config.get('f_high', 2000.0))
        
        # Check for NaN/Inf after filtering
        import numpy as np
        if not np.isfinite(ts_bp.value).all():
            print(f"Skipping segment {segment_id}: contains NaN/Inf after processing")
            return (segment_id, False)

        # Save PNG
        generate_qtransform(ts_bp, save_path=save_path,
                            cmap=config.get('colormap', 'cividis'))
        
        return (segment_id, True)
        
    except Exception as exc:
        print(f"Worker Error on {segment_id}: {exc}")
        return (segment_id, False)


def batch_process_parallel(
    segments: list[tuple[int, int]],
    detector: str | list[str],
    output_dir: Path,
    config: dict,
    workers: int = 1,
    fetch_workers: int = 4,
    cache_raw: bool = True,
) -> tuple[int, int]:
    
    output_dir = Path(output_dir)
    
    if workers <= 1:
        # Sequential fallback — unchanged behavior
        from src.preprocessor import batch_process
        if isinstance(detector, list):
            saved, skipped = 0, 0
            for det in detector:
                det_out = output_dir / det
                det_out.mkdir(parents=True, exist_ok=True)
                p_saved = batch_process(segments, det, det_out, config)
                saved += len(p_saved)
                skipped += len(segments) - len(p_saved)
            return saved, skipped
        else:
            output_dir.mkdir(parents=True, exist_ok=True)
            saved_paths = batch_process(segments, detector, output_dir, config)
            return len(saved_paths), len(segments) - len(saved_paths)
    
    # Embarrassingly parallel: each worker is fully autonomous
    cpu_workers = max(1, workers - 2)
    
    logger.info(
        "Parallel pipeline: %d autonomous workers (fetch+process per worker)",
        cpu_workers
    )
    
    # Build args list — only picklable primitives
    preprocessing_config = {
        'sample_rate': config.get('preprocessing', {}).get('sample_rate', 4096),
        'f_low': config.get('preprocessing', {}).get('f_low', 20.0),
        'f_high': config.get('preprocessing', {}).get('f_high', 2000.0),
        'qrange': config.get('preprocessing', {}).get('qrange', [4, 64]),
        'frange': config.get('preprocessing', {}).get('frange', [20, 2048]),
        'output_size': config.get('preprocessing', {}).get('output_size', [256, 256]),
        'colormap': config.get('preprocessing', {}).get('colormap', 'cividis'),
    }
    
    detectors = detector if isinstance(detector, list) else [detector]
    
    args_list = []
    for gps_start, gps_end in segments:
        for det in detectors:
            if len(detectors) > 1:
                det_out_dir = output_dir / det
                det_out_dir.mkdir(parents=True, exist_ok=True)
            else:
                det_out_dir = output_dir
                det_out_dir.mkdir(parents=True, exist_ok=True)
            args_list.append((gps_start, gps_end, det, str(det_out_dir), preprocessing_config, cache_raw))
    
    saved = 0
    skipped = 0
    
    with ProcessPoolExecutor(max_workers=cpu_workers) as executor:
        futures = {executor.submit(_process_single_segment, args): args 
                   for args in args_list}
        
        from tqdm import tqdm
        det_str = "+".join(detectors)
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc=f"Processing {det_str}",
            unit="seg"
        ):
            try:
                segment_id, success = future.result(timeout=120)
                if success:
                    saved += 1
                else:
                    skipped += 1
            except Exception:
                skipped += 1
    
    logger.info(
        "Parallel batch complete: %d saved, %d skipped", saved, skipped
    )
    return saved, skipped

