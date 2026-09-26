#!/usr/bin/env python3
"""Preflight, run or independently verify the O3a-only diagnostic PEM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_pem import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    preflight_inputs,
    run_native_pem,
    verify_native_pem,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("preflight", "run", "verify"), required=True)
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    args = parser.parse_args()
    if args.stage == "preflight":
        receipt, _targets, _exclusion = preflight_inputs(
            root=ROOT, external_root=args.external_root,
        )
        print(json.dumps(receipt, sort_keys=True, indent=2))
        return 0
    if args.stage == "run":
        receipt, run_dir = run_native_pem(root=ROOT, external_root=args.external_root)
    else:
        receipt, run_dir = verify_native_pem(root=ROOT, external_root=args.external_root)
    print(json.dumps({"run_dir": str(run_dir), **receipt}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
