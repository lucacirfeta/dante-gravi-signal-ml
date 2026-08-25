#!/usr/bin/env python3
"""Generate compact outcome-blind evidence for the frozen v6 Phase-B design."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.prefilter_v6_phase_b import derive_seed, load_phase_b_contract


OUTPUT = ROOT / "artifacts/dante_light/prefilter_l4_v6_design/phase_b_freeze_v6.json"


def build() -> dict[str, object]:
    contract = load_phase_b_contract()
    body: dict[str, object] = {
        "schema_version": 1,
        "status": "FROZEN_PHASE_B_SCREENING_CONTRACT_VERIFIED",
        "contract_digest": contract["contract_digest"],
        "arms": contract["arms"],
        "replicate_seeds": [
            derive_seed(contract["contract_digest"], "phase_b_model_replicate", index)
            for index in range(int(contract["replicates"]["count"]))
        ],
        "objective": contract["objective"],
        "selection_rule": contract["selection_rule"],
        "outcomes_accessed": [],
        "authorized_next_action": "download_frozen_missing_windows_then_build_phase_b_teacher_ledger",
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def main() -> int:
    payload = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(OUTPUT.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, OUTPUT)
    print(json.dumps({"status": "PASS", "artifact_digest": payload["artifact_digest"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
