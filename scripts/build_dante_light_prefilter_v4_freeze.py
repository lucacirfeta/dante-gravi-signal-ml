#!/usr/bin/env python3
"""Freeze the outcome-blind DANTE-Light phase-aware v4 protocol and cohorts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_freeze import build_freeze


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-commit", help="full code commit bound into the confirmation seal")
    parser.add_argument("--refresh-segments", action="store_true")
    args=parser.parse_args()
    commit=args.freeze_commit or subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    try:
        result=build_freeze(ROOT,freeze_commit=commit,refresh_segments=args.refresh_segments)
    except ContractError as exc:
        print(f"NOT_READY: {exc}",file=sys.stderr); return 2
    print(json.dumps({"status":"PASS_IDENTITY_ONLY_NOT_OPENED","freeze_commit":commit,"counts":result["counts"]},indent=2,sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
