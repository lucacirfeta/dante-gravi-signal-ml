#!/usr/bin/env python3
"""Run or verify corrected O4a asymmetric physical coincidence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_execution import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_PRIMARY_ROOT,
)
from src.dante_light.o4a_corrected_native_classification import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_CLASSIFICATION_ROOT,
)
from src.dante_light.o4a_corrected_native_coincidence import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    run_native_coincidence,
    verify_native_coincidence,
)
from src.dante_light.o4a_corrected_native_index import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_INDEX_ROOT,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument(
        "--primary-external-root", type=Path, default=DEFAULT_PRIMARY_ROOT
    )
    parser.add_argument(
        "--classification-external-root",
        type=Path,
        default=DEFAULT_CLASSIFICATION_ROOT,
    )
    parser.add_argument("--index-external-root", type=Path, default=DEFAULT_INDEX_ROOT)
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    common = {
        "root": ROOT,
        "primary_external_root": args.primary_external_root.resolve(),
        "classification_external_root": args.classification_external_root.resolve(),
        "index_external_root": args.index_external_root.resolve(),
        "external_root": args.external_root.resolve(),
        "device": args.device,
    }
    if args.stage == "run":
        summary, run_dir = run_native_coincidence(
            raw_root=args.raw_root.resolve(),
            workers=args.workers,
            batch_size=args.batch_size,
            **common,
        )
    else:
        summary, run_dir = verify_native_coincidence(**common)
    print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
