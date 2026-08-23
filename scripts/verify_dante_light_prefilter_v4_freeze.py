#!/usr/bin/env python3
"""Fail-closed verifier for the public DANTE-Light v4 identity freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_freeze import prior_exclusions, validate_segment_snapshot
from src.dante_light.prefilter_v4_protocol import load_protocol, repository_reference, sha256_path
from src.dante_light.prefilter_v4_seal import (
    EMPTY_ACCESS_LOG_SHA256, validate_identity_manifest, verify_unopened_seal,
)


def _reference(reference: dict[str,str]) -> None:
    path=ROOT/reference["path"]
    if not path.is_file() or sha256_path(path)!=reference["sha256"]:
        raise ContractError(f"reference mismatch: {reference['path']}")


def verify() -> dict[str,object]:
    protocol=load_protocol(ROOT/"config/dante_light_prefilter_protocol_v4.json").payload
    for ref in protocol["parent_evidence"]: _reference(ref)
    _reference(protocol["source_contract"]["segment_snapshot"])
    snapshot=json.loads((ROOT/protocol["source_contract"]["segment_snapshot"]["path"]).read_text(encoding="utf-8")); validate_segment_snapshot(snapshot)
    header_path=ROOT/"config/dante_light_prefilter_splits_v4.json"; header=json.loads(header_path.read_text(encoding="utf-8"))
    _reference(header["protocol_reference"]); _reference(header["selection_code_reference"])
    for ref in header["source_references"]: _reference(ref)
    _reference(header["entries_reference"])
    if header["manifest_digest"]!=canonical_json_sha256({k:v for k,v in header.items() if k!="manifest_digest"}):
        raise ContractError("public v4 split header digest mismatch")
    rows=[json.loads(line) for line in (ROOT/header["entries_reference"]["path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    complete={k:v for k,v in header.items() if k!="entries_reference"}; complete["rows"]=rows
    complete["manifest_digest"]=canonical_json_sha256({k:v for k,v in complete.items() if k!="manifest_digest"})
    validate_identity_manifest(complete)
    prior,_,_=prior_exclusions(ROOT)
    if set(complete["prior_block_exclusions"]["block_keys"])!=prior:
        raise ContractError("v4 prior block exclusions no longer match v1/v2")
    seal=json.loads((ROOT/"config/dante_light_prefilter_v4_confirmation_seal.json").read_text(encoding="utf-8"))
    for ref in seal["code_references"].values(): _reference(ref)
    _reference(seal["public_split_header_reference"]); _reference(seal["public_split_entries_reference"])
    access=ROOT/"config/dante_light_prefilter_v4_confirmation_access.jsonl"
    access_bytes=access.read_bytes() if access.exists() else b""
    verify_unopened_seal(complete,seal,access_log_bytes=access_bytes)
    counts={}
    for row in rows:
        key=(row["role"],row["detector"],row["morphology"],row["partition"]); counts[key]=counts.get(key,0)+1
    expected_total=600+170+510+750
    if len(rows)!=expected_total: raise ContractError(f"v4 row count mismatch: {len(rows)}/{expected_total}")
    if any(key in json.dumps(rows).lower() for key in ('"score"','"feature"','"snr"','"outcome"')):
        raise ContractError("outcome-bearing field leaked into v4 identities")
    trial_path=ROOT/"config/dante_light_prefilter_v4_injection_trials.jsonl"
    trials=[json.loads(line) for line in trial_path.read_text().splitlines() if line.strip()]
    if len(trials)!=375 or any(t["outcome_fields_present"] for t in trials):
        raise ContractError("v4 injection identity table is incomplete or outcome-bearing")
    if any(t["trial_digest"]!=canonical_json_sha256({k:v for k,v in t.items() if k!="trial_digest"}) for t in trials):
        raise ContractError("v4 injection trial digest mismatch")
    return {"status":"PASS_IDENTITY_ONLY_NOT_OPENED","rows":len(rows),"trials":len(trials),"access_log_sha256":hashlib.sha256(access_bytes).hexdigest()}


if __name__ == "__main__":
    try: print(json.dumps(verify(),indent=2,sort_keys=True))
    except ContractError as exc: print(f"FAIL: {exc}",file=sys.stderr); raise SystemExit(2)
