#!/usr/bin/env python3
"""Freeze, fit or replay-verify detector-specific O3a native thresholds."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_thresholds import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    execute_thresholds,
    freeze_threshold_contract,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    args = parser.parse_args()
    if args.freeze:
        result = freeze_threshold_contract(root=ROOT)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "contract_digest": result["contract_digest"],
                }
            )
        )
    else:
        result, directory = execute_thresholds(
            root=ROOT, external_root=args.external_root, verify=args.verify
        )
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "artifact_digest": result["artifact_digest"],
                    "run_dir": str(directory),
                    "replay_verified": args.verify,
                }
            )
        )


if __name__ == "__main__":
    main()
