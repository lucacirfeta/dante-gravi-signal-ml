#!/usr/bin/env python3
"""Run the v7 teacher guard and authorized threshold search."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_teacher_stability import run_training_canary
from src.dante_light.prefilter_v7_threshold_search import (
    DEFAULT_CACHE,
    DEFAULT_STABILITY_RECEIPT,
    DEFAULT_TRAINING_CACHE,
    run_threshold_search,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("guard", "execute", "all"), default="all")
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--training-cache-root", type=Path, default=DEFAULT_TRAINING_CACHE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    output = None
    if args.stage in {"guard", "all"}:
        output = run_training_canary(
            requested_partition="threshold_search",
            root=ROOT,
            cache_root=args.training_cache_root,
            device=args.device,
            prior_partition_access_entries=0,
            write_path=DEFAULT_STABILITY_RECEIPT,
        )
    if args.stage in {"execute", "all"}:
        output = run_threshold_search(
            root=ROOT,
            cache_root=args.cache_root,
            training_cache_root=args.training_cache_root,
            stability_receipt_path=DEFAULT_STABILITY_RECEIPT,
            workers=args.workers,
            retries=args.retries,
            device_name=args.device,
        )
    print(json.dumps({
        "status": output["status"],
        "digest": output.get(
            "threshold_search_result_digest", output.get("stability_receipt_digest")
        ),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
