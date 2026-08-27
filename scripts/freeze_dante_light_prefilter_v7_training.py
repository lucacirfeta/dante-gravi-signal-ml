"""Freeze the outcome-blind DANTE-Light v7 training contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_training_freeze import (
    build_training_freeze,
    validate_training_freeze,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-basis-commit")
    args = parser.parse_args()
    commit = args.freeze_basis_commit or subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    contract = build_training_freeze(
        ROOT, freeze_basis_commit=commit, write_artifacts=True
    )
    print(json.dumps(validate_training_freeze(contract, root=ROOT), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
