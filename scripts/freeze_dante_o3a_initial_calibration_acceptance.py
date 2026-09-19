#!/usr/bin/env python3
"""Freeze the O3a initial-calibration raw-acceptance execution contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_initial_calibration_acceptance import (  # noqa: E402
    write_acceptance_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-download-summary", type=Path, required=True)
    args = parser.parse_args()
    value = write_acceptance_contract(
        root=ROOT,
        raw_download_summary=args.raw_download_summary,
    )
    print(
        json.dumps(
            {
                "status": value["status"],
                "contract_digest": value["contract_digest"],
                "raw_manifest_sha256": value["verified_raw_input"][
                    "manifest_sha256"
                ],
                "top_k": value["method_parity"]["top_k"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
