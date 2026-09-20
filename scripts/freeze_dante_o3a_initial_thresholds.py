#!/usr/bin/env python3
"""Freeze the O3a detector-specific initial p99 threshold contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_initial_thresholds import (  # noqa: E402
    write_threshold_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acceptance-summary", type=Path, required=True)
    args = parser.parse_args()
    value = write_threshold_contract(
        root=ROOT, acceptance_summary=args.acceptance_summary
    )
    print(
        json.dumps(
            {
                "status": value["status"],
                "contract_digest": value["contract_digest"],
                "acceptance_artifact_digest": value["parents"][
                    "acceptance_run"
                ]["artifact_digest"],
                "method": value["method"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

