#!/usr/bin/env python3
"""Verify the frozen DANTE-Light v5 development result and screening gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError  # noqa: E402
from src.dante_light.prefilter_v5_development_contract import (  # noqa: E402
    load_development_contract,
)
from src.dante_light.prefilter_v5_screening import verify_screening  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=None)
    args = parser.parse_args()
    try:
        contract = load_development_contract(root=ROOT)
        result = verify_screening(root=ROOT, cache_root=args.cache_root)
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "contract_digest": contract["development_contract_digest"],
                "verification": result,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
