#!/usr/bin/env python3
"""gravi-signal-ml — CLI entry point.

Provides subcommands for each pipeline stage:

    fetch         — Download and process a known reference event (PoC)
    scan          — Batch-scan O4a segments for a detector
    scan-extended — Extended 48h scan of H1 + L1 (Phase 3.1)
    encode        — Extract embeddings from spectrograms (Phase 2)
    cluster       — Cluster embeddings to discover novel classes (Phase 3)
    crosscheck    — Gravity Spy cross-check of anomalous clusters (Phase 3.1)

Usage:
    python main.py fetch          --event GW150914
    python main.py scan           --detector H1 --hours 2
    python main.py scan-extended
    python main.py encode         --input-dir data/spectrograms/ --output data/embeddings/o4a_h1.npy
    python main.py cluster        --input data/embeddings/o4a_h1_6h.npy --output data/clusters/
    python main.py crosscheck     --report data/clusters/cluster_report.json --metadata data/embeddings/o4a_h1_6h.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from src.data_loader import fetch_o4a_segments, fetch_strain_data
from src.encoder import DINOv2Encoder
from src.preprocessor import bandpass, batch_process, generate_qtransform, whiten
from src.utils import load_config, setup_logger

logger = setup_logger("main", log_file=Path("logs/gravi-signal-ml.log"))


def cmd_fetch(args: argparse.Namespace) -> None:
    """Fetch a known reference event, preprocess it, and save a spectrogram."""
    cfg = load_config()
    event_name: str = args.event

    if event_name not in cfg["reference_events"]:
        available = ", ".join(cfg["reference_events"].keys())
        logger.error("Unknown event '%s'. Available: %s", event_name, available)
        sys.exit(1)

    event = cfg["reference_events"][event_name]
    detector = event["detector"]
    gps_start = event["start"]
    gps_end = event["end"]

    logger.info("=== FETCH: %s (%s) ===", event_name, detector)

    # 1. Fetch strain data
    ts = fetch_strain_data(detector, gps_start, gps_end)

    # 2. Whiten
    ts_white = whiten(ts)

    # 3. Bandpass
    ts_bp = bandpass(ts_white)

    # 4. Generate Q-transform spectrogram
    output_dir = Path("data/spectrograms")
    output_dir.mkdir(parents=True, exist_ok=True)
    save_path = output_dir / f"{event_name}_{detector}.png"

    spectrogram = generate_qtransform(ts_bp, save_path=save_path)

    logger.info(
        "Phase 1 complete. Chirp visible at %s (shape: %s)",
        save_path,
        spectrogram.shape,
    )


def cmd_scan(args: argparse.Namespace) -> None:
    """Batch-scan O4a segments for a given detector."""
    detector: str = args.detector
    hours: float = args.hours

    logger.info("=== SCAN: %s, %.1f hours ===", detector, hours)

    # Generate segment list
    segments = fetch_o4a_segments(detector, duration_hours=hours)

    if not segments:
        logger.warning("No segments found for %s in the requested window.", detector)
        sys.exit(0)

    # Output directory
    output_dir = Path(f"data/spectrograms/o4a/{detector}")

    workers: int = args.workers

    # Run batch processing
    if workers == 1:
        saved_paths = batch_process(segments, detector, output_dir)
        processed_count = len(saved_paths)
    else:
        from src.parallel_processor import batch_process_parallel
        cfg = load_config()
        fetch_workers = cfg.get("performance", {}).get("gwosc_fetch_threads", 4)
        processed_count, _ = batch_process_parallel(
            segments, detector, output_dir, cfg, workers=workers, fetch_workers=fetch_workers
        )

    total_duration = sum(end - start for start, end in segments)
    logger.info(
        "Scan complete: %d processed, %d skipped, %.1f h scanned",
        processed_count,
        len(segments) - processed_count,
        total_duration / 3600,
    )


def cmd_scan_extended(args: argparse.Namespace) -> None:
    """Run an extended 48h scan of H1 + L1 sequentially."""
    cfg = load_config()
    scan_cfg = cfg["scan_extended"]

    hours = scan_cfg["hours_per_detector"]
    detectors = scan_cfg["detectors"]
    offsets = {
        "H1": scan_cfg["h1_offset_hours"],
        "L1": scan_cfg["l1_offset_hours"],
    }
    workers: int = args.workers
    fetch_workers = cfg.get("performance", {}).get("gwosc_fetch_threads", 4)

    logger.info("=== SCAN-EXTENDED: %s, %d h per detector ===", detectors, hours)

    totals: dict[str, int] = {}

    for det in detectors:
        offset = offsets.get(det, 0)
        logger.info("--- Scanning %s: %d h, offset %.1f h ---", det, hours, offset)

        # Generate segment list with offset
        segments = fetch_o4a_segments(
            det, duration_hours=hours, gps_offset_hours=offset
        )

        if not segments:
            logger.warning("No segments for %s — skipping.", det)
            totals[det] = 0
            continue

        # Output directory (preserves existing spectrograms)
        output_dir = Path(f"data/spectrograms/o4a/{det}")

        # Run batch processing
        if workers == 1:
            saved_paths = batch_process(segments, det, output_dir)
            processed_count = len(saved_paths)
        else:
            from src.parallel_processor import batch_process_parallel
            processed_count, _ = batch_process_parallel(
                segments, det, output_dir, cfg, workers=workers, fetch_workers=fetch_workers
            )

        total_duration = sum(end - start for start, end in segments)
        logger.info(
            "%s scan complete: %d processed, %d skipped, %.1f h scanned",
            det,
            processed_count,
            len(segments) - processed_count,
            total_duration / 3600,
        )
        totals[det] = processed_count

    parts = " ".join(f"{d}={n}" for d, n in totals.items())
    print(f"Extended scan complete: {parts} spectrograms saved.")


def cmd_encode(args: argparse.Namespace) -> None:
    """Extract embeddings from spectrograms using the DINOv2-Reg encoder."""
    input_dir = Path(args.input_dir)
    output_path = Path(args.output)
    batch_size: int = args.batch_size

    logger.info("=== ENCODE: %s ===", input_dir)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    encoder = DINOv2Encoder()

    try:
        encoder.extract_dataset(input_dir, output_path, batch_size)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        print(f"Error: {exc}")
        sys.exit(1)

    print("Phase 2 complete. Embeddings ready for Phase 3 clustering.")


def cmd_cluster(args: argparse.Namespace) -> None:
    """Cluster embeddings to discover novel glitch classes."""
    input_path = Path(args.input)
    output_dir = Path(args.output)

    logger.info("=== CLUSTER: %s ===", input_path)

    # 1. Load embeddings (.npy)
    if not input_path.exists():
        logger.error("Embeddings file not found: %s", input_path)
        sys.exit(1)

    embeddings = np.load(input_path)
    logger.info("Loaded embeddings: shape %s, dtype %s", embeddings.shape, embeddings.dtype)

    # 2. Load companion metadata JSON (same path, .json suffix)
    json_path = input_path.with_suffix(".json")
    metadata = {}
    if json_path.exists():
        import json

        with open(json_path, "r", encoding="utf-8") as fh:
            metadata = json.load(fh)
        logger.info("Loaded metadata: %d files", len(metadata.get("files", [])))
    else:
        logger.warning("No companion metadata JSON found at %s", json_path)

    # 3. Load clustering config
    cfg = load_config()
    cluster_cfg = cfg["clustering"]

    # 4. Run full clustering pipeline
    from src.clustering import run_full_pipeline

    result = run_full_pipeline(embeddings, cluster_cfg)

    # 5. Save cluster report (JSON + UMAP plot + gallery)
    from src.reporter import print_summary, save_cluster_report

    save_cluster_report(result, metadata, output_dir)

    # 6. Print human-readable summary
    print_summary(result)

    print(f"Phase 3 complete. Results in {output_dir}")


def cmd_crosscheck(args: argparse.Namespace) -> None:
    """Cross-check anomalous clusters against the Gravity Spy database."""
    from src.gravity_spy_checker import (
        cross_check_anomalous_clusters,
        print_crosscheck_summary,
    )

    report_path = Path(args.report)
    metadata_path = Path(args.metadata)
    detector: str = args.detector
    output_path = Path(args.output) if args.output else None

    logger.info("=== CROSSCHECK: %s, report=%s ===", detector, report_path)

    # 1. Run the full cross-check
    results = cross_check_anomalous_clusters(
        cluster_report_path=report_path,
        metadata_path=metadata_path,
        detector=detector,
        output_path=output_path,
    )

    # 2. Print human-readable summary
    print_crosscheck_summary(results)

    # 3. Final message
    n_unclassified = results["unclassified"]
    print(f"Cross-check complete. Results: {n_unclassified} unclassified candidates.")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="gravi-signal-ml",
        description=(
            "Unsupervised anomaly detection pipeline for gravitational-wave "
            "data.  Discovers novel glitch classes in LIGO/Virgo O4a data."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- fetch ---
    p_fetch = subparsers.add_parser(
        "fetch",
        help="Fetch a known reference event and generate a spectrogram.",
    )
    p_fetch.add_argument(
        "--event",
        type=str,
        required=True,
        help="Reference event name (e.g. GW150914, GW170817, GW231123).",
    )
    p_fetch.set_defaults(func=cmd_fetch)

    # --- scan ---
    p_scan = subparsers.add_parser(
        "scan",
        help="Batch-scan O4a segments and save spectrograms.",
    )
    p_scan.add_argument(
        "--detector",
        type=str,
        required=True,
        choices=["H1", "L1", "V1"],
        help="Detector identifier.",
    )
    p_scan.add_argument(
        "--hours",
        type=float,
        default=1.0,
        help="Duration to scan from O4a start (hours). Default: 1.0",
    )
    p_scan.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of parallel workers. Use 1 (default) for sequential mode "
            "(any hardware). Use cpu_count-2 for maximum speed on multi-core "
            "systems. Recommended: 6 for Ryzen 7 7800X3D."
        ),
    )
    p_scan.set_defaults(func=cmd_scan)

    # --- scan-extended (Phase 3.1) ---
    p_scan_ext = subparsers.add_parser(
        "scan-extended",
        help="[Phase 3.1] Extended 48h scan of H1 + L1 detectors.",
    )
    p_scan_ext.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of parallel workers. Use 1 (default) for sequential mode "
            "(any hardware). Use cpu_count-2 for maximum speed on multi-core "
            "systems. Recommended: 6 for Ryzen 7 7800X3D."
        ),
    )
    p_scan_ext.set_defaults(func=cmd_scan_extended)

    # --- encode (Phase 2) ---
    p_encode = subparsers.add_parser(
        "encode",
        help="[Phase 2] Extract DINOv2-Reg embeddings from spectrograms.",
    )
    p_encode.add_argument(
        "--input-dir",
        type=str,
        required=True,
        help="Directory containing spectrogram PNGs.",
    )
    p_encode.add_argument(
        "--output",
        type=str,
        required=True,
        help="Output .npy file path (e.g. data/embeddings/o4a_h1.npy).",
    )
    p_encode.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for inference. Default: 32.",
    )
    p_encode.set_defaults(func=cmd_encode)

    # --- cluster (Phase 3) ---
    p_cluster = subparsers.add_parser(
        "cluster",
        help="[Phase 3] Cluster embeddings to discover novel glitch classes.",
    )
    p_cluster.add_argument(
        "--input",
        type=str,
        required=True,
        help="Path to embedding .npy file (e.g. data/embeddings/o4a_h1_6h.npy).",
    )
    p_cluster.add_argument(
        "--output",
        type=str,
        default="data/clusters/",
        help="Output directory for cluster report. Default: data/clusters/",
    )
    p_cluster.set_defaults(func=cmd_cluster)

    # --- crosscheck (Phase 3.1) ---
    p_cross = subparsers.add_parser(
        "crosscheck",
        help="[Phase 3.1] Cross-check anomalous clusters against Gravity Spy.",
    )
    p_cross.add_argument(
        "--report",
        type=str,
        required=True,
        help="Path to cluster_report.json.",
    )
    p_cross.add_argument(
        "--metadata",
        type=str,
        required=True,
        help="Path to encoder metadata JSON (e.g. data/embeddings/o4a_h1_6h.json).",
    )
    p_cross.add_argument(
        "--detector",
        type=str,
        default="H1",
        choices=["H1", "L1", "V1"],
        help="Detector for Gravity Spy queries. Default: H1.",
    )
    p_cross.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON path for cross-check results.",
    )
    p_cross.set_defaults(func=cmd_crosscheck)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
