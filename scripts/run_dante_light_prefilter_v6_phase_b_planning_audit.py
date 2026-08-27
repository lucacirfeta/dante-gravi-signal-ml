#!/usr/bin/env python3
"""Generate the outcome-blind DANTE-Light v6 Phase-B planning audit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v6_phase_b_planning import (
    build_planning_audit,
    load_planning_contract,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v6_phase_b_planning_audit.json"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "phase_b_planning_audit_v6.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    contract = load_planning_contract(args.config.resolve(), root=ROOT)
    payload = build_planning_audit(contract=contract, root=ROOT)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, output)
    print(json.dumps({"status": "PASS", "artifact_digest": payload["artifact_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
