#!/usr/bin/env python3
"""Freeze or verify the corrected O4a native-threshold calibration cohort."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_native_calibration import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    freeze_native_calibration_cohort,
    verify_native_calibration_cohort,
)
from src.dante_light.o4a_corrected_execution import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_PRIMARY_EXTERNAL_ROOT,
)
from src.dante_light.o4a_corrected_native import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_NATIVE_EXTERNAL_ROOT,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("freeze", "verify"), required=True)
    parser.add_argument(
        "--primary-external-root", type=Path, default=DEFAULT_PRIMARY_EXTERNAL_ROOT
    )
    parser.add_argument(
        "--native-external-root", type=Path, default=DEFAULT_NATIVE_EXTERNAL_ROOT
    )
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    common = {
        "root": ROOT,
        "primary_external_root": args.primary_external_root.resolve(),
        "native_external_root": args.native_external_root.resolve(),
        "external_root": args.external_root.resolve(),
        "device": args.device,
    }
    if args.stage == "freeze":
        summary, run_dir = freeze_native_calibration_cohort(
            raw_root=args.raw_root.resolve(), **common
        )
    else:
        summary, run_dir = verify_native_calibration_cohort(**common)
    print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
