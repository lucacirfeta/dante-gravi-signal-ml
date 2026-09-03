#!/usr/bin/env python3
"""Validate corrected manifest stitching against a frozen real O4a cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_context_validation import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_RAW_ROOT,
    OUTPUT,
    write_context_validation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    value = write_context_validation(
        raw_root=args.raw_root.resolve(),
        cache_root=args.cache_root.resolve(),
        output=args.output.resolve(),
    )
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
