#!/usr/bin/env python3
"""Fit or independently verify O3a initial detector-specific p99 thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_initial_thresholds import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    run_initial_thresholds,
    verify_initial_thresholds,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    function = verify_initial_thresholds if args.verify else run_initial_thresholds
    value, run_dir = function(root=ROOT, external_root=args.external_root)
    print(
        json.dumps(
            {
                "status": value["status"],
                "run_key": value["run_key"],
                "run_dir": str(run_dir),
                "thresholds": value["thresholds"],
                "adequacy_gate": value["adequacy_gate"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

