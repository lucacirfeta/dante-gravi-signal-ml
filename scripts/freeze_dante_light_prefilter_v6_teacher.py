#!/usr/bin/env python3
"""Freeze the v6 Phase-B native-teacher contract after raw-cache completion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v6_teacher import build_teacher_contract, _atomic_json


DEFAULT_RAW = ROOT / "artifacts/dante_light/prefilter_l4_v6_cache/phase_b_raw_cache_summary_v6.json"
DEFAULT_OUTPUT = ROOT / "config/dante_light_prefilter_v6_teacher_contract.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-cache-summary", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract = build_teacher_contract(root=ROOT, raw_cache_summary_path=args.raw_cache_summary.resolve())
    _atomic_json(args.output.resolve(), contract)
    print(json.dumps({"status": "PASS", "teacher_contract_digest": contract["teacher_contract_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
