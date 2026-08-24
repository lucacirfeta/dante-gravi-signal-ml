#!/usr/bin/env python3
"""Build the outcome-blind DANTE-Light v5 protocol, split, and seal."""

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
from src.dante_light.prefilter_v5_freeze import build_freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-commit", help="full code commit bound into the seal")
    args = parser.parse_args()
    commit = args.freeze_commit or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    try:
        result = build_freeze(ROOT, freeze_commit=commit)
    except ContractError as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS_IDENTITY_ONLY_NOT_OPENED", "freeze_commit": commit, "rows": len(result["rows"]), "trials": len(result["trials"]), "counts": result["counts"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
