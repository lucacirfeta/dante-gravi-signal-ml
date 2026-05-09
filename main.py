#!/usr/bin/env python3
"""gravi-signal-ml — CLI entry point.

Provides subcommands for each pipeline stage:

    fetch   — Download and process a known reference event (PoC)
    scan    — Batch-scan O4a segments for a detector
    encode  — Extract embeddings from spectrograms (Phase 2)
    cluster — Cluster embeddings to discover novel classes (Phase 3)

Usage:
    python main.py fetch   --event GW150914
    python main.py scan    --detector H1 --hours 2
    python main.py encode  --input-dir data/spectrograms/
    python main.py cluster --input-dir data/embeddings/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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

    # Run batch processing
    saved_paths = batch_process(segments, detector, output_dir)

    total_duration = sum(end - start for start, end in segments)
    logger.info(
        "Scan complete: %d processed, %d skipped, %.1f h scanned",
        len(saved_paths),
        len(segments) - len(saved_paths),
        total_duration / 3600,
    )


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
    input_dir = Path(args.input_dir)
    logger.info("=== CLUSTER: %s ===", input_dir)
    logger.warning("Not implemented yet — Phase 3.")
    print("Not implemented yet — Phase 3.")
    print(f"Will cluster embeddings from: {input_dir}")


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
    p_scan.set_defaults(func=cmd_scan)

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
        "--input-dir",
        type=str,
        default="data/embeddings/",
        help="Directory containing embedding .npy files.",
    )
    p_cluster.set_defaults(func=cmd_cluster)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
