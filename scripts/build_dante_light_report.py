#!/usr/bin/env python3
"""Build one provenance-bound human report from DANTE-Light run evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dante_light.reporting import build_run_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prospective", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--followup-dir", type=Path)
    parser.add_argument("--auxiliary", type=Path)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    result = build_run_report(
        prospective_path=args.prospective,
        output_path=args.output,
        receipt_path=args.receipt,
        followup_dir=args.followup_dir,
        auxiliary_path=args.auxiliary,
        root=args.root,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
