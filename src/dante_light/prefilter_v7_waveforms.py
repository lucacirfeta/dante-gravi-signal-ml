"""Outcome-blind waveform cache for v7 risk-calibration injections."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_injections import reconstruct_frozen_trial


ROOT = Path(__file__).resolve().parents[2]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


SCHEMA_VERSION = 1
DEFAULT_CACHE = Path("E:/dante_cache/dante_light/prefilter_l4_v7_risk_calibration")
DEFAULT_TRIALS = ROOT / "config/dante_light_prefilter_v7_injection_trials.jsonl"
DEFAULT_DESIGN = ROOT / "config/dante_light_prefilter_v7_outcome_blind_contract.json"
DEFAULT_SUMMARY = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_risk_calibration"
    / "risk_calibration_waveforms_v7.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.savez(stream, **arrays)
    temporary.replace(path)


def waveform_contract(*, root: Path = ROOT) -> dict[str, Any]:
    design_path = root / DEFAULT_DESIGN.relative_to(ROOT)
    trials_path = root / DEFAULT_TRIALS.relative_to(ROOT)
    design = _read_json(design_path)
    body = {
        "schema_version": SCHEMA_VERSION,
        "partition": "risk_calibration",
        "outcome_contract_digest": design["contract_digest"],
        "trials_sha256": file_sha256(trials_path),
        "reconstruction_code_sha256": file_sha256(
            root / "src/dante_light/prefilter_v5_injections.py"
        ),
        "cache_code_sha256": file_sha256(Path(__file__)),
        "outcomes_accessed": [],
        "confirmation_accessed": [],
        "o4b_accessed": [],
    }
    return {**body, "waveform_contract_digest": canonical_json_sha256(body)}


def waveform_run_key(contract: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "waveform_contract_digest": contract["waveform_contract_digest"],
            "stage": "risk_calibration",
            "schema_version": SCHEMA_VERSION,
        }
    )


def risk_calibration_trials(*, root: Path = ROOT) -> list[dict[str, Any]]:
    selected = []
    for line in (root / DEFAULT_TRIALS.relative_to(ROOT)).read_text(
        encoding="utf-8"
    ).splitlines():
        if not line.strip():
            continue
        trial = json.loads(line)
        if trial.get("v7_partition", trial.get("partition")) != "risk_calibration":
            continue
        body = dict(trial)
        if body.pop("trial_digest", None) != canonical_json_sha256(body):
            raise ContractError("v7 risk-calibration trial digest mismatch")
        selected.append(trial)
    selected.sort(key=lambda row: row["source_id"])
    if len(selected) != 720 or len({row["source_id"] for row in selected}) != 720:
        raise ContractError("v7 risk-calibration injection trials are incomplete")
    if any(row.get("outcome_fields_present") != [] for row in selected):
        raise ContractError("v7 risk-calibration waveform input exposes an outcome")
    return selected


def build_waveform_cache(
    *, root: Path = ROOT, cache_root: Path = DEFAULT_CACHE
) -> dict[str, Any]:
    contract = waveform_contract(root=root)
    run_key = waveform_run_key(contract)
    run_dir = cache_root.resolve() / f"waveforms_{run_key}"
    design = _read_json(root / DEFAULT_DESIGN.relative_to(ROOT))
    protocol = {"approved_design": {"waveforms": design["waveforms"]}}
    records = []
    for trial in risk_calibration_trials(root=root):
        source_id = str(trial["source_id"])
        stem = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
        array_path = run_dir / "arrays" / f"{stem}.npz"
        record_path = run_dir / "records" / f"{stem}.json"
        if record_path.is_file():
            record = _read_json(record_path)
            body = dict(record)
            if body.pop("record_digest", None) != canonical_json_sha256(body):
                raise ContractError("v7 waveform record digest mismatch")
            if record.get("run_key") != run_key or record.get("source_id") != source_id:
                raise ContractError("v7 waveform cache identity collision")
            if not array_path.is_file() or file_sha256(array_path) != record["array_sha256"]:
                raise ContractError("v7 waveform array changed")
            records.append(record)
            continue
        parameters, projected = reconstruct_frozen_trial(trial, protocol)
        detector_strain = np.ascontiguousarray(projected.detector_strain, dtype=np.float64)
        if detector_strain.size == 0 or not np.isfinite(detector_strain).all():
            raise ContractError("v7 waveform reconstruction is invalid")
        _atomic_npz(array_path, detector_strain=detector_strain)
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "RISK_CALIBRATION_WAVEFORM_COMPLETE_OUTCOME_BLIND",
            "run_key": run_key,
            "source_id": source_id,
            "trial_digest": trial["trial_digest"],
            "parameters": parameters.to_dict(),
            "projection": {
                "detector_delay_s": projected.detector_delay_s,
                "geocentric_merger_gps": projected.geocentric_merger_gps,
                "detector_merger_gps": projected.detector_merger_gps,
                "injection_array_center_gps": projected.injection_array_center_gps,
            },
            "array_path": array_path.relative_to(run_dir).as_posix(),
            "array_sha256": file_sha256(array_path),
            "array_samples": int(detector_strain.size),
            "outcomes_accessed": [],
            "confirmation_accessed": [],
            "o4b_accessed": [],
        }
        record = {**body, "record_digest": canonical_json_sha256(body)}
        _atomic_json(record_path, record)
        records.append(record)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "RISK_CALIBRATION_WAVEFORMS_COMPLETE_OUTCOME_BLIND",
        "run_key": run_key,
        "waveform_contract": contract,
        "row_count": len(records),
        "source_ids_digest": canonical_json_sha256([row["source_id"] for row in records]),
        "record_digests": [row["record_digest"] for row in records],
        "cache_location": {
            "environment_alias": "DANTE_V7_RISK_CALIBRATION_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
        },
        "outcomes_accessed": [],
        "confirmation_accessed": [],
        "o4b_accessed": [],
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "waveform_summary.json", summary)
    _atomic_json(root / DEFAULT_SUMMARY.relative_to(ROOT), summary)
    return summary


def verify_waveform_cache(
    *, root: Path = ROOT, cache_root: Path = DEFAULT_CACHE
) -> tuple[Path, dict[str, dict[str, Any]], dict[str, Any]]:
    summary = _read_json(root / DEFAULT_SUMMARY.relative_to(ROOT))
    body = dict(summary)
    if body.pop("artifact_digest", None) != canonical_json_sha256(body):
        raise ContractError("v7 waveform summary digest mismatch")
    contract = waveform_contract(root=root)
    if (
        summary.get("status") != "RISK_CALIBRATION_WAVEFORMS_COMPLETE_OUTCOME_BLIND"
        or summary.get("waveform_contract") != contract
        or summary.get("row_count") != 720
        or summary.get("outcomes_accessed") != []
        or summary.get("confirmation_accessed") != []
        or summary.get("o4b_accessed") != []
    ):
        raise ContractError("v7 waveform cache crossed the outcome boundary")
    run_dir = cache_root.resolve() / summary["cache_location"]["run_subdirectory"]
    cache_summary = _read_json(run_dir / "waveform_summary.json")
    if cache_summary != summary:
        raise ContractError("v7 repository/cache waveform summaries differ")
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((run_dir / "records").glob("*.json")):
        record = _read_json(path)
        record_body = dict(record)
        if record_body.pop("record_digest", None) != canonical_json_sha256(record_body):
            raise ContractError("v7 waveform cache record digest mismatch")
        array_path = (run_dir / record["array_path"]).resolve()
        if not array_path.is_relative_to(run_dir) or file_sha256(array_path) != record["array_sha256"]:
            raise ContractError("v7 waveform cache array mismatch")
        records[record["source_id"]] = record
    if (
        len(records) != 720
        or canonical_json_sha256(sorted(records)) != summary["source_ids_digest"]
        or [records[key]["record_digest"] for key in sorted(records)]
        != summary["record_digests"]
    ):
        raise ContractError("v7 waveform cache is incomplete")
    return run_dir, records, summary
