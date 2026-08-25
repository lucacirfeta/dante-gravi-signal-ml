#!/usr/bin/env python3
"""Recompute the frozen DANTE-Light v5 power contract without outcomes."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.evidence import atomic_json
from src.dante_light.prefilter_v5_power import analyze_power, load_power_config


OUTPUT = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/confirmation_power_analysis_v5.json"


def main() -> int:
    config, design = load_power_config()
    result = analyze_power(config, design)
    atomic_json(OUTPUT, result)
    print(json.dumps({"status": result["status"], "artifact_digest": result["artifact_digest"], "output": str(OUTPUT)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
