"""Create the outcome-blind DANTE-Light v7 selective-deferral freeze."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_freeze import build_freeze, verify_freeze


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-basis-commit")
    args = parser.parse_args()
    commit = args.freeze_basis_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    build_freeze(ROOT, freeze_basis_commit=commit)
    print(json.dumps(verify_freeze(ROOT), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
