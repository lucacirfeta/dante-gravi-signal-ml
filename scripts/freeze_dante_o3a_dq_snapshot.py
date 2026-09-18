#!/usr/bin/env python3
"""Freeze or verify the public O3a H1/L1 CBC_CAT1 metadata snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_contract import (  # noqa: E402
    load_dq_snapshot,
    write_dq_snapshot,
    write_scope_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        snapshot = load_dq_snapshot(root=ROOT)
    else:
        snapshot = write_dq_snapshot(root=ROOT)
        write_scope_contract(root=ROOT)
        snapshot = load_dq_snapshot(root=ROOT)
    print(
        json.dumps(
            {
                "status": "PASS",
                "snapshot_digest": snapshot["snapshot_digest"],
                "summaries": snapshot["summaries"],
                "outcome_data_accessed": snapshot["source"]["outcome_data_accessed"],
                "strain_data_accessed": snapshot["source"]["strain_data_accessed"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
