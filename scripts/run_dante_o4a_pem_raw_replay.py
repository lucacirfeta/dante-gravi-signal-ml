#!/usr/bin/env python3
"""Reacquire and independently verify O4a PEM numerical event contexts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_pem_raw_replay import run_replay, verify_replay  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    parser.add_argument("--external-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    args = parser.parse_args()
    if args.stage == "run":
        summary, run_dir = run_replay(root=ROOT, external_root=args.external_root)
    else:
        if args.run_dir is None:
            parser.error("--run-dir is required for --stage verify")
        run_dir = args.run_dir.resolve()
        summary = verify_replay(root=ROOT, run_dir=run_dir)
    print(json.dumps({"run_dir": str(run_dir), **summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
