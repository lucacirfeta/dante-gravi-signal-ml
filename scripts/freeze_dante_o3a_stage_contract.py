#!/usr/bin/env python3
"""Freeze the O3a scale audit and author-approved parity stage contract."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_scale_adequacy import (  # noqa: E402
    write_scale_audit_and_stage_contract,
)


def main() -> int:
    audit, contract = write_scale_audit_and_stage_contract(root=ROOT)
    print(
        json.dumps(
            {
                "status": contract["status"],
                "scale_audit_status": audit["status"],
                "scale_audit_digest": audit["audit_digest"],
                "stage_contract_digest": contract["contract_digest"],
                "detectors": audit["detectors"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
