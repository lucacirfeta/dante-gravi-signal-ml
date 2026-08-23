"""Development-only feature extraction for the frozen DANTE-Light v4 cohort."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, FailClosedReason, WindowIdentity, canonical_json_sha256
from src.dante_light.executor import DeferredWindow, WindowTask
from src.dante_light.prefilter_v4 import extract_prefilter_v4_features
from src.dante_light.prefilter_v4_protocol import PrefilterProtocolV4, repository_reference
from src.dante_light.prefilter_v4_seal import require_partition_authorized, validate_identity_manifest
from src.dante_light.preprocessing import PreparedPrefilterFeatures


ROLES=("background","robust_candidate","known_glitch","injection")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes((json.dumps(value,indent=2,sort_keys=True)+"\n").encode("utf-8"))


def _load_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_v4_partition(
    *, root: Path, split_path: Path, partition: str,
    seal: Mapping[str, Any] | None=None, unlock_receipt: Mapping[str, Any] | None=None,
) -> tuple[dict[str, Any],list[dict[str, Any]]]:
    """Load one authorized partition without exposing any other row."""

    require_partition_authorized(partition,seal=seal,unlock_receipt=unlock_receipt)
    header=json.loads(split_path.read_text(encoding="utf-8"))
    public_body=dict(header); declared_public=public_body.pop("manifest_digest",None)
    if declared_public!=canonical_json_sha256(public_body):
        raise ContractError("v4 public split header digest mismatch")
    entries_ref=header["entries_reference"]; entries_path=root/entries_ref["path"]
    if _sha(entries_path)!=entries_ref["sha256"]:
        raise ContractError("v4 split entries hash mismatch")
    rows=_load_rows(entries_path)
    complete={k:v for k,v in header.items() if k!="entries_reference"}; complete["rows"]=rows
    complete["manifest_digest"]=canonical_json_sha256({k:v for k,v in complete.items() if k!="manifest_digest"})
    validate_identity_manifest(complete)
    header=dict(header); header["identity_manifest_digest"]=complete["manifest_digest"]
    selected=[row for row in rows if row["partition"]==partition]
    if not selected or any(row["partition"]!=partition for row in selected):
        raise ContractError("v4 authorized partition is empty or contaminated")
    return header,selected


def load_injection_trials(path: Path) -> dict[str,dict[str,Any]]:
    trials={}
    for row in _load_rows(path):
        body=dict(row); declared=body.pop("trial_digest",None)
        if declared!=canonical_json_sha256(body) or row.get("outcome_fields_present")!=[]:
            raise ContractError("v4 injection trial digest/outcome boundary mismatch")
        source_id=str(row["source_id"])
        if source_id in trials: raise ContractError("duplicate v4 injection source identity")
        trials[source_id]=row
    if not trials: raise ContractError("v4 injection trial table is empty")
    return trials


def prepare_v4_injection_features(
    task: WindowTask,
    *,
    protocol: PrefilterProtocolV4,
    trials: Mapping[str,Mapping[str,Any]],
    local_only: bool = False,
) -> PreparedPrefilterFeatures:
    """Reconstruct one legacy-comparable injection; SNR is diagnostic only."""

    from src.core.data_loader import fetch_strain_data
    from src.core.injection import InjectionEngine
    from src.core.preprocessor import extract_clean_subwindow, whiten_context
    from src.pipeline_v2_production.astrophysical_injection import _project, _waveform

    source=task.payload; source_id=str(source["source"]["source_id"])
    trial=trials.get(source_id)
    if trial is None: raise ContractError(f"v4 injection trial missing: {source_id}")
    stratum=source["stratum"]
    if (
        trial["system"]!=stratum["system"]
        or float(trial["distance_mpc"])!=float(stratum["distance_mpc"])
        or int(trial["trial_index"])!=int(stratum["trial_index"])
        or float(trial["gps_start"])!=task.window.gps_start
    ):
        raise ContractError("v4 injection trial/manifest identity mismatch")
    contract=protocol.payload["injection_waveform_contract"]
    system=contract["systems"][str(trial["system"])]
    sample_rate=int(contract["sample_rate_hz"]); duration=float(contract["window_duration_s"])
    gps=task.window.gps_start; detector=task.window.detector
    began=time.perf_counter()
    hp,hc=_waveform(float(system["mass_1_msun"]),float(system["mass_2_msun"]),
        float(trial["distance_mpc"]),float(trial["inclination_rad"]),float(system["f_low_hz"]))
    if len(hp) / sample_rate > duration:
        raise ContractError("v4 legacy injection waveform exceeds the frozen analysis window")
    projected,delay=_project(hp,hc,detector,float(trial["ra_rad"]),float(trial["dec_rad"]),
        float(trial["psi_rad"]),gps+duration/2.0)
    waveform_s=time.perf_counter()-began
    began=time.perf_counter()
    try:
        pad=float(protocol.payload["feature_extraction"]["whitening_context_pad_s"])
        raw=fetch_strain_data(detector,gps-pad,gps+duration+pad,local_only=local_only,edge_tolerance=1.0/sample_rate)
    except (FileNotFoundError,OSError,RuntimeError) as exc:
        raise DeferredWindow(FailClosedReason.DEPENDENCY_UNAVAILABLE) from exc
    data_read_s=time.perf_counter()-began
    raw_values=np.asarray(raw.value)
    if int(round(float(raw.sample_rate.value))) != sample_rate:
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    if not np.all(np.isfinite(raw_values)): raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    engine=InjectionEngine(sample_rate=sample_rate)
    measured_snr=float(engine.compute_snr(raw.crop(gps,gps+duration),projected))
    placement=gps+duration/2.0+float(delay)-(len(projected)/sample_rate)/2.0
    injected=engine.inject(raw,projected,placement)
    injected_values=np.asarray(injected.value)
    began=time.perf_counter()
    whitened,padding=whiten_context(injected,gps,gps+duration,pad=pad)
    clean=extract_clean_subwindow(whitened,gps,gps+duration)
    whitening_s=time.perf_counter()-began
    tolerance=1.0/sample_rate
    if (
        float(padding.get("effective_left",0.0))+tolerance<pad
        or float(padding.get("effective_right",0.0))+tolerance<pad
        or abs(float(clean.duration.value)-duration)>tolerance
    ): raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    began=time.perf_counter()
    features=extract_prefilter_v4_features(np.asarray(clean.value),config=protocol.payload["feature_extraction"])
    feature_s=time.perf_counter()-began
    digest=lambda values:hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()
    return PreparedPrefilterFeatures(features=features,strain_sha256=digest(injected_values),timings={
        "waveform_projection_s":waveform_s,"data_read_s":data_read_s,"whitening_s":whitening_s,
        "feature_extraction_s":feature_s},metadata={
        "raw_strain_sha256":digest(raw_values),"waveform_plus_sha256":digest(hp),
        "waveform_cross_sha256":digest(hc),"projected_waveform_sha256":digest(projected),
        "measured_snr_diagnostic_only":measured_snr,"snr_used_for_selection_or_gate":False,
        "geocentre_delay_s":float(delay),"placement_gps":float(placement),
        "approximant":contract["approximant"],"tidal_effects_included":bool(system.get("tidal_effects_included",False))})


def build_development_ledger(
    *, root: Path, split_path: Path, protocol: PrefilterProtocolV4, role: str,
    output_dir: Path, prepare: Callable[[WindowTask],PreparedPrefilterFeatures],
    workers: int=1, limit: int|None=None,
) -> dict[str,Any]:
    if role not in ROLES: raise ContractError(f"unsupported v4 role: {role}")
    if not 1<=workers<=8: raise ContractError("v4 workers must be in [1,8]")
    header,all_development=load_v4_partition(root=root,split_path=split_path,partition="development")
    rows=[row for row in all_development if row["role"]==role]
    expected_full=len(rows)
    if limit is not None:
        if limit<=0: raise ContractError("v4 smoke limit must be positive")
        rows=rows[:limit]
    tasks=[WindowTask(WindowIdentity.from_dict(row["window"]),payload=row) for row in rows]
    if len({task.window.window_id for task in tasks})!=len(tasks): raise ContractError("duplicate v4 development window")
    output_dir.mkdir(parents=True,exist_ok=True)
    partial=output_dir/f"{role}_features_v4_development.partial.jsonl"
    partial_rows=_load_rows(partial) if partial.exists() else []
    existing={row["window"]["window_id"]:row for row in partial_rows}
    if len(existing)!=len(partial_rows): raise ContractError("duplicate row in v4 partial ledger")
    expected_ids={task.window.window_id for task in tasks}
    if not set(existing)<=expected_ids: raise ContractError("v4 partial ledger contains unauthorized rows")
    feature_contract_sha=canonical_json_sha256(protocol.payload["feature_extraction"])
    for window_id, row in existing.items():
        task = next(item for item in tasks if item.window.window_id == window_id)
        if (
            row.get("schema_version") != 4
            or row.get("partition") != "development"
            or row.get("roles") != [role]
            or row.get("manifest_digest") != header["identity_manifest_digest"]
            or row.get("feature_contract_sha256") != feature_contract_sha
            or row.get("window") != task.window.to_dict()
        ):
            raise ContractError("v4 partial ledger is stale or contract-incompatible")
    def one(task: WindowTask):
        prepared=prepare(task); source=task.payload
        return task.window.window_id,{"schema_version":4,"window":task.window.to_dict(),"roles":[role],
            "partition":"development","detector":task.window.detector,"morphology":source["morphology"],
            "retention_target":bool(source["retention_target"]),"cohort_id":source["cohort_id"],
            "source_id":source["source"]["source_id"],"manifest_digest":header["identity_manifest_digest"],
            "feature_contract_sha256":feature_contract_sha,"strain_sha256":prepared.strain_sha256,
            "features":asdict(prepared.features),"timings":prepared.timings,"preparation_metadata":prepared.metadata}
    pending=[task for task in tasks if task.window.window_id not in existing]
    with partial.open("a",encoding="utf-8",newline="\n") as stream:
        if workers==1:
            iterator=(one(task) for task in pending)
            for window_id,row in iterator:
                stream.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n"); stream.flush(); existing[window_id]=row
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures={pool.submit(one,task):task for task in pending}
                for future in as_completed(futures):
                    window_id,row=future.result()
                    if window_id in existing: raise ContractError("duplicate concurrent v4 feature row")
                    stream.write(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n"); stream.flush(); existing[window_id]=row
    if set(existing)!=expected_ids: raise ContractError("v4 development ledger incomplete")
    final_rows=[existing[task.window.window_id] for task in tasks]
    rows_path=output_dir/f"{role}_features_v4_development.jsonl"
    rows_path.write_bytes("".join(json.dumps(row,sort_keys=True,separators=(",",":"))+"\n" for row in final_rows).encode())
    partial.unlink()
    ledger={"schema_version":4,"status":"complete" if limit is None else "smoke_only",
        "scientific_mode":"v4_frozen_development_only_feature_extraction","role":role,
        "selection_partitions":["development"],"confirmation_rows_accessed":[],"o4b_rows_accessed":[],
        "outcome_fields_used_for_feature_extraction":[],"protocol":repository_reference(root,protocol.path),
        "source_split_header":repository_reference(root,split_path),"source_split_entries":header["entries_reference"],
        "public_split_header_digest":header["manifest_digest"],
        "manifest_digest":header["identity_manifest_digest"],"feature_contract_sha256":feature_contract_sha,
        "row_count":len(final_rows),"expected_full_row_count":expected_full,"rows_path":rows_path.name,
        "rows_sha256":_sha(rows_path),"selection_limit":limit,"extraction_workers":workers}
    ledger["ledger_digest"]=canonical_json_sha256(ledger)
    _write_json(output_dir/f"{role}_feature_ledger_v4_development.json",ledger)
    return ledger
