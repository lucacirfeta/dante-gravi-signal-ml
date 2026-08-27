#!/usr/bin/env python3
"""Fail-closed verifier for the v6 Phase-B planning audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_phase_b_planning import (
    build_planning_audit,
    load_planning_contract,
)


DEFAULT_CONFIG = ROOT / "config/dante_light_prefilter_v6_phase_b_planning_audit.json"
DEFAULT_ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "phase_b_planning_audit_v6.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()
    contract = load_planning_contract(args.config.resolve(), root=ROOT)
    payload = json.loads(args.artifact.resolve().read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-B planning artifact digest mismatch")
    if payload.get("status") != "PHASE_B_PLANNING_AUDIT_COMPLETE_AWAITING_DECISION":
        raise ContractError("v6 Phase-B planning audit is incomplete")
    if payload.get("contract_digest") != contract["contract_digest"]:
        raise ContractError("v6 Phase-B planning artifact uses the wrong contract")
    if any(payload["outcome_access"].values()):
        raise ContractError("v6 Phase-B planning audit accessed a forbidden outcome")
    if any(payload["decision"].values()):
        raise ContractError("v6 Phase-B planning audit made a forbidden decision")
    if payload["capacity"]["interpretation_boundary"]["allocation_selected"] is not False:
        raise ContractError("v6 Phase-B planning audit selected an allocation")
    if args.deep:
        regenerated = build_planning_audit(contract=contract, root=ROOT)
        if regenerated != payload:
            raise ContractError("v6 Phase-B planning deep recomputation mismatch")
    print(
        json.dumps(
            {
                "status": "PASS",
                "artifact_digest": declared,
                "deep": bool(args.deep),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
