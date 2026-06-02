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

# GPS extraction pattern: matches e.g. H1_1369209472_1369209504.png
_GPS_PATTERN = re.compile(r"^[A-Z]\d+_(\d+)_(\d+)\.png$")


def _gps_from_filename(filename: str) -> int | None:
    """Extract the GPS start time from a spectrogram filename.

    Returns the integer GPS start, or None if the name doesn't match.
    """
    m = _GPS_PATTERN.match(Path(filename).name)
    if m:
        return int(m.group(1))
    return None


def extract_anomalous_gps(metadata_path: Path, report_path: Path) -> set[int]:
    """Extract start GPS times of anomalous spectrograms.

    Reads:
    - ``anomalous_clusters`` from the cluster report and collects all
      ``sample_files`` belonging to those clusters.
    - ``anomalous_samples`` (DPMM individual anomaly indices) from the report,
      resolving them against the ``files`` list in the metadata JSON.

    GPS times are parsed from the spectrogram filenames
    (pattern: ``<DET>_<GPS_START>_<GPS_END>.png``).

    Args:
        metadata_path: Path to the embeddings metadata JSON
                       (contains ``files`` list).
        report_path: Path to the cluster report JSON produced by
                     :func:`~src.reporter.save_cluster_report`.

    Returns:
        Set of integer GPS start times for all anomalous spectrograms.
    """
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
    if not report_path.exists():
        raise FileNotFoundError(f"Report file not found: {report_path}")

    with open(metadata_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    results = report.get("results", {})
    anomalous_gps: set[int] = set()

    # ------------------------------------------------------------------
    # 1. Cluster-level anomalies
    # ------------------------------------------------------------------
    anomalous_cluster_ids = set(results.get("anomalous_clusters", []))

    clusters = results.get("clusters", {})
    for cid_str, cluster_data in clusters.items():
        try:
            cid = int(cid_str)
        except ValueError:
            continue
        if cid not in anomalous_cluster_ids:
            continue
        for sample_path in cluster_data.get("sample_files", []):
            gps = _gps_from_filename(sample_path)
            if gps is not None:
                anomalous_gps.add(gps)

    # ------------------------------------------------------------------
    # 2. DPMM individual anomalies (anomalous_samples are indices into
    #    the metadata files list)
    # ------------------------------------------------------------------
    anomalous_sample_indices: list[int] = results.get("anomalous_samples", [])
    if anomalous_sample_indices:
        all_files: list[str] = metadata.get("files", [])
        n_files = len(all_files)
        for idx in anomalous_sample_indices:
            if not isinstance(idx, int) or idx < 0 or idx >= n_files:
                logger.warning(
                    "anomalous_samples index %s out of range (n_files=%d) — skipping",
                    idx, n_files,
                )
                continue
            gps = _gps_from_filename(all_files[idx])
            if gps is not None:
                anomalous_gps.add(gps)

    logger.debug(
        "extract_anomalous_gps: %d cluster-anomalous clusters, "
        "%d DPMM-anomalous samples → %d unique GPS times",
        len(anomalous_cluster_ids),
        len(anomalous_sample_indices),
        len(anomalous_gps),
    )
    return anomalous_gps


def count_coincidences(h1_gps: set[int], l1_gps: set[int], window: int = 32) -> int:
    """Count coincidences between two sets of GPS times within a window.

    Each H1 event can only be matched once (greedy, first-match).

    Args:
        h1_gps: Set of H1 GPS start times.
        l1_gps: Set of L1 GPS start times.
        window: Maximum absolute time difference in seconds to count
                as a coincidence. Default: 32.

    Returns:
        Number of coincident H1 events.
    """
    coincidences = 0
    for t1 in h1_gps:
        for t2 in l1_gps:
            if abs(t1 - t2) <= window:
                coincidences += 1
                break  # count each t1 only once
    return coincidences


def run_timeslide(
        meta_h1: Path, rep_h1: Path,
        meta_l1: Path, rep_l1: Path,
        output_dir: Path,
        iterations: int = 100,
        window: int = 32,

        logger: logging.Logger | logging.LoggerAdapter | None = None, ) -> dict:
    """Run time-slide analysis and save report.

    Estimates the background coincidence rate between H1 and L1 by
    shifting the L1 event times by random offsets and counting how
    often the zero-lag coincidence count is exceeded.

    Args:
        meta_h1: Path to H1 metadata JSON (from the encoder).
        rep_h1: Path to H1 cluster report JSON.
        meta_l1: Path to L1 metadata JSON (from the encoder).
        rep_l1: Path to L1 cluster report JSON.
        output_dir: Directory to save ``timeslide_report_H1_L1.json``.
        iterations: Number of time-slide iterations. Default: 100.
        window: Coincidence window in seconds. Default: 32.

    Returns:
        Dictionary with zero-lag count, background distribution,
        p-value, z-score, and interpretation.
    """

    logger = logger or logging.getLogger(__name__)


    logger.info("Extracting H1 anomalous GPS times...")
    h1_gps = extract_anomalous_gps(meta_h1, rep_h1)

    logger.info("Extracting L1 anomalous GPS times...")
    l1_gps = extract_anomalous_gps(meta_l1, rep_l1)

    logger.info("H1 anomalous segments: %d", len(h1_gps))
    logger.info("L1 anomalous segments: %d", len(l1_gps))

    if len(h1_gps) == 0 or len(l1_gps) == 0:
        logger.warning(
            "One or both detectors have 0 anomalous GPS times. "
            "Timeslide will produce a trivial result."
        )

    # Zero-lag coincidence count
    zero_lag_coinc = count_coincidences(h1_gps, l1_gps, window)

    # Time-slide background estimation
    background: list[int] = []

    # Shifts: multiples of 100 s between ±5000 s, excluding 0
    possible_shifts = [x for x in range(-5000, 5001, 100) if x != 0]

    if iterations > len(possible_shifts):
        logger.warning(
            "Requested %d iterations but only %d available non-zero shifts. Capping.",
            iterations, len(possible_shifts),
        )
        iterations = len(possible_shifts)

    shifts = random.sample(possible_shifts, iterations)

    logger.info("Running %d time-slide iterations (window=%ds)...", iterations, window)
    for shift in shifts:
        shifted_l1 = {t + shift for t in l1_gps}
        c = count_coincidences(h1_gps, shifted_l1, window)
        background.append(c)

    # Background statistics
    bg_mean = float(np.mean(background)) if background else 0.0
    bg_std = float(np.std(background)) if background else 0.0

    # Empirical p-value: fraction of background trials >= zero-lag
    p_value = (
        sum(1 for c in background if c >= zero_lag_coinc) / iterations
        if iterations > 0 else 1.0
    )

    # z-score
    z_score = (zero_lag_coinc - bg_mean) / bg_std if bg_std > 0 else 0.0

    interpretation = "significativo" if p_value < 0.05 else "compatibile con fondo"

    logger.info(
        "Time-slide: zero-lag=%d coincidences, background mean=%.2f±%.2f, "
        "p-value=%.4f, z-score=%.2f",
        zero_lag_coinc, bg_mean, bg_std, p_value, z_score,
    )

    report = {
        "zero_lag_coincidences": zero_lag_coinc,
        "h1_anomalous_gps_count": len(h1_gps),
        "l1_anomalous_gps_count": len(l1_gps),
        "iterations": iterations,
        "window_seconds": window,
        "background_distribution": background,
        "background_mean": bg_mean,
        "background_std": bg_std,
        "p_value": p_value,
        "z_score": z_score,
        "interpretation": (
            f"p < 0.05 = significativo, altrimenti coincidenza compatibile con fondo. "
            f"Risultato: {interpretation}"
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "timeslide_report_H1_L1.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)

    logger.info("Timeslide report saved to %s", out_file)

    return report
