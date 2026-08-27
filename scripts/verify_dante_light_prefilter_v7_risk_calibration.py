#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from src.dante_light.prefilter_v7_risk_calibration import DEFAULT_CACHE, verify_result
parser = argparse.ArgumentParser()
parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
parser.add_argument("--require-cache", action="store_true")
args = parser.parse_args()
print(json.dumps(verify_result(root=ROOT, cache_root=args.cache_root if args.require_cache else None), indent=2, sort_keys=True))
