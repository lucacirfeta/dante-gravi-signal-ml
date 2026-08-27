#!/usr/bin/env python3
"""Verify the v7 teacher fingerprint and optionally execute its canary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v7_teacher_stability import (
    DEFAULT_BASELINE,
    DEFAULT_CACHE,
    run_training_canary,
    verify_stability_contract,
    verify_stability_receipt,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--run-canary", action="store_true")
    parser.add_argument(
        "--requested-partition",
        choices=("baseline", "threshold_search", "risk_calibration", "confirmation"),
        default="baseline",
    )
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args()
    contract = verify_stability_contract(root=ROOT)
    replacing_baseline = args.run_canary and args.write_baseline
    baseline = None
    if not replacing_baseline:
        if not DEFAULT_BASELINE.is_file():
            raise ContractError("saved v7 teacher-stability baseline is absent")
        baseline = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
        verify_stability_receipt(baseline, contract=contract)
        if baseline.get("requested_partition") != "baseline":
            raise ContractError("saved teacher-stability evidence is not the baseline")
    result = {
        "status": "PASS_STRUCTURE_ONLY",
        "stability_contract_digest": contract["stability_contract_digest"],
        "teacher_fingerprint_digest": contract["teacher_fingerprint"]["fingerprint_digest"],
        "canary": "PASS_SAVED_BASELINE",
        "saved_baseline_receipt_digest": (
            baseline["stability_receipt_digest"]
            if baseline is not None
            else "REPLACED_BY_FULL_CANARY"
        ),
        "accessed": contract["accessed"],
    }
    if args.run_canary:
        destination = DEFAULT_BASELINE if args.write_baseline else None
        receipt = run_training_canary(
            requested_partition=args.requested_partition,
            root=ROOT,
            cache_root=args.cache_root,
            write_path=destination,
        )
        verify_stability_receipt(receipt, contract=contract)
        result.update({
            "status": "PASS_FULL_CANARY",
            "canary": receipt["status"],
            "canary_count": receipt["canary_count"],
            "stability_receipt_digest": receipt["stability_receipt_digest"],
            "accessed": receipt["accessed"],
        })
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
