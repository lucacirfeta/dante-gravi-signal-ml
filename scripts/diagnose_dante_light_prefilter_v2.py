#!/usr/bin/env python3
"""Run post-hoc OOF AUC and regularization diagnostics for frozen L4 v2."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_splits import load_prefilter_splits
from src.dante_light.prefilter_v2_diagnostics import (
    DEFAULT_DIAGNOSTIC_CONFIG,
    diagnose_prefilter_v2,
    load_diagnostic_config,
    write_diagnostic_result,
)
from src.dante_light.prefilter_v2_protocol import DEFAULT_PROTOCOL_V2_PATH, load_prefilter_v2_protocol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background", required=True, type=Path)
    parser.add_argument("--robust", required=True, type=Path)
    parser.add_argument("--known", required=True, type=Path)
    parser.add_argument("--injection", required=True, type=Path)
    parser.add_argument("--screening", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--split", type=Path, default=ROOT / "config/dante_light_prefilter_splits_v2.json")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V2_PATH)
    parser.add_argument("--diagnostic-config", type=Path, default=DEFAULT_DIAGNOSTIC_CONFIG)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v2_protocol(args.protocol)
        diagnostic_config = load_diagnostic_config(args.diagnostic_config, protocol=protocol)
        split = load_prefilter_splits(args.split)
        if split.get("protocol") != protocol.reference:
            raise ContractError("v2 diagnostic split is bound to a different protocol")
        expected = {role: cohort["split_sha256"] for role, cohort in split["cohorts"].items()}
        result = diagnose_prefilter_v2(
            ledgers={
                "background": args.background,
                "robust_candidate": args.robust,
                "known_glitch": args.known,
                "injection": args.injection,
            },
            expected_split_hashes=expected,
            frozen_screening_path=args.screening,
            protocol=protocol,
            diagnostic_config=diagnostic_config,
        )
        write_diagnostic_result(result, args.output)
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(f"DIAGNOSTIC_ONLY: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
