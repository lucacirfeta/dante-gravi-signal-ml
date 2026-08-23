"""Outcome-blind construction of the frozen DANTE-Light v4 identities."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v4_protocol import (
    PHASE_FEATURES, PROTOCOL_ID, SEED_METHOD, SEED_PURPOSES, derive_seed,
    protocol_digest, repository_reference, sha256_path, validate_protocol,
)
from src.dante_light.prefilter_v4_seal import build_confirmation_seal, build_identity_manifest


DETECTORS = ("H1", "L1")
KNOWN = ("Blip", "KoiFish", "ScatteredLight")
KNOWN_LABEL = {"Blip": "Blip", "KoiFish": "Koi_Fish", "ScatteredLight": "Scattered_Light"}
SYSTEMS = ("BBH_30_30", "BBH_10_10", "NSBH_10_1.4")
DISTANCES = (100.0, 200.0, 400.0, 800.0, 1600.0)
BLOCK_S = 4096
WINDOW_S = 32.0
PAD_S = 4.0
O4A_BOUNDS = (1368975618, 1389456018)
O3B_BOUNDS = (1256655618, 1269363618)


def _priority(seed: int, *parts: object) -> str:
    return hashlib.sha256(json.dumps([seed, *parts], separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _block(detector: str, gps: float) -> str:
    return f"{detector}:{math.floor(float(gps) / BLOCK_S)}"


def _contained(segments: Sequence[Sequence[int]], start: float, end: float) -> bool:
    return any(float(a) <= start and end <= float(b) for a, b in segments)


def fetch_segments(flag: str, start: int, end: int, *, attempts: int = 6) -> list[list[int]]:
    from gwosc.timeline import get_segments

    last: Exception | None = None
    for attempt in range(attempts):
        try:
            segments = get_segments(flag, start, end)
            result = [[int(item[0]), int(item[1])] for item in segments]
            if not result:
                raise ContractError(f"empty GWOSC segment response for {flag}")
            return result
        except Exception as exc:  # network errors are retried, never converted to PASS
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise ContractError(f"unable to freeze GWOSC segment flag {flag}: {last}")


def build_segment_snapshot() -> dict[str, Any]:
    specs = {
        "H1_O4A_CBC_CAT1": ("H1_CBC_CAT1", *O4A_BOUNDS),
        "L1_O4A_CBC_CAT1": ("L1_CBC_CAT1", *O4A_BOUNDS),
        "H1_O3B_DATA": ("H1_DATA", *O3B_BOUNDS),
        "L1_O3B_DATA": ("L1_DATA", *O3B_BOUNDS),
    }
    flags: dict[str, Any] = {}
    for name, (flag, start, end) in specs.items():
        segments = fetch_segments(flag, start, end)
        flags[name] = {
            "source": "GWOSC API v2 via gwosc.timeline.get_segments",
            "flag": flag, "gps_bounds": [start, end], "segments": segments,
            "segment_count": len(segments),
            "livetime_s": sum(b - a for a, b in segments),
            "segments_digest": canonical_json_sha256(segments),
        }
    body = {"schema_version": 1, "status": "FROZEN_GWOSC_SEGMENT_IDENTITIES", "flags": flags}
    return {**body, "snapshot_digest": canonical_json_sha256(body)}


def validate_segment_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(value); declared = body.pop("snapshot_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v4 segment snapshot digest mismatch")
    if body.get("status") != "FROZEN_GWOSC_SEGMENT_IDENTITIES":
        raise ContractError("v4 segment snapshot is not frozen")
    for item in body["flags"].values():
        if item["segments_digest"] != canonical_json_sha256(item["segments"]):
            raise ContractError("v4 segment list digest mismatch")
    return dict(value)


def prior_exclusions(root: Path) -> tuple[set[str], set[str], set[str]]:
    blocks: set[str] = set(); windows: set[str] = set(); source_ids: set[str] = set()
    for path in sorted((root / "config").glob("dante_light_prefilter_splits_v[12].jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            row = json.loads(line); window = row["window"]
            blocks.add(_block(str(window["detector"]), float(window["gps_start"])))
            windows.add(str(window["window_id"]))
            if row.get("gravityspy_id"): source_ids.add(str(row["gravityspy_id"]))
    return blocks, windows, source_ids


def _identity(*, role: str, detector: str, morphology: str, partition: str, gps: float,
              priority: str, source_kind: str, run: str, source_id: str,
              stratum: Mapping[str, Any]) -> dict[str, Any]:
    window = WindowIdentity(run, detector, float(gps), WINDOW_S)
    cohort_id = f"v4-{role}:{detector}:{source_id}"
    return {
        "schema_version": 1, "cohort_id": cohort_id, "role": role,
        "detector": detector, "morphology": morphology, "partition": partition,
        "partition_priority": priority, "retention_target": role != "background",
        "source": {"kind": source_kind, "run": run, "source_id": source_id},
        "stratum": dict(stratum), "window": window.to_dict(),
    }


def _partition(items: Sequence[dict[str, Any]], dev_n: int, confirm_n: int) -> list[tuple[dict[str, Any], str]]:
    chosen = sorted(items, key=lambda row: (row["priority"], row["source_id"]))[: dev_n + confirm_n]
    if len(chosen) != dev_n + confirm_n:
        raise ContractError(f"insufficient fresh candidates: {len(chosen)}/{dev_n + confirm_n}")
    return [(row, "development" if index < dev_n else "confirmation") for index, row in enumerate(chosen)]


def select_robust(root: Path, segments: Mapping[str, Any], seed: int,
                  excluded_blocks: set[str]) -> tuple[list[dict[str, Any]], set[str]]:
    path = root / "data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
    with path.open(newline="", encoding="utf-8") as stream: catalog = list(csv.DictReader(stream))
    rows: list[dict[str, Any]] = []; occupied = set(excluded_blocks)
    for detector in DETECTORS:
        segs = segments[f"{detector}_O4A_CBC_CAT1"]["segments"]
        candidates = []
        for source in catalog:
            if source["detector"] != detector or source["robustness_class"] != "ROBUST": continue
            event = float(source["gps_start"]); gps = event + 4.0; block = _block(detector, gps)
            if block in occupied or not _contained(segs, gps - PAD_S, gps + WINDOW_S + PAD_S): continue
            sid = f"taxonomy:{detector}:{event:.6f}"
            candidates.append({"gps": gps, "source_id": sid, "priority": _priority(seed, "robust", detector, sid)})
        # Enforce one row per detector block before applying partition quotas.
        unique: list[dict[str, Any]] = []; seen: set[str] = set()
        for item in sorted(candidates, key=lambda row: (row["priority"], row["source_id"])):
            key = _block(detector, item["gps"])
            if key not in seen: seen.add(key); unique.append(item)
        for item, partition in _partition(unique, 25, 60):
            rows.append(_identity(role="robust_candidate", detector=detector, morphology="unknown",
                partition=partition, gps=item["gps"], priority=item["priority"], source_kind="detector_aware_taxonomy",
                run="O4A", source_id=item["source_id"], stratum={"robustness_class": "ROBUST"}))
            occupied.add(_block(detector, item["gps"]))
    return rows, occupied


def select_known(root: Path, segments: Mapping[str, Any], seed: int, prior_blocks: set[str],
                 prior_source_ids: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []; occupied = set(prior_blocks)
    for detector in DETECTORS:
        path = root / f"data/reference/gs_classifications_O3b_{detector}.csv"
        with path.open(newline="", encoding="utf-8") as stream: catalog = list(csv.DictReader(stream))
        segs = segments[f"{detector}_O3B_DATA"]["segments"]
        pool: list[dict[str, Any]] = []
        for source in catalog:
            sid = str(source["gravityspy_id"]); label = str(source["ml_label"])
            morphology = next((m for m in KNOWN if KNOWN_LABEL[m] == label), None)
            if morphology is None or sid in prior_source_ids or source["ifo"] != detector: continue
            if float(source["ml_confidence"]) < 0.95 or float(source["snr"]) < 7.5: continue
            event = float(source["event_time"]); gps = event - 16.0; block = _block(detector, gps)
            if block in occupied or not _contained(segs, gps - PAD_S, gps + WINDOW_S + PAD_S): continue
            pool.append({"gps": gps, "source_id": sid, "morphology": morphology,
                         "priority": _priority(seed, "known", detector, morphology, sid)})
        # Global hash order prevents morphology-loop order from claiming shared blocks.
        quotas = {(m, p): 25 if p == "development" else 60 for m in KNOWN for p in ("development", "confirmation")}
        by_morph = {m: sorted((x for x in pool if x["morphology"] == m), key=lambda x: (x["priority"], x["source_id"])) for m in KNOWN}
        for morphology in KNOWN:
            candidates = [x for x in by_morph[morphology] if _block(detector, x["gps"]) not in occupied]
            unique=[]; seen=set()
            for item in candidates:
                key=_block(detector,item["gps"])
                if key not in seen: seen.add(key); unique.append(item)
            for item, partition in _partition(unique, 25, 60):
                rows.append(_identity(role="known_glitch", detector=detector, morphology=morphology,
                    partition=partition, gps=item["gps"], priority=item["priority"], source_kind="gravity_spy_o3b",
                    run="O3B", source_id=item["source_id"], stratum={"gravityspy_label": morphology}))
                occupied.add(_block(detector, item["gps"]))
    return rows


def common_o4a_windows(segments: Mapping[str, Any], excluded: set[str], seed: int) -> list[dict[str, Any]]:
    start = math.floor(O4A_BOUNDS[0] / BLOCK_S); end = math.ceil(O4A_BOUNDS[1] / BLOCK_S)
    result=[]
    for index in range(start, end):
        gps=float(index * BLOCK_S + 32)
        if any(f"{detector}:{index}" in excluded for detector in DETECTORS): continue
        if all(_contained(segments[f"{d}_O4A_CBC_CAT1"]["segments"], gps-PAD_S, gps+WINDOW_S+PAD_S) for d in DETECTORS):
            result.append({"gps": gps, "block": index, "priority": _priority(seed, "common-o4a", index)})
    return sorted(result, key=lambda x: (x["priority"], x["block"]))


def select_injections(segments: Mapping[str, Any], seed: int, excluded: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    windows = common_o4a_windows(segments, excluded, seed)
    needed = len(SYSTEMS) * len(DISTANCES) * 25
    if len(windows) < needed: raise ContractError(f"insufficient fresh common O4a blocks: {len(windows)}/{needed}")
    rng = np.random.default_rng(seed); trial_rows=[]; identities=[]; occupied=set(excluded)
    cursor=0
    for system in SYSTEMS:
        for distance in DISTANCES:
            cell=[]
            for trial_index in range(25):
                selected=windows[cursor]; cursor += 1; gps=selected["gps"]
                sid=f"v4inj:{system}:{distance:g}:{trial_index}"
                trial={"schema_version":1,"source_id":sid,"system":system,"distance_mpc":distance,
                    "trial_index":trial_index,"gps_start":gps,
                    "inclination_rad":float(np.arccos(rng.uniform(-1.0,1.0))),
                    "ra_rad":float(rng.uniform(0.0,2*np.pi)),"dec_rad":float(np.arcsin(rng.uniform(-1.0,1.0))),
                    "psi_rad":float(rng.uniform(0.0,np.pi)),"outcome_fields_present":[]}
                trial["trial_digest"]=canonical_json_sha256(trial); trial_rows.append(trial)
                cell.append({"trial":trial,"priority":_priority(seed,"partition",sid)})
                for detector in DETECTORS: occupied.add(_block(detector,gps))
            selected_dev={item["trial"]["source_id"] for item in sorted(cell,key=lambda x:x["priority"])[:7]}
            for item in cell:
                trial=item["trial"]; partition="development" if trial["source_id"] in selected_dev else "confirmation"
                for detector in DETECTORS:
                    identities.append(_identity(role="injection", detector=detector, morphology=system,
                        partition=partition, gps=trial["gps_start"], priority=item["priority"], source_kind="software_injection",
                        run="O4A", source_id=trial["source_id"], stratum={"system":system,"distance_mpc":distance,"trial_index":trial["trial_index"]}))
    return identities, trial_rows, occupied


def select_background(segments: Mapping[str, Any], seed: int, excluded: set[str]) -> list[dict[str, Any]]:
    rows=[]; start=math.floor(O4A_BOUNDS[0]/BLOCK_S); end=math.ceil(O4A_BOUNDS[1]/BLOCK_S)
    for detector in DETECTORS:
        candidates=[]; segs=segments[f"{detector}_O4A_CBC_CAT1"]["segments"]
        for index in range(start,end):
            gps=float(index*BLOCK_S+32); key=f"{detector}:{index}"
            if key in excluded or not _contained(segs,gps-PAD_S,gps+WINDOW_S+PAD_S): continue
            candidates.append({"gps":gps,"source_id":f"cat1:{detector}:{int(gps)}","priority":_priority(seed,"background",detector,index)})
        for item, partition in _partition(candidates,300,0):
            rows.append(_identity(role="background",detector=detector,morphology="clean_background",partition=partition,
                gps=item["gps"],priority=item["priority"],source_kind="gwosc_cbc_cat1",run="O4A",
                source_id=item["source_id"],stratum={}))
    return rows


def _ref(root: Path, relative: str) -> dict[str, str]:
    return repository_reference(root, root / relative)


def build_protocol(root: Path, segment_reference: Mapping[str, str]) -> dict[str, Any]:
    parent_paths = [
        "config/dante_light_prefilter_protocol_v3.json",
        "config/dante_light_prefilter_v4_feasibility.json",
        "artifacts/dante_light/prefilter_l4_v4_design/feasibility_summary_v4.json",
        "config/dante_light_prefilter_v4_power_analysis.json",
        "artifacts/dante_light/prefilter_l4_v4_design/confirmation_power_analysis_v4.json",
    ]
    parents=[_ref(root,path) for path in parent_paths]; parent_digests=[x["sha256"] for x in parents]
    phase_cfg=json.loads((root/"config/dante_light_prefilter_v4_feasibility.json").read_text())["phase_probe"]
    seeds={purpose:derive_seed(PROTOCOL_ID,purpose,parent_digests) for purpose in SEED_PURPOSES}
    body={
        "schema_version":4,"status":"FROZEN_OUTCOME_BLIND","protocol_id":PROTOCOL_ID,
        "parent_evidence":parents,
        "scientific_boundary":{"primary_development_run":"O4A","external_known_glitch_run":"O3B",
            "prospective_evaluation_run":"O4B","prior_v1_v3_interpretation":"EXPLORATORY_FOR_V4",
            "o4b_outcomes_allowed":False,"routing_enabled":False,"confirmation_outcomes_accessed_at_freeze":False},
        "required_detectors":list(DETECTORS),"required_morphologies_by_role":{"known_glitch":list(KNOWN),"injection":list(SYSTEMS)},
        "cohort_contract":{"block_duration_s":BLOCK_S,"window_duration_s":WINDOW_S,"whitening_pad_s":PAD_S,
            "counts_per_detector_stratum":{"background":{"development":300,"confirmation":0},
                "robust_candidate":{"development":25,"confirmation":60},"known_glitch":{"development":25,"confirmation":60},
                "injection":{"development":35,"confirmation":90}},
            "injection_distances_mpc":list(DISTANCES),"injection_trials_per_distance":{"development":7,"confirmation":18},
            "selection_uses_only_identity_availability_class_and_hash_priority":True,
            "require_no_detector_4096s_block_overlap_with_v1_v3_or_between_partitions":True,
            "robust_population_scope":"frozen_DANTE_ROBUST_decision_population_dominated_by_Family_01"},
        "source_contract":{"segment_snapshot":dict(segment_reference),"o4a_background_flag":"CBC_CAT1","o3b_known_glitch_flag":"DATA",
            "gravity_spy_minimum_confidence":0.95,"gravity_spy_minimum_snr":7.5},
        "seed_derivation":{"method":SEED_METHOD,"protocol_id":PROTOCOL_ID,"purposes":list(SEED_PURPOSES),
            "parent_digests":sorted(parent_digests),"seeds":seeds},
        "feature_extraction":{"feature_version":"prefilter-v4-phase-primary","features":list(PHASE_FEATURES),
            "sample_rate_hz":4096,"analysis_band_hz":[20.0,1024.0],"whitening_context_pad_s":4.0,
            "canonical_sequence":["fetch_padded_strain","whiten_context_pad_4s","extract_clean_32s_crop","phase_extractor"],
            "phase_parameters":{k:v for k,v in phase_cfg.items() if k not in {"benchmark_repetitions","warmup_repetitions","synthetic_control_repetitions","synthetic_seed","synthetic_chirp"}},
            "failure_policy":"DEFER_TO_EXACT_PATH_NO_IMPUTATION"},
        "development":{"cross_validation_folds":5,"cross_validation_method":"shuffled_group_k_fold_detector_4096s_block",
            "model":"l2_logistic_regression","regularization_c":1.0,"maximum_iterations":2000,
            "class_weighting":"equal_background_and_positive_strata","minimum_effective_reduction":0.5,
            "feature_subset_selection_allowed":False,"failed_primary_status":"V4_NOT_READY_NO_SAME_COHORT_RETUNING"},
        "confirmation":{"open_only_after_development_ready":True,"one_shot":True,"endpoint":"protected_stratum_retention_only",
            "minimum_retention":0.9,"minimum_wilson_lower":0.8,"wilson_confidence":0.95,"gate_operator":"AND",
            "n90_boundary":{"minimum_retained":81,"note":"80/90 passes Wilson lower 0.80 but fails point retention 0.90"},
            "can_authorize_operational_pass":False},
        "uncertainty":{"method":"detector_gps_4096s_block_bootstrap","n_resamples":2000,"confidence":0.95,"eligible_for_gate":False},
        "o4b":{"status":"SEALED_OUTSIDE_V4_DEVELOPMENT_AND_CONFIRMATION"},
    }
    return {**body,"protocol_digest":canonical_json_sha256(body)}


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n",encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("".join(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n" for row in rows),encoding="utf-8")


def build_freeze(root: Path, *, freeze_commit: str, refresh_segments: bool=False) -> dict[str, Any]:
    segment_path=root/"config/dante_light_prefilter_v4_segments.json"
    if refresh_segments or not segment_path.exists(): write_json(segment_path,build_segment_snapshot())
    segments=validate_segment_snapshot(json.loads(segment_path.read_text(encoding="utf-8")))
    protocol_path=root/"config/dante_light_prefilter_protocol_v4.json"
    protocol=build_protocol(root,repository_reference(root,segment_path)); write_json(protocol_path,protocol); validate_protocol(protocol)
    prior_blocks,_,prior_sources=prior_exclusions(root); seed=protocol["seed_derivation"]["seeds"]["cohort"]
    robust,occupied=select_robust(root,segments["flags"],seed,prior_blocks)
    injections,trials,occupied=select_injections(segments["flags"],protocol["seed_derivation"]["seeds"]["injection"],occupied)
    background=select_background(segments["flags"],seed,occupied)
    known=select_known(root,segments["flags"],seed,prior_blocks,prior_sources)
    trial_path=root/"config/dante_light_prefilter_v4_injection_trials.jsonl"; write_jsonl(trial_path,trials)
    sources=[repository_reference(root,segment_path),repository_reference(root,trial_path),
        _ref(root,"data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"),
        _ref(root,"data/reference/gs_classifications_O3b_H1.csv"),_ref(root,"data/reference/gs_classifications_O3b_L1.csv"),
        _ref(root,"config/dante_light_prefilter_splits_v1.jsonl"),_ref(root,"config/dante_light_prefilter_splits_v2.jsonl")]
    seed_contract={k:protocol["seed_derivation"][k] for k in ("method","protocol_id","purposes","parent_digests")}
    manifest=build_identity_manifest([*background,*robust,*known,*injections],protocol_reference=repository_reference(root,protocol_path),
        source_references=sources,selection_code_reference=_ref(root,"src/dante_light/prefilter_v4_freeze.py"),
        seed_derivation=seed_contract,prior_block_keys=prior_blocks)
    rows=manifest.pop("rows"); entries_path=root/"config/dante_light_prefilter_splits_v4.jsonl"; write_jsonl(entries_path,rows)
    manifest["entries_reference"]=repository_reference(root,entries_path); manifest["manifest_digest"]=canonical_json_sha256({k:v for k,v in manifest.items() if k!="manifest_digest"})
    split_path=root/"config/dante_light_prefilter_splits_v4.json"; write_json(split_path,manifest)
    # Rehydrate only for the existing strict seal implementation.
    complete=dict(manifest); complete.pop("entries_reference"); complete["rows"]=rows
    complete["manifest_digest"]=canonical_json_sha256({k:v for k,v in complete.items() if k!="manifest_digest"})
    seal=build_confirmation_seal(complete,freeze_commit=freeze_commit,code_references={
        "split_builder":_ref(root,"src/dante_light/prefilter_v4_freeze.py"),"phase_extractor":_ref(root,"src/dante_light/prefilter_v4_phase.py"),
        "seal_verifier":_ref(root,"src/dante_light/prefilter_v4_seal.py")},declared_storage_roots=[
            {"root_id":"repository","kind":"repository_relative","location":"."},
            {"root_id":"raw_strain","kind":"environment_alias","location":"DANTE_RAW_STRAIN_ROOT"}])
    seal["public_split_header_reference"]=repository_reference(root,split_path)
    seal["public_split_entries_reference"]=repository_reference(root,entries_path)
    # Recompute after adding public references.
    seal["seal_digest"]=canonical_json_sha256({k:v for k,v in seal.items() if k!="seal_digest"})
    seal_path=root/"config/dante_light_prefilter_v4_confirmation_seal.json"; write_json(seal_path,seal)
    counts={}
    for row in rows:
        key="/".join([row["role"],row["detector"],row["morphology"],row["partition"]]); counts[key]=counts.get(key,0)+1
    return {"protocol":protocol,"manifest_header":manifest,"rows":rows,"trials":trials,"seal":seal,"counts":counts}
