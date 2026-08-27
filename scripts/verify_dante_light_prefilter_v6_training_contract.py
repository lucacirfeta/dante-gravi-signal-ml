#!/usr/bin/env python3
"""Verify the frozen v6 Phase-B training input contract."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v6_training_contract import load_training_freeze


def main() -> int:
    contract = load_training_freeze(root=ROOT)
    print(
        json.dumps(
            {
                "status": "PASS",
                "training_contract_digest": contract["training_contract_digest"],
                "population": contract["population"],
                "access_boundary": contract["access_boundary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
