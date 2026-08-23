#!/usr/bin/env python
"""Recompute the non-gating DANTE-Light v4 confirmation power proposal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.evidence import atomic_json
from src.dante_light.prefilter_v4_power import analyze_power, load_power_config


DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "dante_light"
    / "prefilter_l4_v4_design"
    / "confirmation_power_analysis_v4.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config = load_power_config(args.config) if args.config else load_power_config()
    result = analyze_power(config)
    atomic_json(args.output, result)
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(args.output),
                "artifact_digest": result["artifact_digest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
