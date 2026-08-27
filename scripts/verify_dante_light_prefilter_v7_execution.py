#!/usr/bin/env python3
"""Fail-closed verifier for authorized v7 training-only artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training import (
    DEFAULT_AUTHORIZATION, DEFAULT_CACHE, DEFAULT_LEDGER_SUMMARY,
    DEFAULT_TARGETS, DEFAULT_TRAINING_SUMMARY, file_sha256,
    training_rows,
)
from src.dante_light.prefilter_v7_verification import (
    load_training_authorization_for_verification,
)


def verify(cache_root: Path, *, require_training: bool) -> dict:
    authorization = load_training_authorization_for_verification(
        DEFAULT_AUTHORIZATION, root=ROOT
    )
    rows = training_rows(root=ROOT)
    ledger = json.loads(DEFAULT_LEDGER_SUMMARY.read_text(encoding="utf-8"))
    ledger_body = dict(ledger); ledger_digest = ledger_body.pop("artifact_digest", None)
    if ledger_digest != canonical_json_sha256(ledger_body):
        raise ContractError("v7 ledger digest mismatch")
    if ledger.get("status") != "COMPLETE_TRAINING_ONLY" or ledger.get("row_count") != 600:
        raise ContractError("v7 ledger is not complete")
    if ledger.get("authorization_digest") != authorization["authorization_digest"]:
        raise ContractError("v7 ledger authorization mismatch")
    if ledger["compact_targets"].get("sha256") != file_sha256(DEFAULT_TARGETS):
        raise ContractError("v7 compact target file changed")
    targets = [json.loads(line) for line in DEFAULT_TARGETS.read_text(encoding="utf-8").splitlines() if line]
    if len(targets) != 600 or {row["identity_id"] for row in targets} != {row["identity_id"] for row in rows}:
        raise ContractError("v7 compact target identities are incomplete")
    if any(ledger["accessed"][key] for key in ("threshold_search", "risk_calibration", "confirmation", "o4b")):
        raise ContractError("v7 ledger crossed a protected boundary")
    result = {"authorization": "PASS", "teacher_ledger": "PASS", "training": "NOT_REQUIRED"}
    if require_training:
        training = json.loads(DEFAULT_TRAINING_SUMMARY.read_text(encoding="utf-8"))
        body = dict(training); declared = body.pop("artifact_digest", None)
        if declared != canonical_json_sha256(body):
            raise ContractError("v7 training summary digest mismatch")
        if training.get("status") != "TRAINING_COMPLETE_NON_PROMOTABLE":
            raise ContractError("v7 five-member training is not complete")
        if training.get("member_count") != 5 or training.get("all_five_members_complete") is not True:
            raise ContractError("v7 ensemble is incomplete")
        run_dir = cache_root.resolve() / training["cache_location"]["run_subdirectory"]
        for member in training["members"]:
            if member.get("status") != "TRAINING_COMPLETE_NON_PROMOTABLE":
                raise ContractError("v7 ensemble contains a failed member")
            model = run_dir / member["best_model"]["path"]
            metrics = run_dir / member["metrics"]["path"]
            if not model.is_file() or file_sha256(model) != member["best_model"]["sha256"]:
                raise ContractError("v7 member checkpoint mismatch")
            if not metrics.is_file() or file_sha256(metrics) != member["metrics"]["sha256"]:
                raise ContractError("v7 member metrics mismatch")
        if any(training[key] for key in ("threshold_search", "risk_calibration", "confirmation", "o4b")):
            raise ContractError("v7 training crossed a protected boundary")
        if training.get("threshold_search_automatic_access") is not False or training.get("routing_enabled") is not False or training.get("candidate_promoted") is not False:
            raise ContractError("v7 training silently promoted or opened routing")
        result["training"] = "PASS_NON_PROMOTABLE"
    return {"status": "PASS", **result}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--require-training", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.cache_root, require_training=args.require_training), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
