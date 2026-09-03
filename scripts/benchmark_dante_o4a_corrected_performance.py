#!/usr/bin/env python
"""Freeze, run, or verify the corrected O4a performance benchmark."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_performance import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    run_performance_benchmark,
    verify_performance_result,
    write_performance_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("freeze", "run", "verify"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    if args.stage == "freeze":
        value = write_performance_contract(args.root)
        print(value["contract_digest"])
    elif args.stage == "run":
        value, path = run_performance_benchmark(
            root=args.root,
            raw_root=args.raw_root,
            external_root=args.external_root,
            device=args.device,
        )
        print(value["status"])
        print(path)
    else:
        value = verify_performance_result(root=args.root, external_root=args.external_root)
        print(value["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
