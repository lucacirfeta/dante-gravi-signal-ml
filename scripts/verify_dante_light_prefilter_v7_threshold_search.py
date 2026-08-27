#!/usr/bin/env python3
"""Verify and replay the frozen v7 threshold-search result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_threshold_search import (
    DEFAULT_CACHE,
    verify_threshold_search_result,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--require-cache", action="store_true")
    args = parser.parse_args()
    result = verify_threshold_search_result(
        root=ROOT, cache_root=args.cache_root if args.require_cache else None
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
