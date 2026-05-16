"""Time-slide background estimation.

Calculates the significance of anomalous cluster coincidences
between H1 and L1 using time slides.
"""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path

import numpy as np

from src.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)


def extract_anomalous_gps(metadata_path: Path, report_path: Path) -> set[int]:
    """Extract start GPS times of anomalous spectrograms.
    
    Reads cluster labels from the cluster report and file paths from the metadata.
    """
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
    if not report_path.exists():
        raise FileNotFoundError(f"Report file not found: {report_path}")

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)
        
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # Find which clusters are anomalous
    anomalous_cluster_ids = set(report.get("results", {}).get("anomalous_clusters", []))
    
    anomalous_files = set()
    clusters = report.get("results", {}).get("clusters", {})
    for cid_str, cluster_data in clusters.items():
        cid = int(cid_str)
        if cid in anomalous_cluster_ids:
            for sample in cluster_data.get("sample_files", []):
                anomalous_files.add(Path(sample).name)
                
    # Parse GPS from filenames in metadata
    pattern = re.compile(r"^[A-Z]\d_(\d+)_(\d+)\.png$")
    anomalous_gps = set()
    
    for f in metadata.get("files", []):
        name = Path(f).name
        if name in anomalous_files:
            m = pattern.match(name)
            if m:
                gps_start = int(m.group(1))
                anomalous_gps.add(gps_start)
                
    return anomalous_gps


def count_coincidences(h1_gps: set[int], l1_gps: set[int], window: int = 32) -> int:
    """Count coincidences between two sets of GPS times within a window.
    
    Each t1 can only be matched once.
    """
    coincidences = 0
    # O(N*M) is fine because anomalous GPS sets are small
    for t1 in h1_gps:
        for t2 in l1_gps:
            if abs(t1 - t2) <= window:
                coincidences += 1
                break  # count t1 only once
    return coincidences


def run_timeslide(
    meta_h1: Path, rep_h1: Path,
    meta_l1: Path, rep_l1: Path,
    output_dir: Path,
    iterations: int = 50,
    window: int = 32
) -> dict:
    """Run time-slide analysis and save report.
    
    Args:
        meta_h1: Path to H1 metadata JSON
        rep_h1: Path to H1 cluster report JSON
        meta_l1: Path to L1 metadata JSON
        rep_l1: Path to L1 cluster report JSON
        output_dir: Directory to save timeslide_report.json
        iterations: Number of time-slide iterations (default 50)
        window: Coincidence window in seconds (default 32)
    """
    logger.info("Extracting H1 anomalous GPS...")
    h1_gps = extract_anomalous_gps(meta_h1, rep_h1)
    
    logger.info("Extracting L1 anomalous GPS...")
    l1_gps = extract_anomalous_gps(meta_l1, rep_l1)
    
    logger.info("H1 anomalous segments: %d", len(h1_gps))
    logger.info("L1 anomalous segments: %d", len(l1_gps))
    
    # 2. Zero-lag
    zero_lag_coinc = count_coincidences(h1_gps, l1_gps, window)
    
    # 3. Time-slide
    background = []
    
    # shifts between -5000 and 5000, multiples of 100, excluding 0
    possible_shifts = [x for x in range(-5000, 5001, 100) if x != 0]
    
    # Ensure we have enough possible shifts
    if iterations > len(possible_shifts):
        logger.warning(
            "Requested %d iterations but only %d available. Capping.", 
            iterations, len(possible_shifts)
        )
        iterations = len(possible_shifts)
        
    shifts = random.sample(possible_shifts, iterations)
    
    logger.info("Running %d time-slide iterations...", iterations)
    for shift in shifts:
        shifted_l1 = {t + shift for t in l1_gps}
        c = count_coincidences(h1_gps, shifted_l1, window)
        background.append(c)
        
    # 4. Construct background distribution
    bg_mean = float(np.mean(background)) if background else 0.0
    bg_std = float(np.std(background)) if background else 0.0
    
    # 5. Calculate p-value
    p_value = sum(1 for c in background if c >= zero_lag_coinc) / iterations if iterations > 0 else 1.0
    
    # 6. Calculate z-score
    z_score = (zero_lag_coinc - bg_mean) / bg_std if bg_std > 0 else 0.0
    
    interpretation = "significativo" if p_value < 0.05 else "compatibile con fondo"
    
    logger.info(
        "Time-slide: zero-lag=%d coincidences, background mean=%.2f±%.2f, p-value=%.4f",
        zero_lag_coinc, bg_mean, bg_std, p_value
    )
    
    report = {
        "zero_lag_coincidences": zero_lag_coinc,
        "background_distribution": background,
        "p_value": p_value,
        "z_score": z_score,
        "interpretation": f"p < 0.05 = significativo, altrimenti coincidenza compatibile con fondo. Risultato: {interpretation}"
    }
    
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "timeslide_report_H1_L1.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)
        
    logger.info("Timeslide report saved to %s", out_file)
    
    return report
