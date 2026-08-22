#!/usr/bin/env python3
"""Recompute and verify sealed DANTE-Light L4 v3 development evidence."""

from __future__ import annotations

import argparse
import json
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
from src.dante_light.prefilter_v3_screening import verify_screening_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--robust", required=True, type=Path)
    parser.add_argument("--known", required=True, type=Path)
    parser.add_argument("--injection", required=True, type=Path)
    parser.add_argument("--screening", required=True, type=Path)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V3_PATH)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v3_protocol(args.protocol)
        source_check = verify_prefilter_v3_sources(protocol, root=ROOT)
        verification = verify_screening_result(
            args.screening,
            ledgers={
                "background": args.background,
                "robust_candidate": args.robust,
                "known_glitch": args.known,
                "injection": args.injection,
            },
            protocol=protocol,
        )
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"source_check": source_check, "screening_check": verification},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
