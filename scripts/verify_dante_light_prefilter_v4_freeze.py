#!/usr/bin/env python3
"""Fail-closed verifier for the public DANTE-Light v4 identity freeze."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_protocol import load_protocol, sha256_path
from src.dante_light.prefilter_v4_seal import (
    EMPTY_ACCESS_LOG_SHA256, validate_identity_manifest, verify_unopened_seal,
)

DISTANCES=(100.0,200.0,400.0,800.0,1600.0)
KNOWN=("Blip","KoiFish","ScatteredLight")
SYSTEMS=("BBH_30_30","BBH_10_10","NSBH_10_1.4")
PAD_S=4.0
WINDOW_S=32.0


def _contained(segments,start,end):
    return any(float(left)<=start and end<=float(right) for left,right in segments)


def _hardware_injection_clear(flags,detector,start,end):
    return all(
        not (float(left)<end and start<float(right))
        for suffix in ("HW_INJ","CBC_INJ","BURST_INJ")
        for left,right in flags[f"{detector}_O4A_{suffix}"]["segments"]
    )


def _prior_exclusions():
    blocks=set(); source_ids=set()
    for path in sorted((ROOT/"config").glob("dante_light_prefilter_splits_v[12].jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            row=json.loads(line); window=row["window"]
            blocks.add(f"{window['detector']}:{math.floor(float(window['gps_start'])/4096)}")
            if row.get("gravityspy_id"): source_ids.add(str(row["gravityspy_id"]))
    return blocks,source_ids


def _validate_segment_snapshot(value):
    body=dict(value); declared=body.pop("snapshot_digest",None)
    if declared!=canonical_json_sha256(body): raise ContractError("v4 segment snapshot digest mismatch")
    if body.get("status")!="FROZEN_GWOSC_SEGMENT_IDENTITIES": raise ContractError("v4 segment snapshot is not frozen")
    for item in body["flags"].values():
        if item["segments_digest"]!=canonical_json_sha256(item["segments"]): raise ContractError("v4 segment list digest mismatch")


def _reference(reference: dict[str,str]) -> None:
    path=ROOT/reference["path"]
    if not path.is_file() or sha256_path(path)!=reference["sha256"]:
        raise ContractError(f"reference mismatch: {reference['path']}")


def verify() -> dict[str,object]:
    protocol=load_protocol(ROOT/"config/dante_light_prefilter_protocol_v4.json").payload
    for ref in protocol["parent_evidence"]: _reference(ref)
    _reference(protocol["source_contract"]["segment_snapshot"])
    for ref in protocol["source_contract"]["gravity_spy_filtered_snapshot"]: _reference(ref)
    known_header_ref,known_entries_ref=protocol["source_contract"]["gravity_spy_filtered_snapshot"]
    known_header=json.loads((ROOT/known_header_ref["path"]).read_text(encoding="utf-8"))
    known_rows=[json.loads(line) for line in (ROOT/known_entries_ref["path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    if known_header["snapshot_digest"]!=canonical_json_sha256({k:v for k,v in known_header.items() if k!="snapshot_digest"}):
        raise ContractError("known-glitch source snapshot header digest mismatch")
    if known_header["entries_reference"]!=known_entries_ref or known_header["row_count"]!=len(known_rows):
        raise ContractError("known-glitch source snapshot entries/count mismatch")
    if known_header["rows_digest"]!=canonical_json_sha256(known_rows):
        raise ContractError("known-glitch source snapshot rows digest mismatch")
    if any(set(row)!={"detector","event_time","gravityspy_id","ml_confidence","morphology","snr","source_priority"} for row in known_rows):
        raise ContractError("known-glitch compact source contains unexpected fields")
    known_block_keys=[(row["detector"],row["morphology"],math.floor((float(row["event_time"])-16.0)/4096)) for row in known_rows]
    if len(known_block_keys)!=len(set(known_block_keys)):
        raise ContractError("known-glitch compact source has duplicate detector/morphology blocks")
    snapshot=json.loads((ROOT/protocol["source_contract"]["segment_snapshot"]["path"]).read_text(encoding="utf-8")); _validate_segment_snapshot(snapshot)
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
    prior,prior_source_ids=_prior_exclusions()
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
    expected_counts={}
    for detector in ("H1","L1"):
        expected_counts[("background",detector,"clean_background","development")]=300
        expected_counts[("robust_candidate",detector,"unknown","development")]=25
        expected_counts[("robust_candidate",detector,"unknown","confirmation")]=60
        for morphology in KNOWN:
            expected_counts[("known_glitch",detector,morphology,"development")]=25
            expected_counts[("known_glitch",detector,morphology,"confirmation")]=60
        for system in SYSTEMS:
            expected_counts[("injection",detector,system,"development")]=35
            expected_counts[("injection",detector,system,"confirmation")]=90
    if counts!=expected_counts: raise ContractError("v4 per-stratum identity counts changed")
    if any(key in json.dumps(rows).lower() for key in ('"score"','"feature"','"snr"','"outcome"')):
        raise ContractError("outcome-bearing field leaked into v4 identities")
    known_ids={row["source"]["source_id"] for row in rows if row["role"]=="known_glitch"}
    if known_ids & prior_source_ids: raise ContractError("v4 reuses a prior Gravity Spy identity")
    for row in rows:
        window=row["window"]; start=float(window["gps_start"])-PAD_S; end=float(window["gps_start"])+WINDOW_S+PAD_S
        detector=row["detector"]
        if window["run"]=="O4A":
            if not _contained(snapshot["flags"][f"{detector}_O4A_CBC_CAT1"]["segments"],start,end):
                raise ContractError("v4 O4a padded window is outside CBC_CAT1")
            if not _hardware_injection_clear(snapshot["flags"],detector,start,end):
                raise ContractError("v4 O4a identity overlaps a hardware-injection flag")
        elif row["role"]=="known_glitch":
            if not _contained(snapshot["flags"][f"{detector}_O3B_DATA"]["segments"],start,end):
                raise ContractError("v4 O3b known-glitch padded window is outside DATA")
    trial_path=ROOT/"config/dante_light_prefilter_v4_injection_trials.jsonl"
    trials=[json.loads(line) for line in trial_path.read_text().splitlines() if line.strip()]
    if len(trials)!=375 or any(t["outcome_fields_present"] for t in trials):
        raise ContractError("v4 injection identity table is incomplete or outcome-bearing")
    if any(t["trial_digest"]!=canonical_json_sha256({k:v for k,v in t.items() if k!="trial_digest"}) for t in trials):
        raise ContractError("v4 injection trial digest mismatch")
    trial_by_id={trial["source_id"]:trial for trial in trials}
    if len(trial_by_id)!=375: raise ContractError("duplicate v4 injection trial identity")
    trial_cells=Counter((trial["system"],float(trial["distance_mpc"])) for trial in trials)
    if trial_cells!={ (system,distance):25 for system in SYSTEMS for distance in DISTANCES }:
        raise ContractError("v4 injection system/distance grid changed")
    injection_rows=[row for row in rows if row["role"]=="injection"]
    if {row["source"]["source_id"] for row in injection_rows}!=set(trial_by_id):
        raise ContractError("v4 injection manifest/trial-table identity mismatch")
    grouped={}
    for row in injection_rows: grouped.setdefault(row["source"]["source_id"],[]).append(row)
    for source_id,pair in grouped.items():
        if len(pair)!=2 or {row["detector"] for row in pair}!={"H1","L1"}:
            raise ContractError("v4 injection trial is not paired across detectors")
        trial=trial_by_id[source_id]
        if any(row["partition"]!=pair[0]["partition"] or row["window"]["gps_start"]!=trial["gps_start"] for row in pair):
            raise ContractError("v4 injection detector pair disagrees on partition or GPS")
    return {"status":"PASS_IDENTITY_ONLY_NOT_OPENED","rows":len(rows),"trials":len(trials),"access_log_sha256":hashlib.sha256(access_bytes).hexdigest()}


if __name__ == "__main__":
    try: print(json.dumps(verify(),indent=2,sort_keys=True))
    except ContractError as exc: print(f"FAIL: {exc}",file=sys.stderr); raise SystemExit(2)
