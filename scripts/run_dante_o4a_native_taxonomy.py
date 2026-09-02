#!/usr/bin/env python3
"""Run or verify the corrected O4a native-class taxonomy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_execution import (
    DEFAULT_EXTERNAL_ROOT as DEFAULT_PRIMARY_ROOT,
)
from src.dante_light.o4a_corrected_native_classification import (
    DEFAULT_EXTERNAL_ROOT as DEFAULT_CLASSIFICATION_ROOT,
)
from src.dante_light.o4a_corrected_native_taxonomy import (
    DEFAULT_EXTERNAL_ROOT,
    run_native_taxonomy,
    verify_native_taxonomy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    parser.add_argument(
        "--primary-external-root", type=Path, default=DEFAULT_PRIMARY_ROOT
    )
    parser.add_argument(
        "--classification-external-root",
        type=Path,
        default=DEFAULT_CLASSIFICATION_ROOT,
    )
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    common = {
        "root": ROOT,
        "primary_external_root": args.primary_external_root.resolve(),
        "classification_external_root": args.classification_external_root.resolve(),
        "external_root": args.external_root.resolve(),
        "device": args.device,
    }
    if args.stage == "run":
        summary, run_dir = run_native_taxonomy(**common)
    else:
        summary, run_dir = verify_native_taxonomy(**common)
    print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
