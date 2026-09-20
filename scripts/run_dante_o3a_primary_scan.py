#!/usr/bin/env python3
"""Preflight, run, resume, or verify the frozen O3a primary scan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_primary_scan import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    DEFAULT_RAW_ROOT,
    clear_infrastructure_failure,
    preflight_primary_scan,
    run_primary_scan,
    verify_primary_scan,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument(
        "--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT
    )
    parser.add_argument("--device", default="cuda")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--clear-infrastructure-failure", action="store_true")
    args = parser.parse_args()

    if args.clear_infrastructure_failure:
        archive = clear_infrastructure_failure(
            root=ROOT,
            external_root=args.external_root,
            device=args.device,
        )
        print(json.dumps({"archived_failure": str(archive)}, indent=2))
        return 0
    if args.preflight:
        value, run_dir = preflight_primary_scan(
            root=ROOT,
            raw_root=args.raw_root,
            external_root=args.external_root,
            device=args.device,
        )
    elif args.verify:
        value, run_dir = verify_primary_scan(
            root=ROOT,
            external_root=args.external_root,
        )
    else:
        value, run_dir = run_primary_scan(
            root=ROOT,
            raw_root=args.raw_root,
            external_root=args.external_root,
            device=args.device,
        )
    print(
        json.dumps(
            {
                "status": value["status"],
                "run_key": value["run_key"],
                "run_dir": str(run_dir),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
