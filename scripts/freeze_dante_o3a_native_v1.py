#!/usr/bin/env python3
"""Freeze and verify the approved O3a runtime and scope contracts in WSL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_contract import (  # noqa: E402
    load_runtime_contract,
    load_scope_contract,
    write_runtime_and_scope_contracts,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="validate checked-in contracts without rewriting them",
    )
    args = parser.parse_args()
    if args.verify_only:
        runtime = load_runtime_contract(root=ROOT, require_current=True)
        scope = load_scope_contract(root=ROOT)
    else:
        runtime, scope = write_runtime_and_scope_contracts(root=ROOT)
        load_runtime_contract(root=ROOT, require_current=True)
        load_scope_contract(root=ROOT)
    print(
        json.dumps(
            {
                "status": "PASS",
                "runtime_contract_digest": runtime["contract_digest"],
                "scope_contract_digest": scope["contract_digest"],
                "pipeline_execution_allowed": scope["pipeline_execution_allowed"],
                "unresolved_stage_parameters": scope["unresolved_stage_parameters"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
