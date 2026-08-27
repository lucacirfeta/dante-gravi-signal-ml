#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_cost_reaudit import (
    DEFAULT_CACHE,
    DEFAULT_TRAINING_CACHE,
    run_cost_reaudit,
)


parser = argparse.ArgumentParser()
parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
parser.add_argument("--training-cache-root", type=Path, default=DEFAULT_TRAINING_CACHE)
args = parser.parse_args()
result = run_cost_reaudit(
    root=ROOT,
    cache_root=args.cache_root,
    training_cache_root=args.training_cache_root,
)
print(json.dumps({"status": result["status"], "digest": result["cost_reaudit_result_digest"]}, indent=2, sort_keys=True))
