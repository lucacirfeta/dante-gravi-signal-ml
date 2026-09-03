#!/usr/bin/env python3
"""Run or verify corrected O4a PEM diagnostic follow-up."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_native_classification import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_CLASSIFICATION_ROOT,
)
from src.dante_light.o4a_corrected_native_coincidence import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_COINCIDENCE_ROOT,
)
from src.dante_light.o4a_corrected_native_pem import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    run_native_pem,
    verify_native_pem,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--coincidence-external-root", type=Path, default=DEFAULT_COINCIDENCE_ROOT
    )
    parser.add_argument(
        "--classification-external-root",
        type=Path,
        default=DEFAULT_CLASSIFICATION_ROOT,
    )
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    args = parser.parse_args()
    common = {
        "root": ROOT,
        "coincidence_external_root": args.coincidence_external_root.resolve(),
        "classification_external_root": args.classification_external_root.resolve(),
        "external_root": args.external_root.resolve(),
    }
    if args.stage == "run":
        summary, run_dir = run_native_pem(raw_root=args.raw_root.resolve(), **common)
    else:
        summary, run_dir = verify_native_pem(**common)
    print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
