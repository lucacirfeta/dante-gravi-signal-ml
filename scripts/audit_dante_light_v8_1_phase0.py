#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.v8_1_phase0 import verify_result, write_result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build or verify the frozen DANTE-Light v8.1 phase-zero audit."
    )
    parser.add_argument("--write", action="store_true", help="write the compact result")
    args = parser.parse_args()
    result = write_result(root=ROOT) if args.write else verify_result(root=ROOT)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
