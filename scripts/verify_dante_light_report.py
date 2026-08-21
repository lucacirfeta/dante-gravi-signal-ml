#!/usr/bin/env python3
"""Verify a DANTE-Light generated report receipt and all bound artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dante_light.reporting import verify_run_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    result = verify_run_report(args.receipt, root=args.root)
    print(
        json.dumps(
            {
                "status": "PASS",
                "report_path": result["report_path"],
                "report_sha256": result["report_sha256"],
                "receipt_sha256": result["receipt_sha256"],
                "source_count": len(result["source_artifacts"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
