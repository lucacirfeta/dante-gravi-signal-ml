#!/usr/bin/env python3
"""Screen the frozen L4 v3 A+B primary on development ledgers only."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v3_protocol import (
    DEFAULT_PROTOCOL_V3_PATH,
    load_prefilter_v3_protocol,
    verify_prefilter_v3_sources,
)
from src.dante_light.prefilter_v3_screening import screen_prefilter_v3, write_screening_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--robust", required=True, type=Path)
    parser.add_argument("--known", required=True, type=Path)
    parser.add_argument("--injection", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V3_PATH)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v3_protocol(args.protocol)
        verify_prefilter_v3_sources(protocol, root=ROOT)
        result = screen_prefilter_v3(
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
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{result['status']}: {args.output}")
    return 0 if result["status"] == "READY_FOR_CONFIRMATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
