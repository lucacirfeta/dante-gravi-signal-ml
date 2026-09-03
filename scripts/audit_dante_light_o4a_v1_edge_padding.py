#!/usr/bin/env python3
"""Audit and preserve the O4a v1 file-edge padding failure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_v1_edge_audit import (  # noqa: E402
    DEFAULT_CACHE_ROOT,
    DEFAULT_OUTPUT,
    DEFAULT_RAW_ROOT,
    DEFAULT_RUN_DIR,
    reproduce_clipped_example,
    summarize_edge_failure,
    write_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-clipped-reproduction", action="store_true")
    args = parser.parse_args()

    audit = summarize_edge_failure(
        root=ROOT,
        run_dir=args.run_dir.resolve(),
        cache_root=args.cache_root.resolve(),
    )
    if not args.skip_clipped_reproduction:
        audit = reproduce_clipped_example(
            audit,
            root=ROOT,
            raw_root=args.raw_root.resolve(),
            device=args.device,
        )
    write_audit(audit, args.output.resolve())
    print(json.dumps(audit, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
