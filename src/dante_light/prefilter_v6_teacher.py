"""Native-O4a teacher ledger restricted to frozen DANTE-Light v6 Phase B."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path
from src.dante_light.prefilter_v5_teacher import (
    PreparedTeacherInput,
    TARGET_NAME,
    TARGET_SCORE_KEY,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "dante_light_prefilter_v6_teacher_contract.json"


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def phase_b_windows(*, root: Path = ROOT) -> list[dict[str, Any]]:
    blocks = _jsonl(root / "config/dante_light_prefilter_v6_partitions.jsonl")
    rows: list[dict[str, Any]] = []
    for block in blocks:
        if block["partition"] != "phase_b":
            continue
        starts = [float(value) for value in block["selected_window_starts"]]
        if len(starts) != 8:
            raise ContractError("v6 teacher Phase-B block does not contain eight windows")
        for index, start in enumerate(starts):
            window = WindowIdentity(
                run="O4A",
                detector=str(block["detector"]),
                gps_start=start,
                duration_s=32.0,
            )
            rows.append(
                {
                    "detector": block["detector"],
                    "block_index": int(block["block_index"]),
                    "subset": block["subset"],
                    "span_stratum": int(block["span_stratum"]),
                    "window_index": index,
                    "window": window.to_dict(),
                }
            )
    rows.sort(key=lambda row: (row["detector"], row["block_index"], row["window_index"]))
    if len(rows) != 2880 or len({row["window"]["window_id"] for row in rows}) != len(rows):
        raise ContractError("v6 teacher Phase-B identity count or uniqueness changed")
    return rows


def build_teacher_contract(*, root: Path = ROOT, raw_cache_summary_path: Path) -> dict[str, Any]:
    raw_summary = json.loads(raw_cache_summary_path.read_text(encoding="utf-8"))
    if raw_summary.get("status") != "COMPLETE":
        raise ContractError("v6 teacher freeze requires a complete Phase-B raw cache")
    for field in ("phase_c_rows_accessed", "phase_d_rows_accessed", "o4b_rows_accessed", "teacher_scores_accessed"):
        if raw_summary.get(field) != []:
            raise ContractError(f"v6 raw cache crossed boundary before teacher freeze: {field}")
    rows = phase_b_windows(root=root)
    representation = RepresentationContract.from_reference_manifest(root / "config/reference_artifacts.json")
    sources = {
        "phase_b_contract": repository_reference(root, root / "config/dante_light_prefilter_v6_phase_b_freeze.json"),
        "partition_header": repository_reference(root, root / "config/dante_light_prefilter_v6_partitions.json"),
        "partition_entries": repository_reference(root, root / "config/dante_light_prefilter_v6_partitions.jsonl"),
        "raw_cache_summary": repository_reference(root, raw_cache_summary_path),
        "reference_manifest": repository_reference(root, root / "config/reference_artifacts.json"),
        "v5_teacher_contract": repository_reference(root, root / "config/dante_light_prefilter_v5_teacher_contract.json"),
    }
    body = {
        "schema_version": 1,
        "status": "FROZEN_PHASE_B_TEACHER_ONLY",
        "teacher_id": "dante-light-l4-prefilter-v6-phase-b-native-teacher",
        "source_references": sources,
        "representation": representation.to_dict(),
        "teacher": {
            "target_name": TARGET_NAME,
            "decision_score_key": TARGET_SCORE_KEY,
            "target_index_artifact_id": "o4a_native_q4_64_k1216",
            "target_index_sha256": representation.native_index_sha256,
            "encoder_index_artifact_id": "o3b_production_k275",
            "encoder_index_sha256": representation.primary_index_sha256,
            "engine": "shared_encoder_score_only",
            "output_mode": "score_only",
            "threshold_applied": False,
            "physical_truth_label": False,
            "standardization_deferred_to_training_fit_subset": True,
        },
        "identity_count": len(rows),
        "block_count": len({(row["detector"], row["block_index"]) for row in rows}),
        "identity_digest": canonical_json_sha256([row["window"]["window_id"] for row in rows]),
        "access_boundary": {
            "allowed_partition": "phase_b",
            "allowed_role": "background",
            "phase_c_rows_allowed": False,
            "phase_d_rows_allowed": False,
            "o4b_rows_allowed": False,
            "morphology_labels_allowed": False,
        },
        "cache": {
            "environment_alias": "DANTE_V6_TRAINING_CACHE_ROOT",
            "default_location": "E:/dante_cache/dante_light/prefilter_l4_v6_training",
            "canonical_whitened_float32_cached": True,
            "incompatible_run_reuse_allowed": False,
        },
        "outcome_access_at_freeze": {
            "teacher_scores": [],
            "student_outputs": [],
            "phase_c": [],
            "phase_d": [],
            "o4b": [],
            "morphology_labels": [],
        },
    }
    return {**body, "teacher_contract_digest": canonical_json_sha256(body)}


def load_teacher_contract(path: Path = DEFAULT_CONTRACT, *, root: Path = ROOT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("teacher_contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 teacher contract digest mismatch")
    if payload.get("status") != "FROZEN_PHASE_B_TEACHER_ONLY":
        raise ContractError("v6 teacher contract is not frozen")
    for name, reference in payload["source_references"].items():
        source = root / reference["path"]
        if not source.is_file() or sha256_path(source) != reference["sha256"]:
            raise ContractError(f"v6 teacher source mismatch: {name}")
    rows = phase_b_windows(root=root)
    if payload["identity_count"] != len(rows) or payload["identity_digest"] != canonical_json_sha256(
        [row["window"]["window_id"] for row in rows]
    ):
        raise ContractError("v6 teacher identities changed")
    boundary = payload["access_boundary"]
    if boundary["allowed_partition"] != "phase_b" or any(
        boundary[key]
        for key in (
            "phase_c_rows_allowed",
            "phase_d_rows_allowed",
            "o4b_rows_allowed",
            "morphology_labels_allowed",
        )
    ):
        raise ContractError("v6 teacher access boundary widened")
    representation = RepresentationContract.from_reference_manifest(
        root / payload["source_references"]["reference_manifest"]["path"]
    )
    if payload["representation"] != representation.to_dict():
        raise ContractError("v6 teacher representation changed")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.savez(stream, **arrays)
    os.replace(temporary, path)


def teacher_run_key(contract: Mapping[str, Any], code_references: Mapping[str, Mapping[str, str]]) -> str:
    return canonical_json_sha256(
        {
            "teacher_contract_digest": contract["teacher_contract_digest"],
            "code_references": code_references,
        }
    )


def _validate_cached_block(
    path: Path,
    *,
    run_key: str,
    expected_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("block_digest", None)
    if declared != canonical_json_sha256(body) or payload.get("status") != "COMPLETE":
        raise ContractError(f"v6 teacher block is stale: {path.name}")
    if payload["run_key"] != run_key:
        raise ContractError(f"v6 teacher block run key changed: {path.name}")
    expected_ids = [row["window"]["window_id"] for row in expected_rows]
    if [row["window"]["window_id"] for row in payload["rows"]] != expected_ids:
        raise ContractError(f"v6 teacher block identities changed: {path.name}")
    shard = path.parent / payload["strain_shard"]["path"]
    if not shard.is_file() or sha256_path(shard) != payload["strain_shard"]["sha256"]:
        raise ContractError(f"v6 teacher clean-strain shard changed: {path.name}")
    return payload


def build_teacher_ledger(
    *,
    root: Path,
    contract: Mapping[str, Any],
    cache_root: Path,
    artifact_path: Path,
    code_references: Mapping[str, Mapping[str, str]],
    prepare: Callable[[WindowIdentity], PreparedTeacherInput],
    score: Callable[[Sequence[np.ndarray]], tuple[list[float], dict[str, float]]],
    workers: int,
    limit_blocks: int | None = None,
) -> dict[str, Any]:
    checked = load_teacher_contract(root=root)
    if checked != contract:
        raise ContractError("v6 teacher caller contract differs from frozen contract")
    if workers < 1 or workers > 16:
        raise ContractError("v6 teacher worker count is outside [1,16]")
    for name, reference in code_references.items():
        source = root / reference["path"]
        if not source.is_file() or sha256_path(source) != reference["sha256"]:
            raise ContractError(f"v6 teacher code reference mismatch: {name}")
    run_key = teacher_run_key(checked, code_references)
    run_dir = cache_root / f"teacher_{run_key}"
    block_dir = run_dir / "blocks"
    block_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in phase_b_windows(root=root):
        grouped.setdefault((row["detector"], row["block_index"]), []).append(row)
    groups = sorted(grouped.items())
    expected_blocks = len(groups)
    if limit_blocks is not None:
        if limit_blocks < 1:
            raise ContractError("v6 teacher smoke limit must be positive")
        groups = groups[:limit_blocks]
    payloads = []
    for (detector, block_index), block_rows in groups:
        block_rows.sort(key=lambda row: row["window_index"])
        block_path = block_dir / f"{detector}_{block_index}.json"
        if block_path.is_file():
            payloads.append(_validate_cached_block(block_path, run_key=run_key, expected_rows=block_rows))
            continue
        prepared_by_id: dict[str, PreparedTeacherInput] = {}
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(prepare, WindowIdentity.from_dict(row["window"])): row
                for row in block_rows
            }
            for future in as_completed(futures):
                row = futures[future]
                try:
                    prepared_by_id[row["window"]["window_id"]] = future.result()
                except Exception as exc:
                    failures.append({
                        "window_id": row["window"]["window_id"],
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    })
        if failures:
            _atomic_json(run_dir / "failure.json", {
                "status": "NOT_READY_INCOMPLETE_TEACHER_INPUT",
                "run_key": run_key,
                "detector": detector,
                "block_index": block_index,
                "failures": failures,
                "phase_c_rows_accessed": [],
                "phase_d_rows_accessed": [],
                "o4b_rows_accessed": [],
            })
            raise ContractError(f"v6 teacher preparation failed in {detector}:{block_index}")
        prepared = [prepared_by_id[row["window"]["window_id"]] for row in block_rows]
        scores, score_timings = score([item.image for item in prepared])
        if len(scores) != 8 or not np.isfinite(scores).all():
            raise ContractError("v6 teacher scorer returned invalid scores")
        strain = np.stack([item.clean_strain for item in prepared]).astype(np.float32, copy=False)
        window_ids = np.asarray([row["window"]["window_id"] for row in block_rows], dtype="U32")
        shard_path = block_dir / f"{detector}_{block_index}_clean_strain.npz"
        _atomic_npz(shard_path, clean_strain=strain, window_ids=window_ids)
        result_rows = []
        for row, item, native_score in zip(block_rows, prepared, scores, strict=True):
            result_rows.append({
                "window": row["window"],
                "subset": row["subset"],
                "span_stratum": row["span_stratum"],
                "window_index": row["window_index"],
                "raw_strain_sha256": item.raw_strain_sha256,
                "clean_strain_sha256": item.clean_strain_sha256,
                "image_sha256": item.image_sha256,
                "teacher_target": {
                    "name": TARGET_NAME,
                    "score_key": TARGET_SCORE_KEY,
                    TARGET_NAME: float(native_score),
                    "float32_hex": np.float32(native_score).tobytes().hex(),
                },
                "preparation_timings_s": item.timings,
            })
        block_body = {
            "schema_version": 1,
            "status": "COMPLETE",
            "run_key": run_key,
            "detector": detector,
            "block_index": block_index,
            "teacher_contract_digest": checked["teacher_contract_digest"],
            "strain_shard": {
                "path": shard_path.name,
                "sha256": sha256_path(shard_path),
                "dtype": "float32",
                "shape": list(strain.shape),
            },
            "score_timings_s": score_timings,
            "rows": result_rows,
            "phase_c_rows_accessed": [],
            "phase_d_rows_accessed": [],
            "o4b_rows_accessed": [],
        }
        payload = {**block_body, "block_digest": canonical_json_sha256(block_body)}
        _atomic_json(block_path, payload)
        payloads.append(payload)
    values: dict[str, list[float]] = {"H1": [], "L1": []}
    references = []
    for payload in payloads:
        values[payload["detector"]].extend(
            float(row["teacher_target"][TARGET_NAME]) for row in payload["rows"]
        )
        path = block_dir / f"{payload['detector']}_{payload['block_index']}.json"
        references.append({"path": path.relative_to(run_dir).as_posix(), "sha256": sha256_path(path)})
    smoke = limit_blocks is not None
    body = {
        "schema_version": 1,
        "status": "SMOKE_ONLY" if smoke else "COMPLETE",
        "run_key": run_key,
        "teacher_contract_digest": checked["teacher_contract_digest"],
        "identity_digest": checked["identity_digest"],
        "row_count": sum(len(payload["rows"]) for payload in payloads),
        "expected_full_row_count": checked["identity_count"],
        "block_count": len(payloads),
        "expected_full_block_count": expected_blocks,
        "score_descriptives_training_only": {
            detector: {
                "n": len(current),
                "mean": float(np.mean(current)) if current else None,
                "std_population": float(np.std(current, ddof=0)) if current else None,
                "minimum": float(np.min(current)) if current else None,
                "maximum": float(np.max(current)) if current else None,
            }
            for detector, current in values.items()
        },
        "block_references": references,
        "code_references": dict(code_references),
        "cache_location": {
            "environment_alias": "DANTE_V6_TRAINING_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
        },
        "student_training_executed": False,
        "phase_c_rows_accessed": [],
        "phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
        "morphology_labels_accessed": [],
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "teacher_ledger_summary_v6.json", summary)
    _atomic_json(artifact_path, summary)
    return summary


def verify_teacher_ledger_summary(
    summary: Mapping[str, Any],
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    cache_root: Path,
    require_complete: bool = True,
) -> dict[str, Any]:
    """Validate the compact v6 ledger against every immutable cached block."""

    contract = load_teacher_contract(contract_path, root=root)
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 teacher ledger artifact digest mismatch")
    expected_status = "COMPLETE" if require_complete else summary.get("status")
    if expected_status not in {"COMPLETE", "SMOKE_ONLY"} or summary.get("status") != expected_status:
        raise ContractError("v6 teacher ledger completion status is invalid")
    if summary.get("teacher_contract_digest") != contract["teacher_contract_digest"]:
        raise ContractError("v6 teacher ledger contract digest mismatch")
    for field in (
        "phase_c_rows_accessed",
        "phase_d_rows_accessed",
        "o4b_rows_accessed",
        "morphology_labels_accessed",
    ):
        if summary.get(field) != []:
            raise ContractError(f"v6 teacher ledger crossed protected boundary: {field}")
    if summary.get("student_training_executed") is not False:
        raise ContractError("v6 teacher ledger incorrectly reports student training")
    code_references = summary.get("code_references", {})
    if not code_references:
        raise ContractError("v6 teacher ledger has no code provenance")
    for name, reference in code_references.items():
        source = root / reference["path"]
        if not source.is_file() or sha256_path(source) != reference["sha256"]:
            raise ContractError(f"v6 teacher ledger code mismatch: {name}")
    expected_run_key = teacher_run_key(contract, code_references)
    if summary.get("run_key") != expected_run_key:
        raise ContractError("v6 teacher ledger run key mismatch")
    run_dir = cache_root / summary["cache_location"]["run_subdirectory"]
    references = summary.get("block_references", [])
    if len(references) != int(summary.get("block_count", -1)):
        raise ContractError("v6 teacher block-reference count mismatch")
    frozen_rows = phase_b_windows(root=root)
    by_block: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in frozen_rows:
        by_block.setdefault((row["detector"], row["block_index"]), []).append(row)
    seen_ids: list[str] = []
    score_values: dict[str, list[float]] = {"H1": [], "L1": []}
    seen_blocks: set[tuple[str, int]] = set()
    for reference in references:
        path = run_dir / reference["path"]
        if not path.is_file() or sha256_path(path) != reference["sha256"]:
            raise ContractError("v6 teacher block reference changed")
        payload = json.loads(path.read_text(encoding="utf-8"))
        key = (str(payload["detector"]), int(payload["block_index"]))
        if key in seen_blocks or key not in by_block:
            raise ContractError("v6 teacher block identity is duplicated or unknown")
        seen_blocks.add(key)
        checked = _validate_cached_block(
            path,
            run_key=expected_run_key,
            expected_rows=sorted(by_block[key], key=lambda row: row["window_index"]),
        )
        for row in checked["rows"]:
            value = float(row["teacher_target"][TARGET_NAME])
            if not np.isfinite(value):
                raise ContractError("v6 teacher ledger contains a non-finite target")
            if np.float32(value).tobytes().hex() != row["teacher_target"]["float32_hex"]:
                raise ContractError("v6 teacher target float32 provenance mismatch")
            seen_ids.append(row["window"]["window_id"])
            score_values[key[0]].append(value)
    if len(seen_ids) != len(set(seen_ids)) or len(seen_ids) != int(summary.get("row_count", -1)):
        raise ContractError("v6 teacher ledger row identity count mismatch")
    if require_complete:
        expected_ids = [row["window"]["window_id"] for row in frozen_rows]
        if set(seen_ids) != set(expected_ids):
            raise ContractError("v6 teacher complete ledger does not cover Phase B exactly")
        if summary.get("row_count") != contract["identity_count"]:
            raise ContractError("v6 teacher complete row count changed")
        if summary.get("block_count") != contract["block_count"]:
            raise ContractError("v6 teacher complete block count changed")
    for detector, values in score_values.items():
        recorded = summary["score_descriptives_training_only"][detector]
        observed = {
            "n": len(values),
            "mean": float(np.mean(values)) if values else None,
            "std_population": float(np.std(values, ddof=0)) if values else None,
            "minimum": float(np.min(values)) if values else None,
            "maximum": float(np.max(values)) if values else None,
        }
        if recorded != observed:
            raise ContractError(f"v6 teacher score descriptives changed for {detector}")
    return {
        "status": "PASS_COMPLETE" if require_complete else "PASS_SMOKE_ONLY",
        "run_key": expected_run_key,
        "row_count": len(seen_ids),
        "block_count": len(seen_blocks),
        "teacher_contract_digest": contract["teacher_contract_digest"],
        "phase_c_rows_accessed": [],
        "phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
