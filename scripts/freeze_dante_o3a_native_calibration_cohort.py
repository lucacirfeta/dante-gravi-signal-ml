#!/usr/bin/env python3
"""Freeze or verify outcome-blind O3a native-calibration identities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_calibration_cohort import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    freeze_native_calibration_cohort,
    verify_native_calibration_cohort,
    write_cohort_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--contract-only", action="store_true")
    mode.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.contract_only:
        print(json.dumps({"contract": write_cohort_contract(root=ROOT)}, indent=2, sort_keys=True))
        return 0
    summary, run_dir = (
        verify_native_calibration_cohort(root=ROOT, external_root=args.external_root)
        if args.verify else
        freeze_native_calibration_cohort(root=ROOT, external_root=args.external_root)
    )
    print(json.dumps({"summary": summary, "run_dir": str(run_dir)}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
