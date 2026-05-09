"""Gravity Spy cross-check for anomalous cluster candidates — Phase 3.1.

Queries the public Gravity Spy glitch database to determine whether
spectrograms flagged as anomalous by the clustering pipeline are already
catalogued.  Spectrograms without a confident Gravity Spy match are
the strongest candidates for genuinely novel glitch classes.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from src.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# GPS extraction
# ---------------------------------------------------------------------------


def get_anomalous_gps_windows(
    cluster_report_path: Path,
    anomalous_cluster_ids: list[int],
    metadata_path: Path,
) -> list[dict]:
    """Extract GPS time windows for spectrograms in anomalous clusters.

    Reads the cluster report JSON to find file paths assigned to each
    anomalous cluster, then parses the GPS start/end times from the
    filename convention ``{detector}_{gps_start}_{gps_end}.png``.

    Args:
        cluster_report_path: Path to ``cluster_report.json``.
        anomalous_cluster_ids: Cluster IDs to treat as anomalous
            (e.g. ``[2, 3]``).
        metadata_path: Path to the companion metadata JSON produced by
            the encoder (unused in current implementation but reserved
            for future enrichment).

    Returns:
        List of dicts, each containing:
        ``{"cluster_id", "gps_start", "gps_end", "file"}``.
    """
    cluster_report_path = Path(cluster_report_path)
    with open(cluster_report_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)

    clusters = report.get("results", {}).get("clusters", {})
    windows: list[dict] = []

    for cid in anomalous_cluster_ids:
        cluster_data = clusters.get(str(cid), {})
        sample_files = cluster_data.get("sample_files", [])

        for filepath in sample_files:
            gps_start, gps_end = _extract_gps_from_filename(filepath)
            if gps_start is not None:
                windows.append(
                    {
                        "cluster_id": cid,
                        "gps_start": gps_start,
                        "gps_end": gps_end,
                        "file": filepath,
                    }
                )
            else:
                logger.warning(
                    "Could not parse GPS from filename: %s", filepath
                )

    logger.info(
        "Extracted %d GPS windows from %d anomalous clusters",
        len(windows),
        len(anomalous_cluster_ids),
    )
    return windows


def _extract_gps_from_filename(filepath: str) -> tuple[int | None, int | None]:
    """Parse GPS start and end times from a spectrogram filename.

    Expected format: ``{detector}_{gps_start}_{gps_end}.png``
    Examples: ``H1_1369599346_1369599378.png``

    Returns:
        Tuple of ``(gps_start, gps_end)`` or ``(None, None)`` if parsing
        fails.
    """
    stem = Path(filepath).stem
    match = re.match(r"^[A-Z]\d+_(\d+)_(\d+)$", stem)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


# ---------------------------------------------------------------------------
# Gravity Spy query
# ---------------------------------------------------------------------------


def query_gravity_spy(
    gps_start: int,
    gps_end: int,
    detector: str = "H1",
    snr_threshold: float = 7.5,
) -> list[dict]:
    """Query the Gravity Spy glitch database for a given GPS window.

    Uses :meth:`gwpy.table.EventTable.fetch` to search for catalogued
    glitches overlapping the specified time range.

    Args:
        gps_start: GPS start time of the window.
        gps_end: GPS end time of the window.
        detector: Detector identifier (``"H1"``, ``"L1"``, ``"V1"``).
        snr_threshold: Minimum signal-to-noise ratio.  Default 7.5.

    Returns:
        List of dicts per match, each containing:
        ``{"peakGPS", "label", "confidence", "snr",
          "peak_frequency", "ifo"}``.
        Returns an empty list if no matches are found or if the query
        fails (logged as a warning — never crashes).
    """
    try:
        from gwpy.table import GravitySpyTable  # type: ignore

        table = GravitySpyTable.fetch(
            "gravityspy",
            "glitches",
            selection=[
                f'{gps_end} > "peakGPS" > {gps_start}',
                f'"ifo" = "{detector}"',
                f'"snr" > {snr_threshold}',
            ],
        )

        results: list[dict] = []
        for row in table:
            results.append(
                {
                    "peakGPS": float(row["peakGPS"]),
                    "label": str(row["ml_label"]),
                    "confidence": float(row["ml_confidence"]),
                    "snr": float(row["snr"]),
                    "peak_frequency": float(row["peak_frequency"]),
                    "ifo": str(row["ifo"]),
                }
            )

        logger.info(
            "Gravity Spy query [%d, %d] %s: %d matches",
            gps_start,
            gps_end,
            detector,
            len(results),
        )
        return results

    except Exception as exc:
        logger.warning(
            "Gravity Spy query failed for [%d, %d] %s: %s",
            gps_start,
            gps_end,
            detector,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Full cross-check orchestration
# ---------------------------------------------------------------------------


def cross_check_anomalous_clusters(
    cluster_report_path: Path,
    metadata_path: Path,
    detector: str = "H1",
    output_path: Path | None = None,
) -> dict:
    """Orchestrate a full Gravity Spy cross-check of anomalous clusters.

    Workflow:
      1. Load the cluster report and identify anomalous clusters.
      2. Extract GPS windows for all anomalous spectrograms.
      3. Query Gravity Spy for each window.
      4. Classify each spectrogram:
         - ``CLASSIFIED``: Gravity Spy match with confidence ≥ 0.95
         - ``LOW_CONFIDENCE``: match with confidence < 0.95
         - ``UNCLASSIFIED``: no match — genuine candidate
      5. Optionally save detailed results to *output_path* (JSON).

    Args:
        cluster_report_path: Path to ``cluster_report.json``.
        metadata_path: Path to encoder companion metadata JSON.
        detector: Detector identifier for Gravity Spy queries.
        output_path: If provided, write JSON results to this path.

    Returns:
        Summary dict with keys:
        ``{"total_anomalous", "classified", "low_confidence",
          "unclassified", "details"}``.
    """
    cluster_report_path = Path(cluster_report_path)
    metadata_path = Path(metadata_path)

    # 1. Load report and find anomalous cluster IDs
    with open(cluster_report_path, "r", encoding="utf-8") as fh:
        report = json.load(fh)

    anomalous_ids = report.get("results", {}).get("anomalous_clusters", [])
    if not anomalous_ids:
        logger.info("No anomalous clusters found in report.")
        return {
            "total_anomalous": 0,
            "classified": 0,
            "low_confidence": 0,
            "unclassified": 0,
            "details": [],
        }

    # 2. Get GPS windows
    windows = get_anomalous_gps_windows(
        cluster_report_path, anomalous_ids, metadata_path
    )

    # 3. Query Gravity Spy for each window and classify
    details: list[dict] = []
    classified = 0
    low_confidence = 0
    unclassified = 0

    for win in windows:
        gs_results = query_gravity_spy(
            win["gps_start"], win["gps_end"], detector=detector
        )

        if gs_results:
            # Pick the highest-confidence match
            best = max(gs_results, key=lambda r: r["confidence"])
            if best["confidence"] >= 0.95:
                status = "CLASSIFIED"
                classified += 1
            else:
                status = "LOW_CONFIDENCE"
                low_confidence += 1

            details.append(
                {
                    "file": win["file"],
                    "gps_start": win["gps_start"],
                    "cluster_id": win["cluster_id"],
                    "status": status,
                    "gs_label": best["label"],
                    "gs_confidence": best["confidence"],
                }
            )
        else:
            status = "UNCLASSIFIED"
            unclassified += 1
            details.append(
                {
                    "file": win["file"],
                    "gps_start": win["gps_start"],
                    "cluster_id": win["cluster_id"],
                    "status": status,
                    "gs_label": None,
                    "gs_confidence": None,
                }
            )

    summary = {
        "total_anomalous": len(windows),
        "classified": classified,
        "low_confidence": low_confidence,
        "unclassified": unclassified,
        "details": details,
    }

    # 4. Save to file if requested
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, default=str)
        logger.info("Cross-check results saved to %s", output_path)

    return summary


# ---------------------------------------------------------------------------
# Console display
# ---------------------------------------------------------------------------


def print_crosscheck_summary(results: dict) -> None:
    """Print a human-readable summary of the Gravity Spy cross-check.

    UNCLASSIFIED entries are highlighted — these are the strongest
    candidates for genuinely novel glitch classes.

    Args:
        results: Summary dict returned by
            :func:`cross_check_anomalous_clusters`.
    """
    print("\n" + "=" * 72)
    print("  GRAVITY SPY CROSS-CHECK SUMMARY")
    print("=" * 72)
    print(f"  Total anomalous spectrograms:  {results['total_anomalous']}")
    print(f"  Classified (known glitches):   {results['classified']}")
    print(f"  Low confidence:                {results['low_confidence']}")
    print(f"  UNCLASSIFIED (novel cands.):   {results['unclassified']}")
    print("-" * 72)
    print(
        f"  {'File':<45} {'Cluster':>7}  {'Status':<16} {'GS Label':<15} {'Conf':>5}"
    )
    print(
        f"  {'-' * 45} {'-' * 7}  {'-' * 16} {'-' * 15} {'-' * 5}"
    )

    for entry in results.get("details", []):
        filename = Path(entry["file"]).name
        cluster = entry["cluster_id"]
        status = entry["status"]
        label = entry.get("gs_label") or "—"
        conf = entry.get("gs_confidence")
        conf_str = f"{conf:.2f}" if conf is not None else "  —"

        # Highlight UNCLASSIFIED entries
        marker = ">>>" if status == "UNCLASSIFIED" else "   "
        print(
            f"{marker} {filename:<44} {cluster:>7}  {status:<16} {label:<15} {conf_str:>5}"
        )

    print("=" * 72 + "\n")
