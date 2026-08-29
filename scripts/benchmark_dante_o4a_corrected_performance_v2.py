#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_performance_v2 import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    run_performance_benchmark_v2,
    verify_performance_result_v2,
    write_performance_contract_v2,
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
        result = write_performance_contract_v2(args.root)
        print(result["contract_digest"])
    elif args.stage == "run":
        result, path = run_performance_benchmark_v2(
            root=args.root,
            raw_root=args.raw_root,
            external_root=args.external_root,
            device=args.device,
        )
        print(result["status"])
        print(path)
    else:
        result = verify_performance_result_v2(root=args.root, external_root=args.external_root)
        print(result["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
