#!/usr/bin/env python3
"""Evaluate, but never promote, a locked DANTE-Light prefilter contract."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_evaluation import evaluate_prefilter, write_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = evaluate_prefilter(contract_path=args.contract, ledger_path=args.ledger)
        write_result(result, args.output)
    except ContractError as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {args.output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
