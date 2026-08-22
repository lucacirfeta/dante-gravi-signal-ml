#!/usr/bin/env python3
"""Lock DANTE-Light L4 v2 held-out evaluation inputs after development PASS."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v2_assembly import assemble_prefilter_v2_evaluation
from src.dante_light.prefilter_v2_protocol import DEFAULT_PROTOCOL_V2_PATH, load_prefilter_v2_protocol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--shadow", required=True, type=Path)
    parser.add_argument("--robust", required=True, type=Path)
    parser.add_argument("--known", required=True, type=Path)
    parser.add_argument("--injection", required=True, type=Path)
    parser.add_argument("--screening", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V2_PATH)
    args = parser.parse_args()
    try:
        contract, ledger = assemble_prefilter_v2_evaluation(
            ledgers={
                "background": args.background,
                "shadow": args.shadow,
                "robust_candidate": args.robust,
                "known_glitch": args.known,
                "injection": args.injection,
            },
            screening_path=args.screening,
            output_dir=args.output_dir,
            protocol=load_prefilter_v2_protocol(args.protocol),
        )
    except ContractError as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"LOCKED: {contract['contract_id']} ({ledger['row_count']} evaluation rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
