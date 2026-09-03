#!/usr/bin/env python3
"""Run or verify corrected O4a native rescoring with calibration v2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_execution import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_PRIMARY_ROOT,
)
from src.dante_light.o4a_corrected_native import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_NATIVE_ROOT,
)
from src.dante_light.o4a_corrected_native_calibration import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_CALIBRATION_ROOT,
)
from src.dante_light.o4a_corrected_native_index import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_INDEX_ROOT,
)
from src.dante_light.o4a_corrected_native_rescore_v2 import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    run_native_rescore_v2,
    verify_native_rescore_v2,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    parser.add_argument("--primary-external-root", type=Path, default=DEFAULT_PRIMARY_ROOT)
    parser.add_argument("--native-external-root", type=Path, default=DEFAULT_NATIVE_ROOT)
    parser.add_argument(
        "--calibration-external-root", type=Path, default=DEFAULT_CALIBRATION_ROOT
    )
    parser.add_argument("--index-external-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    common = {
        "root": ROOT,
        "primary_external_root": args.primary_external_root.resolve(),
        "native_external_root": args.native_external_root.resolve(),
        "calibration_external_root": args.calibration_external_root.resolve(),
        "index_external_root": args.index_external_root.resolve(),
        "external_root": args.external_root.resolve(),
        "device": args.device,
    }
    if args.stage == "run":
        summary, run_dir = run_native_rescore_v2(
            raw_root=args.raw_root.resolve(),
            workers=args.workers,
            batch_size=args.batch_size,
            **common,
        )
    else:
        summary, run_dir = verify_native_rescore_v2(**common)
    print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
