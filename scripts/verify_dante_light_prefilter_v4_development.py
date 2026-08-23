#!/usr/bin/env python3
"""Recompute and verify the frozen DANTE-Light v4 development result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_dante_light_prefilter_v4_freeze import verify as verify_freeze
from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_protocol import load_protocol
from src.dante_light.prefilter_v4_screening import verify_screening_result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_protocol_v4.json",
    )
    args = parser.parse_args()
    ledgers = {
        "background": args.artifact_dir / "background_feature_ledger_v4_development.json",
        "robust_candidate": args.artifact_dir / "robust_candidate_feature_ledger_v4_development.json",
        "known_glitch": args.artifact_dir / "known_glitch_feature_ledger_v4_development.json",
        "injection": args.artifact_dir / "injection_feature_ledger_v4_development.json",
    }
    try:
        freeze = verify_freeze()
        result = verify_screening_result(
            args.artifact_dir / "screening_result_v4.json",
            ledgers=ledgers,
            protocol=load_protocol(args.protocol),
        )
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"freeze": freeze, "development": result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
