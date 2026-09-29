#!/usr/bin/env python3
"""Plan, execute or independently verify the frozen paired diagnostic PEM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_o4a_common_pem_execution import (  # noqa: E402
    freeze_plan,
    run_one,
    verify_one,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("plan", "run", "verify"), required=True)
    parser.add_argument("--run", choices=("O3a", "O4a"))
    args = parser.parse_args()
    if args.stage == "plan":
        if args.run is not None:
            parser.error("--run is only accepted by run and verify")
        receipt, path = freeze_plan(root=ROOT)
    else:
        if args.run is None:
            parser.error("--run is required by run and verify")
        action = run_one if args.stage == "run" else verify_one
        receipt, path = action(run=args.run, root=ROOT)
    print(json.dumps({"path": str(path), **receipt}, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
