#!/usr/bin/env python3
"""Tune the L4 prefilter on frozen development-only feature ledgers."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_tuning import tune_prefilter, write_tuning_result
from src.dante_light.prefilter_splits import load_prefilter_splits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--robust", required=True, type=Path)
    parser.add_argument("--known", required=True, type=Path)
    parser.add_argument("--injection", required=True, type=Path)
    parser.add_argument(
        "--split",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_splits_v1.json",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        split = load_prefilter_splits(args.split)
        expected_split_hashes = {
            role: cohort["split_sha256"] for role, cohort in split["cohorts"].items()
        }
        result = tune_prefilter(
            ledgers={
                "background": args.background,
                "robust_candidate": args.robust,
                "known_glitch": args.known,
                "injection": args.injection,
            },
            expected_split_hashes=expected_split_hashes,
        )
        write_tuning_result(result, args.output)
    except ContractError as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {args.output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
