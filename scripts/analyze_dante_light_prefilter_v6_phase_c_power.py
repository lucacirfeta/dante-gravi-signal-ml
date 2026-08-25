#!/usr/bin/env python3
"""Recompute the outcome-blind DANTE-Light v6 Phase-C power artifact."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.evidence import atomic_json
from src.dante_light.prefilter_v6_phase_c_power import analyze_power, load_power_contract


OUTPUT = ROOT / "artifacts/dante_light/prefilter_l4_v6_design/phase_c_fidelity_power_v6.json"


def main() -> int:
    result = analyze_power(load_power_contract())
    atomic_json(OUTPUT, result)
    print(json.dumps({
        "status": result["status"],
        "artifact_digest": result["artifact_digest"],
        "output": str(OUTPUT),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
