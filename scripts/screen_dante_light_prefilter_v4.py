#!/usr/bin/env python3
"""Screen the frozen DANTE-Light v4 phase primary on development only."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_dante_light_prefilter_v4_freeze import verify as verify_freeze
from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_protocol import load_protocol
from src.dante_light.prefilter_v4_screening import screen_prefilter_v4, write_screening_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--robust", required=True, type=Path)
    parser.add_argument("--known", required=True, type=Path)
    parser.add_argument("--injection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_protocol_v4.json",
    )
    args = parser.parse_args()
    try:
        freeze = verify_freeze()
        if freeze["status"] != "PASS_IDENTITY_ONLY_NOT_OPENED":
            raise ContractError("v4 identity freeze is not unopened")
        protocol = load_protocol(args.protocol)
        result = screen_prefilter_v4(
            ledgers={
                "background": args.background,
                "robust_candidate": args.robust,
                "known_glitch": args.known,
                "injection": args.injection,
            },
            protocol=protocol,
        )
        write_screening_result(result, args.output)
    except ContractError as exc:
        print(f"V4_NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {args.output}")
    print("SEALED: no unlock receipt was created; confirmation and O4b were not accessed")
    return 0 if result["status"] == "READY_FOR_CONFIRMATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
