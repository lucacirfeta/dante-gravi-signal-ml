#!/usr/bin/env python3
"""Execute only the authorized teacher-ledger and fit stages of v7."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_training import (
    DEFAULT_CACHE,
    build_teacher_ledger,
    execution_code_references,
    run_training,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("ledger", "train", "all"), default="all")
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--device", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    references = execution_code_references(ROOT)
    result = None
    if args.stage in {"ledger", "all"}:
        result = build_teacher_ledger(
            root=ROOT, cache_root=args.cache_root, code_references=references,
            workers=args.workers, retries=args.retries, device=args.device, limit=args.limit,
        )
    if args.stage in {"train", "all"}:
        if args.limit is not None:
            raise SystemExit("--limit is valid only for the ledger stage")
        result = run_training(
            root=ROOT, cache_root=args.cache_root, code_references=references,
            device_name=args.device,
        )
    print(json.dumps({
        "status": result["status"],
        "artifact_digest": result["artifact_digest"],
        "run_key": result["run_key"],
    }))
    return 0 if not result["status"].startswith("FAILED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
