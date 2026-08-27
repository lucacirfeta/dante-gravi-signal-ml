#!/usr/bin/env python3
"""Fail-closed verifier for the outcome-blind v6 Phase-B freeze."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_phase_b import load_phase_b_contract
from scripts.freeze_dante_light_prefilter_v6_phase_b import OUTPUT, build


def verify() -> dict[str, object]:
    load_phase_b_contract()
    expected = build()
    if not OUTPUT.is_file():
        raise ContractError("v6 Phase-B freeze artifact is missing")
    observed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if observed != expected:
        raise ContractError("v6 Phase-B freeze artifact does not recompute exactly")
    body = dict(observed)
    declared = body.pop("artifact_digest")
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-B freeze artifact digest mismatch")
    return {
        "status": "PASS",
        "contract_digest": observed["contract_digest"],
        "artifact_digest": declared,
        "arm_count": len(observed["arms"]),
        "replicate_count": len(observed["replicate_seeds"]),
        "outcomes_accessed": observed["outcomes_accessed"],
    }


def main() -> int:
    print(json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
