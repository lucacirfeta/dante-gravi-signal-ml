#!/usr/bin/env python3
"""Run the frozen O3a initial-calibration raw-acceptance stage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_initial_calibration_acceptance import (  # noqa: E402
    DEFAULT_ENCODER_BATCH_SIZE,
    DEFAULT_EXTERNAL_ROOT,
    DEFAULT_MAX_PREPROCESS_IN_FLIGHT,
    DEFAULT_RAW_ROOT,
    DEFAULT_WORKERS,
    execute_acceptance,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument(
        "--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument(
        "--encoder-batch-size", type=int, default=DEFAULT_ENCODER_BATCH_SIZE
    )
    parser.add_argument(
        "--max-preprocess-in-flight",
        type=int,
        default=DEFAULT_MAX_PREPROCESS_IN_FLIGHT,
    )
    args = parser.parse_args()
    value = execute_acceptance(
        root=ROOT,
        raw_root=args.raw_root,
        external_root=args.external_root,
        device=args.device,
        workers=args.workers,
        encoder_batch_size=args.encoder_batch_size,
        max_preprocess_in_flight=args.max_preprocess_in_flight,
    )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
