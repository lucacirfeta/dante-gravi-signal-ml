#!/usr/bin/env python3
"""Execute or verify the frozen O3a native cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_cohort import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    DEFAULT_PRIMARY_EXTERNAL_ROOT,
    DEFAULT_RAW_ROOT,
    clear_infrastructure_failure,
    execute_native_cohort,
    verify_native_cohort,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument(
        "--primary-external-root",
        type=Path,
        default=DEFAULT_PRIMARY_EXTERNAL_ROOT,
    )
    parser.add_argument(
        "--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--clear-infrastructure-failure", action="store_true")
    args = parser.parse_args()
    if args.clear_infrastructure_failure:
        path = clear_infrastructure_failure(
            root=ROOT, external_root=args.external_root
        )
        print(json.dumps({"archived_failure": str(path)}, indent=2))
        return 0
    if args.verify:
        summary, run_dir = verify_native_cohort(
            root=ROOT,
            primary_external_root=args.primary_external_root,
            external_root=args.external_root,
        )
    else:
        summary, run_dir = execute_native_cohort(
            root=ROOT,
            raw_root=args.raw_root,
            primary_external_root=args.primary_external_root,
            external_root=args.external_root,
        )
    print(
        json.dumps(
            {"summary": summary, "run_dir": str(run_dir)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
