"""Outcome-blind waveform cache for the frozen v5 development injections.

This module deliberately has no Torch dependency so the cache can be built in
the WSL LALSuite environment before any development strain or score is read.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_development_contract import (
    DEFAULT_OUTPUT as DEFAULT_CONTRACT,
    load_development_contract,
)
from src.dante_light.prefilter_v5_injections import (
    load_frozen_trials,
    reconstruct_frozen_trial,
)
from src.dante_light.prefilter_v5_protocol import ROOT, sha256_path


SCHEMA_VERSION = 1


def default_development_cache_root() -> Path:
    configured = os.environ.get("DANTE_V5_DEVELOPMENT_CACHE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path("E:/dante_cache/dante_light/prefilter_l4_v5_development").resolve()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v5 waveform JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"v5 waveform JSON is not a mapping: {path}")
    return value


def waveform_run_key(
    contract: Mapping[str, Any], *, partition: str = "development"
) -> str:
    return canonical_json_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "partition": partition,
            "development_contract_digest": contract["development_contract_digest"],
            "injection_trials": contract["source_references"]["injection_trials"],
            "injection_reconstruction": contract["code_references"][
                "injection_reconstruction"
            ],
            "waveform_cache_code": contract["code_references"][
                "development_waveforms"
            ],
        }
    )


def build_injection_waveform_cache(
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    contract = load_development_contract(contract_path, root=root)
    protocol = _load_json(root / contract["source_references"]["protocol"]["path"])
    trials_path = root / contract["source_references"]["injection_trials"]["path"]
    trials = load_frozen_trials(trials_path)
    selected = [trial for trial in trials.values() if trial["partition"] == "development"]
    selected.sort(key=lambda row: row["source_id"])
    if not selected:
        raise ContractError("v5 development injection waveform set is empty")
    run_key = waveform_run_key(contract)
    run_dir = (cache_root or default_development_cache_root()) / f"waveforms_{run_key}"
    rows = []
    for trial in selected:
        source_id = str(trial["source_id"])
        identity = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
        data_path = run_dir / "arrays" / f"{identity}.npz"
        row_path = run_dir / "records" / f"{identity}.json"
        if row_path.is_file():
            row = _load_json(row_path)
            body = dict(row)
            if body.pop("record_digest", None) != canonical_json_sha256(body):
                raise ContractError("v5 waveform cache record digest mismatch")
            if row.get("run_key") != run_key or row.get("source_id") != source_id:
                raise ContractError("v5 waveform cache identity collision")
            if not data_path.is_file() or sha256_path(data_path) != row["array_sha256"]:
                raise ContractError("v5 waveform cache array mismatch")
            rows.append(row)
            continue
        parameters, projected = reconstruct_frozen_trial(trial, protocol)
        detector_strain = np.ascontiguousarray(projected.detector_strain, dtype=np.float64)
        if detector_strain.size == 0 or not np.isfinite(detector_strain).all():
            raise ContractError("v5 projected waveform is invalid")
        _atomic_npz(data_path, detector_strain=detector_strain)
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "WAVEFORM_COMPLETE_OUTCOME_BLIND",
            "run_key": run_key,
            "partition": "development",
            "source_id": source_id,
            "trial_digest": trial["trial_digest"],
            "parameters": parameters.to_dict(),
            "projection": {
                "detector_delay_s": projected.detector_delay_s,
                "geocentric_merger_gps": projected.geocentric_merger_gps,
                "detector_merger_gps": projected.detector_merger_gps,
                "injection_array_center_gps": projected.injection_array_center_gps,
            },
            "array_path": data_path.relative_to(run_dir).as_posix(),
            "array_sha256": sha256_path(data_path),
            "array_samples": int(detector_strain.size),
            "development_strain_accessed": False,
            "teacher_scores_accessed": False,
            "student_outputs_accessed": False,
            "confirmation_accessed": False,
            "o4b_accessed": False,
        }
        row = {**body, "record_digest": canonical_json_sha256(body)}
        _atomic_json(row_path, row)
        rows.append(row)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_OUTCOME_BLIND_DEVELOPMENT_WAVEFORMS",
        "run_key": run_key,
        "development_contract_digest": contract["development_contract_digest"],
        "row_count": len(rows),
        "source_ids_digest": canonical_json_sha256([row["source_id"] for row in rows]),
        "record_digests": [row["record_digest"] for row in rows],
        "cache_location": {
            "environment_alias": "DANTE_V5_DEVELOPMENT_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
        },
        "development_strain_accessed": False,
        "teacher_scores_accessed": False,
        "student_outputs_accessed": False,
        "confirmation_accessed": False,
        "o4b_accessed": False,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "waveform_summary.json", summary)
    return summary


def validate_waveform_cache(
    contract: Mapping[str, Any], *, cache_root: Path
) -> tuple[Path, dict[str, dict[str, Any]]]:
    run_key = waveform_run_key(contract)
    run_dir = (cache_root / f"waveforms_{run_key}").resolve()
    summary = _load_json(run_dir / "waveform_summary.json")
    body = dict(summary)
    if body.pop("artifact_digest", None) != canonical_json_sha256(body):
        raise ContractError("v5 waveform summary digest mismatch")
    if summary.get("status") != "COMPLETE_OUTCOME_BLIND_DEVELOPMENT_WAVEFORMS":
        raise ContractError("v5 development waveform cache is incomplete")
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((run_dir / "records").glob("*.json")):
        row = _load_json(path)
        row_body = dict(row)
        if row_body.pop("record_digest", None) != canonical_json_sha256(row_body):
            raise ContractError("v5 waveform record digest mismatch")
        data_path = (run_dir / row["array_path"]).resolve()
        if not data_path.is_relative_to(run_dir) or sha256_path(data_path) != row["array_sha256"]:
            raise ContractError("v5 waveform array hash mismatch")
        records[row["source_id"]] = row
    if len(records) != int(summary["row_count"]):
        raise ContractError("v5 waveform cache row count mismatch")
    return run_dir, records
