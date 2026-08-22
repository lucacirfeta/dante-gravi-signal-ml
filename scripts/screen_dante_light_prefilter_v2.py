#!/usr/bin/env python3
"""Run block-cross-validated L4 v2 screening on development rows only."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_splits import load_prefilter_splits
from src.dante_light.prefilter_v2_protocol import (
    DEFAULT_PROTOCOL_V2_PATH,
    load_prefilter_v2_protocol,
)
from src.dante_light.prefilter_v2_screening import (
    screen_prefilter_v2,
    write_screening_result,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--robust", required=True, type=Path)
    parser.add_argument("--known", required=True, type=Path)
    parser.add_argument("--injection", required=True, type=Path)
    parser.add_argument(
        "--split",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_splits_v2.json",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V2_PATH)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v2_protocol(args.protocol)
        split = load_prefilter_splits(args.split)
        if split.get("protocol") != protocol.reference:
            raise ContractError("v2 split is bound to a different protocol")
        expected = {role: cohort["split_sha256"] for role, cohort in split["cohorts"].items()}
        result = screen_prefilter_v2(
            ledgers={
                "background": args.background,
                "robust_candidate": args.robust,
                "known_glitch": args.known,
                "injection": args.injection,
            },
            expected_split_hashes=expected,
            protocol=protocol,
        )
        write_screening_result(result, args.output)
    except ContractError as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {args.output}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
