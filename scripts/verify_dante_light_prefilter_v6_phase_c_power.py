#!/usr/bin/env python3
"""Fail-closed verifier for the frozen DANTE-Light v6 Phase-C gate."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v6_phase_c_power import analyze_power, load_power_contract


ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v6_design/phase_c_fidelity_power_v6.json"


def verify() -> dict[str, object]:
    recomputed = analyze_power(load_power_contract())
    if not ARTIFACT.is_file():
        raise ContractError("v6 Phase-C power artifact is missing")
    committed = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    if committed != recomputed:
        raise ContractError("v6 Phase-C power artifact does not recompute exactly")
    return {
        "status": "PASS",
        "artifact_digest": recomputed["artifact_digest"],
        "n_blocks_per_detector": recomputed["sampling_contract"]["blocks_per_detector"],
        "approximate_single_cell_power": recomputed["frozen_recommendation"]["approximate_pass_probability_at_true_alternative"],
        "outcomes_accessed": recomputed["outcomes_accessed"],
    }


def main() -> int:
    print(json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
