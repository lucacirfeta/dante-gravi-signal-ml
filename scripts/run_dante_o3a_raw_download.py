#!/usr/bin/env python3
"""Preflight and run the frozen O3a raw download."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_raw_download import (  # noqa: E402
    DEFAULT_RESERVE_BYTES,
    DEFAULT_RETRIES,
    DEFAULT_WORKERS,
    execute_download,
    write_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=Path(r"E:\o3a"))
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    parser.add_argument(
        "--reserve-gib",
        type=float,
        default=DEFAULT_RESERVE_BYTES / 1024**3,
    )
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    preflight, preflight_path = write_preflight(
        root=ROOT,
        raw_root=args.raw_root,
        workers=args.workers,
        reserve_bytes=int(args.reserve_gib * 1024**3),
    )
    if args.preflight_only:
        result = {
            "status": preflight["status"],
            "run_key": preflight["run_key"],
            "preflight_path": str(preflight_path),
            "expected_file_count": preflight["expected_file_count"],
            "expected_download_bytes": preflight["expected_download_bytes"],
            "free_bytes_at_preflight": preflight["free_bytes_at_preflight"],
            "reserve_bytes": preflight["reserve_bytes"],
        }
    else:
        result = execute_download(
            root=ROOT,
            raw_root=args.raw_root,
            workers=args.workers,
            retries=args.retries,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
