#!/usr/bin/env python3
"""Verify the DANTE-Light v5 training freeze and its teacher cache."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_training_contract import (  # noqa: E402
    DEFAULT_CONTRACT,
    verify_training_freeze_against_cache,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cache-root", type=Path, default=None)
    args = parser.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    print(
        json.dumps(
            verify_training_freeze_against_cache(
                contract,
                root=ROOT,
                cache_root=args.cache_root,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
