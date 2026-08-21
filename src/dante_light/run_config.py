"""Fail-closed preflight for a locked DANTE-Light manifest and causal epochs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from src.core.index_contract import sha256_file
from src.dante_light.contracts import (
    CalibrationEpochContract,
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.runner import load_epochs


def _inside(root: Path, raw: str | Path) -> Path:
    candidate = Path(raw)
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if path != root and root not in path.parents:
        raise ContractError(f"run configuration path escapes repository root: {raw}")
    return path


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"{label} must be a JSON object")
    return payload


def _verify_bound_json(
    root: Path,
    record: Any,
    *,
    label: str,
    digest_field: str,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ContractError(f"shadow manifest {label} binding is missing")
    source = _inside(root, record.get("path", ""))
    if not source.is_file() or sha256_file(source) != record.get("sha256"):
        raise ContractError(f"shadow manifest {label} file hash mismatch")
    payload = _read_object(source, label)
    body = dict(payload)
    digest = body.pop(digest_field, None)
    if digest != record.get(digest_field) or digest != canonical_json_sha256(body):
        raise ContractError(f"shadow manifest {label} self-hash mismatch")
    return payload


def verify_run_configuration(
    *,
    manifest_path: str | Path,
    epochs_path: str | Path,
    root: str | Path = ".",
    reference_manifest_path: str | Path = "config/reference_artifacts.json",
    epoch_loader: Callable[..., tuple[dict[str, Any], dict[str, CalibrationEpochContract]]] = load_epochs,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    manifest_source = _inside(root_path, manifest_path)
    epochs_source = _inside(root_path, epochs_path)
    reference_source = _inside(root_path, reference_manifest_path)
    manifest = _read_object(manifest_source, "shadow manifest")
    body = dict(manifest)
    digest = body.pop("manifest_sha256", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("shadow manifest self-hash mismatch")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "locked_before_scoring":
        raise ContractError("shadow manifest is not locked schema 1")
    if manifest.get("outcome_fields_used_for_selection") != []:
        raise ContractError("shadow manifest selection is outcome-dependent")
    representation = RepresentationContract.from_reference_manifest(reference_source)
    if manifest.get("representation") != representation.to_dict():
        raise ContractError("shadow manifest representation differs from reference contract")
    reference_record = manifest.get("reference_contract")
    if reference_record is not None:
        if reference_record != {
            "path": reference_source.relative_to(root_path).as_posix(),
            "sha256": sha256_file(reference_source),
        }:
            raise ContractError("shadow manifest reference-contract binding mismatch")
    plan = None
    if "selection_plan" in manifest:
        plan = _verify_bound_json(
            root_path,
            manifest["selection_plan"],
            label="selection plan",
            digest_field="plan_sha256",
        )
        if plan.get("status") != "locked_before_dq_fetch":
            raise ContractError("shadow selection plan is not locked before DQ fetch")
        if plan.get("outcome_fields_used_for_selection") != []:
            raise ContractError("shadow selection plan contains outcome fields")
    snapshot = _verify_bound_json(
        root_path,
        manifest.get("dq_snapshot"),
        label="DQ snapshot",
        digest_field="snapshot_sha256",
    )
    if snapshot.get("status") != "frozen_dq_only":
        raise ContractError("shadow DQ snapshot is not frozen")
    if snapshot.get("source", {}).get("outcome_data_accessed") is not False:
        raise ContractError("shadow DQ snapshot is not outcome-blind")
    if snapshot.get("run") != manifest.get("run") or snapshot.get(
        "official_run_bounds_gps"
    ) != manifest.get("official_run_bounds_gps"):
        raise ContractError("shadow DQ snapshot run contract differs from manifest")
    if plan is not None and snapshot.get("selection_plan_sha256") != plan.get(
        "plan_sha256"
    ):
        raise ContractError("shadow DQ snapshot belongs to a different selection plan")
    selection_contract = manifest.get("selection_contract", {})
    selected_detectors = selection_contract.get("detectors", [])
    snapshot_flags = snapshot.get("source", {}).get("flags", {})
    if [snapshot_flags.get(detector) for detector in selected_detectors] != selection_contract.get(
        "dq_flags"
    ):
        raise ContractError("shadow DQ flag contract differs from manifest")

    entries_source = _inside(root_path, manifest.get("entries_path", ""))
    if not entries_source.is_file() or sha256_file(entries_source) != manifest.get("entries_file_sha256"):
        raise ContractError("shadow entry-file SHA256 mismatch")
    entries = [
        json.loads(line)
        for line in entries_source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if canonical_json_sha256(entries) != manifest.get("entries_sha256"):
        raise ContractError("shadow entries canonical digest mismatch")
    if not entries or any(row.get("expected") != {} for row in entries):
        raise ContractError("shadow entries are empty or contain inspected outcomes")
    for row in entries:
        body = dict(row)
        case_id = str(body.pop("case_id", ""))
        if case_id != f"dlc1-{canonical_json_sha256(body)[:24]}":
            raise ContractError("shadow entry case id does not reproduce")
        if row.get("source_kind") != "public_strain":
            raise ContractError("shadow entry source kind is not public strain")
        if not isinstance(row.get("roles"), list) or not row["roles"]:
            raise ContractError("shadow entry roles are missing")
        metadata = row.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("whitening_context_cat1") is not True:
            raise ContractError("shadow entry lacks padded-CAT1 selection evidence")
    windows = [WindowIdentity.from_dict(row["window"]) for row in entries]
    window_ids = {window.window_id for window in windows}
    counts = manifest.get("counts", {})
    if counts.get("entries") != len(entries) or counts.get("unique_windows") != len(window_ids):
        raise ContractError("shadow manifest entry accounting mismatch")
    if len(window_ids) != len(entries):
        raise ContractError("shadow manifest contains duplicate detector/GPS windows")
    run = str(manifest.get("run", ""))
    if {window.run for window in windows} != {run}:
        raise ContractError("shadow entries do not share the manifest run")
    detectors = {window.detector for window in windows}
    selection_detectors = set(selected_detectors)
    if detectors != selection_detectors:
        raise ContractError("shadow detector coverage differs from selection contract")
    reproduced_blocks: dict[str, dict[str, int]] = {}
    for row in entries:
        block_index = int(row["metadata"].get("block_index", 0))
        if block_index <= 0:
            raise ContractError("shadow entry block index is invalid")
        block = f"block_{block_index}"
        detector = row["window"]["detector"]
        reproduced_blocks.setdefault(block, {})[detector] = (
            reproduced_blocks.setdefault(block, {}).get(detector, 0) + 1
        )
    if reproduced_blocks != counts.get("by_block_and_detector"):
        raise ContractError("shadow block/detector accounting mismatch")

    epoch_payload, epochs = epoch_loader(
        epochs_source, representation=representation, root=root_path
    )
    if set(epochs) != detectors:
        raise ContractError("causal epoch detector coverage differs from shadow manifest")
    detector_rows: dict[str, dict[str, Any]] = {}
    for detector in sorted(detectors):
        epoch = epochs[detector]
        selected = [window for window in windows if window.detector == detector]
        evaluation_start = min(window.gps_start for window in selected)
        evaluation_end = max(window.gps_start + window.duration_s for window in selected)
        if not epoch.causal:
            raise ContractError(f"{detector} epoch is not causal")
        if epoch.run != run or epoch.detector != detector:
            raise ContractError(f"{detector} epoch run/detector contract mismatch")
        if epoch.cutoff_gps >= evaluation_start:
            raise ContractError(f"{detector} epoch cutoff is not before evaluation")
        detector_rows[detector] = {
            "epoch_id": epoch.epoch_id,
            "cutoff_gps": epoch.cutoff_gps,
            "evaluation_start_gps": evaluation_start,
            "evaluation_end_gps": evaluation_end,
            "windows": len(selected),
        }
    return {
        "schema_version": 1,
        "status": "PASS",
        "run": run,
        "manifest_path": manifest_source.relative_to(root_path).as_posix(),
        "manifest_sha256": sha256_file(manifest_source),
        "entries_path": entries_source.relative_to(root_path).as_posix(),
        "entries_sha256": sha256_file(entries_source),
        "epochs_path": epochs_source.relative_to(root_path).as_posix(),
        "epochs_sha256": sha256_file(epochs_source),
        "epoch_status": epoch_payload.get("status"),
        "windows": len(windows),
        "detectors": detector_rows,
        "representation_sha256": representation.contract_sha256,
    }
