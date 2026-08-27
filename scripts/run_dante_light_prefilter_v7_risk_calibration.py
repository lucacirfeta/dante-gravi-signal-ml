#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from src.dante_light.prefilter_v7_risk_calibration import DEFAULT_CACHE, DEFAULT_RECEIPT, DEFAULT_TRAINING_CACHE, run_risk_calibration
from src.dante_light.prefilter_v7_teacher_stability import run_training_canary
parser = argparse.ArgumentParser()
parser.add_argument("--stage", choices=("guard", "execute", "all"), default="all")
parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
parser.add_argument("--training-cache-root", type=Path, default=DEFAULT_TRAINING_CACHE)
parser.add_argument("--workers", type=int, default=4)
parser.add_argument("--retries", type=int, default=3)
parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
args = parser.parse_args()
output = None
if args.stage in {"guard", "all"}:
    output = run_training_canary(requested_partition="risk_calibration", root=ROOT, cache_root=args.training_cache_root, device=args.device, prior_partition_access_entries=0, write_path=DEFAULT_RECEIPT)
if args.stage in {"execute", "all"}:
    output = run_risk_calibration(root=ROOT, cache_root=args.cache_root, training_cache_root=args.training_cache_root, receipt_path=DEFAULT_RECEIPT, workers=args.workers, retries=args.retries, device_name=args.device)
print(json.dumps({"status": output["status"], "digest": output.get("risk_calibration_result_digest", output.get("stability_receipt_digest"))}, indent=2, sort_keys=True))
