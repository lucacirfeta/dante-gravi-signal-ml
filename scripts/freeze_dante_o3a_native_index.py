#!/usr/bin/env python3
"""Freeze the approved O3a native-index contract and run real-data preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_index import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    preflight_native_index,
    write_index_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--contract-only", action="store_true")
    args = parser.parse_args()
    contract = write_index_contract(root=ROOT)
    result: dict[str, object] = {"contract": contract}
    if not args.contract_only:
        preflight, run_dir = preflight_native_index(
            root=ROOT, external_root=args.external_root
        )
        result.update({"preflight": preflight, "run_dir": str(run_dir)})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
