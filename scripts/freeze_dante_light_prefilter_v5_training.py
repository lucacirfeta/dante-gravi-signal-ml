#!/usr/bin/env python3
"""Freeze the approved DANTE-Light v5 training-only contract."""

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
    build_training_freeze,
    validate_training_freeze,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract, _assignments, _targets = build_training_freeze(
        root=ROOT,
        cache_root=args.cache_root,
        write_artifacts=True,
    )
    args.contract.write_bytes(
        (json.dumps(contract, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    validate_training_freeze(contract, root=ROOT)
    print(
        json.dumps(
            {
                "status": contract["status"],
                "training_contract_digest": contract["training_contract_digest"],
                "block_counts": contract["internal_split"]["block_counts"],
                "row_counts": contract["internal_split"]["row_counts"],
                "target_standardization": contract["target_standardization"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
