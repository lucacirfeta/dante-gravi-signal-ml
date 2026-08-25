#!/usr/bin/env python3
"""Fail-closed verifier for the v5 retrospective training-only diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_training_diagnostics import (  # noqa: E402
    DEFAULT_OUTPUT,
    verify_diagnostic_result,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = json.loads(args.artifact.read_text(encoding="utf-8"))
    print(
        json.dumps(
            verify_diagnostic_result(result, root=ROOT),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
