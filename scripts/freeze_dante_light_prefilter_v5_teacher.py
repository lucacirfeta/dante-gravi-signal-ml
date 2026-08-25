#!/usr/bin/env python3
"""Build the author-approved native-O4a v5 teacher contract."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_teacher import (  # noqa: E402
    DEFAULT_CONTRACT,
    build_teacher_contract,
    validate_teacher_contract,
)


def main() -> int:
    contract = build_teacher_contract(root=ROOT)
    validate_teacher_contract(contract, root=ROOT)
    DEFAULT_CONTRACT.write_bytes(
        (json.dumps(contract, indent=2, sort_keys=True) + "\n").encode("utf-8")
    )
    print(json.dumps({"status": "FROZEN_TRAINING_ONLY", "teacher_contract_digest": contract["teacher_contract_digest"], "training_identity_count": contract["training_identity_count"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
