"""Fail-closed training-only freeze for the DANTE-Light v5 students."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_student import (
    ComplexSTFT2DStudentProxy,
    Raw1DDepthwiseStudentProxy,
    trainable_parameter_count,
)
from src.dante_light.prefilter_v5_protocol import (
    PROTOCOL_ID,
    ROOT,
    derive_seed,
    load_protocol,
    repository_reference,
    sha256_path,
)
from src.dante_light.prefilter_v5_teacher import (
    default_cache_root,
    load_teacher_contract,
    load_training_rows,
    verify_teacher_ledger_summary,
)


SCHEMA_VERSION = 1
DEFAULT_DESIGN = ROOT / "config/dante_light_prefilter_v5_training_design.json"
DEFAULT_PROTOCOL = ROOT / "config/dante_light_prefilter_protocol_v5.json"
DEFAULT_TEACHER_CONTRACT = ROOT / "config/dante_light_prefilter_v5_teacher_contract.json"
DEFAULT_TEACHER_SUMMARY = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/teacher_ledger_summary_v5.json"
)
DEFAULT_CONTRACT = ROOT / "config/dante_light_prefilter_v5_training_contract.json"
DEFAULT_INTERNAL_SPLIT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/training_internal_split_v5.jsonl"
)
DEFAULT_TARGETS = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/teacher_targets_compact_v5.jsonl"
)
_BLOCK_PATH = re.compile(r"^blocks/(H1|L1)_([0-9]+)\.json$")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return (
        "".join(
            json.dumps(
                dict(row),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
            for row in rows
        )
    ).encode("utf-8")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def _reference(root: Path, value: Mapping[str, Any], label: str) -> Path:
    if set(value) != {"path", "sha256"}:
        raise ContractError(f"v5 training reference is malformed: {label}")
    text = str(value["path"])
    if not text or Path(text).is_absolute() or "\\" in text:
        raise ContractError(f"v5 training reference is not portable: {label}")
    path = (root / text).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError(f"v5 training reference is absent: {label}")
    candidates = {sha256_path(path)}
    try:
        relative = path.relative_to(root.resolve()).as_posix()
        candidates.add(
            hashlib.sha256(
                subprocess.check_output(
                    ["git", "show", f"HEAD:{relative}"],
                    cwd=root,
                    stderr=subprocess.DEVNULL,
                )
            ).hexdigest()
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    if str(value["sha256"]) not in candidates:
        raise ContractError(f"v5 training reference hash mismatch: {label}")
    return path


def validate_training_design(value: Mapping[str, Any]) -> dict[str, Any]:
    design = dict(value)
    if (
        design.get("schema_version") != SCHEMA_VERSION
        or design.get("status") != "APPROVED_TRAINING_ONLY_FREEZE_INPUT"
        or design.get("design_id") != "dante-light-l4-prefilter-v5-training"
    ):
        raise ContractError("v5 training design identity changed")
    scope = design["scope"]
    if (
        scope["allowed_partition"] != "training"
        or scope["allowed_role"] != "background"
        or any(
            bool(scope[name])
            for name in (
                "development_access_allowed",
                "confirmation_access_allowed",
                "o4b_access_allowed",
                "morphology_labels_allowed",
                "routing_enabled",
            )
        )
    ):
        raise ContractError("v5 training design opened a protected outcome")
    split = design["internal_split"]
    if (
        split["unit"] != "detector_gps_4096s_block"
        or not math.isclose(
            float(split["fit_fraction"]) + float(split["validation_fraction"]),
            1.0,
        )
        or not 0.0 < float(split["fit_fraction"]) < 1.0
        or split["stratify_by"] != "detector"
        or bool(split["block_overlap_allowed"])
    ):
        raise ContractError("v5 training internal split is invalid")
    target = design["target"]
    if (
        target["name"] != "native_o4a_novelty_score"
        or target["serialization"] != "float32_hex"
        or target["standardization"]
        != "per_detector_population_mean_std_fit_subset_only"
        or int(target["standard_deviation_ddof"]) != 0
        or bool(target["clipping"])
        or bool(target["physical_truth_label"])
    ):
        raise ContractError("v5 training target semantics changed")
    optimization = design["optimization"]
    if (
        optimization["scheduler"]["name"] != "none"
        or not optimization["scheduler"]["intentional"]
        or optimization["loss"]["name"] != "SmoothL1Loss"
        or int(optimization["maximum_epochs"]) <= 0
        or bool(optimization["early_stopping"])
        or bool(optimization["gradient_clipping"])
        or optimization["precision"]["model_and_inputs"] != "float32"
        or bool(optimization["precision"]["automatic_mixed_precision"])
    ):
        raise ContractError("v5 training optimization semantics changed")
    batch = optimization["batch"]
    if (
        int(batch["total_size"])
        != int(batch["H1_size"]) + int(batch["L1_size"])
        or int(batch["H1_size"]) != int(batch["L1_size"])
        or not batch["detector_balanced"]
    ):
        raise ContractError("v5 training batches are not detector-balanced")
    failure = design["numerical_failure"]
    if (
        failure["nonfinite_input_activation_prediction_loss_gradient_or_parameter"]
        != "FAILED"
        or not failure["failed_replicate_blocks_candidate_promotion"]
        or failure["infrastructure_interruption"]
        != "INCOMPLETE_RERUN_SAME_SEED_ALLOWED"
    ):
        raise ContractError("v5 training numerical failure is not fail-closed")
    return design


def _block_keys_from_summary(summary: Mapping[str, Any]) -> list[tuple[str, int]]:
    keys = []
    for reference in summary["block_references"]:
        match = _BLOCK_PATH.fullmatch(str(reference["path"]))
        if match is None:
            raise ContractError("v5 training teacher block path is malformed")
        keys.append((match.group(1), int(match.group(2))))
    if len(keys) != len(set(keys)) or len(keys) != int(summary["block_count"]):
        raise ContractError("v5 training teacher blocks are duplicated or incomplete")
    return sorted(keys)


def assign_training_blocks(
    block_keys: Sequence[tuple[str, int]],
    *,
    fit_fraction: float,
    seed_purpose: str,
    parent_digests: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Create the deterministic detector-stratified fit/validation assignment."""

    assignments: list[dict[str, Any]] = []
    seeds: dict[str, int] = {}
    for detector in ("H1", "L1"):
        blocks = sorted(index for current, index in block_keys if current == detector)
        if not blocks:
            raise ContractError(f"v5 training has no {detector} blocks")
        fit_count_float = len(blocks) * float(fit_fraction)
        fit_count = int(round(fit_count_float))
        if not math.isclose(fit_count_float, float(fit_count)):
            raise ContractError("v5 training fit fraction does not yield an integer block count")
        seed = derive_seed(
            PROTOCOL_ID,
            f"{seed_purpose}_{detector}",
            parent_digests,
        )
        seeds[detector] = seed
        permutation = np.random.default_rng(seed).permutation(len(blocks))
        fit = {blocks[int(position)] for position in permutation[:fit_count]}
        for block_index in blocks:
            assignments.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "detector": detector,
                    "block_index": block_index,
                    "subset": "fit" if block_index in fit else "validation",
                }
            )
    assignments.sort(key=lambda row: (row["detector"], row["block_index"]))
    return assignments, seeds


def _float32_from_hex(value: str) -> np.float32:
    try:
        raw = bytes.fromhex(str(value))
    except ValueError as exc:
        raise ContractError("v5 teacher target is not hexadecimal") from exc
    if len(raw) != np.dtype(np.float32).itemsize:
        raise ContractError("v5 teacher target is not one float32")
    result = np.frombuffer(raw, dtype=np.float32)[0]
    if not np.isfinite(result):
        raise ContractError("v5 teacher target is non-finite")
    return result


def extract_compact_targets(
    *,
    summary: Mapping[str, Any],
    run_dir: Path,
    assignments: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    subset_by_key = {
        (str(row["detector"]), int(row["block_index"])): str(row["subset"])
        for row in assignments
    }
    targets = []
    for reference in summary["block_references"]:
        relative = str(reference["path"])
        block_path = (run_dir / relative).resolve()
        if not block_path.is_relative_to(run_dir.resolve()):
            raise ContractError("v5 training teacher block escaped its cache root")
        if sha256_path(block_path) != str(reference["sha256"]):
            raise ContractError("v5 training teacher block hash mismatch")
        block = _load_json(block_path)
        key = (str(block["detector"]), int(block["block_index"]))
        subset = subset_by_key.get(key)
        if subset is None:
            raise ContractError("v5 training teacher block has no internal assignment")
        for row in block["rows"]:
            score_hex = str(row["teacher_target"]["float32_hex"])
            _float32_from_hex(score_hex)
            targets.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "window_id": row["window"]["window_id"],
                    "detector": row["window"]["detector"],
                    "gps_start": row["window"]["gps_start"],
                    "block_index": key[1],
                    "subset": subset,
                    "teacher_target_float32_hex": score_hex,
                    "raw_strain_sha256": row["raw_strain_sha256"],
                    "clean_strain_sha256": row["clean_strain_sha256"],
                    "image_sha256": row["image_sha256"],
                    "strain_shard_path": (
                        Path(relative).parent / block["strain_shard"]["path"]
                    ).as_posix(),
                    "strain_shard_sha256": block["strain_shard"]["sha256"],
                }
            )
    return targets


def target_standardization(
    targets: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, float | int]]:
    result: dict[str, dict[str, float | int]] = {}
    for detector in ("H1", "L1"):
        values = np.asarray(
            [
                _float32_from_hex(str(row["teacher_target_float32_hex"]))
                for row in targets
                if row["detector"] == detector and row["subset"] == "fit"
            ],
            dtype=np.float64,
        )
        if values.size == 0 or not np.isfinite(values).all():
            raise ContractError(f"v5 training {detector} fit targets are absent or non-finite")
        mean = float(np.mean(values, dtype=np.float64))
        standard_deviation = float(np.std(values, ddof=0, dtype=np.float64))
        if not math.isfinite(standard_deviation) or standard_deviation <= 0.0:
            raise ContractError(f"v5 training {detector} target scale is degenerate")
        result[detector] = {
            "fit_count": int(values.size),
            "mean_float64": mean,
            "standard_deviation_float64_ddof0": standard_deviation,
        }
    return result


def _artifact_reference(root: Path, path: Path) -> dict[str, str]:
    relative = path.resolve().relative_to(root.resolve()).as_posix()
    return {"path": relative, "sha256": sha256_path(path)}


def build_training_freeze(
    *,
    root: Path = ROOT,
    cache_root: Path | None = None,
    write_artifacts: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    design_path = root / DEFAULT_DESIGN.relative_to(ROOT)
    protocol_path = root / DEFAULT_PROTOCOL.relative_to(ROOT)
    teacher_contract_path = root / DEFAULT_TEACHER_CONTRACT.relative_to(ROOT)
    teacher_summary_path = root / DEFAULT_TEACHER_SUMMARY.relative_to(ROOT)
    internal_split_path = root / DEFAULT_INTERNAL_SPLIT.relative_to(ROOT)
    targets_path = root / DEFAULT_TARGETS.relative_to(ROOT)
    design = validate_training_design(_load_json(design_path))
    protocol = load_protocol(protocol_path, root=root)
    teacher_contract = load_teacher_contract(teacher_contract_path, root=root)
    summary = _load_json(teacher_summary_path)
    selected_cache_root = (cache_root or default_cache_root()).resolve()
    verified = verify_teacher_ledger_summary(
        summary,
        root=root,
        contract=teacher_contract,
        cache_root=selected_cache_root,
        require_complete=True,
    )
    if verified["status"] != "PASS_COMPLETE":
        raise ContractError("v5 training requires a complete teacher ledger")
    parents = [
        protocol["protocol_digest"],
        teacher_contract["teacher_contract_digest"],
        summary["artifact_digest"],
        sha256_path(design_path),
    ]
    assignments, seeds = assign_training_blocks(
        _block_keys_from_summary(summary),
        fit_fraction=float(design["internal_split"]["fit_fraction"]),
        seed_purpose=str(design["internal_split"]["seed_purpose"]),
        parent_digests=parents,
    )
    run_dir = selected_cache_root / summary["cache_location"]["run_subdirectory"]
    targets = extract_compact_targets(
        summary=summary,
        run_dir=run_dir,
        assignments=assignments,
    )
    if len(targets) != int(summary["row_count"]):
        raise ContractError("v5 training compact targets are incomplete")
    if write_artifacts:
        _atomic_bytes(internal_split_path, _jsonl_bytes(assignments))
        _atomic_bytes(targets_path, _jsonl_bytes(targets))
    else:
        if not internal_split_path.is_file() or not targets_path.is_file():
            raise ContractError("v5 training compact artifacts are absent")
    counts = {
        detector: {
            subset: sum(
                1
                for row in assignments
                if row["detector"] == detector and row["subset"] == subset
            )
            for subset in ("fit", "validation")
        }
        for detector in ("H1", "L1")
    }
    row_counts = {
        detector: {
            subset: sum(
                1
                for row in targets
                if row["detector"] == detector and row["subset"] == subset
            )
            for subset in ("fit", "validation")
        }
        for detector in ("H1", "L1")
    }
    model_counts = {
        "raw_1d_depthwise": trainable_parameter_count(Raw1DDepthwiseStudentProxy()),
        "complex_stft_2d": trainable_parameter_count(ComplexSTFT2DStudentProxy()),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_TRAINING_ONLY_BEFORE_STUDENT_FIT",
        "design": design,
        "source_references": {
            "design": repository_reference(root, design_path),
            "protocol": repository_reference(root, protocol_path),
            "teacher_contract": repository_reference(root, teacher_contract_path),
            "teacher_ledger_summary": repository_reference(root, teacher_summary_path),
            "student_architectures": repository_reference(
                root, root / "src/dante_light/prefilter_v4_student.py"
            ),
            "freeze_implementation": repository_reference(
                root, root / "src/dante_light/prefilter_v5_training_contract.py"
            ),
            "freeze_builder": repository_reference(
                root, root / "scripts/freeze_dante_light_prefilter_v5_training.py"
            ),
            "freeze_verifier": repository_reference(
                root, root / "scripts/verify_dante_light_prefilter_v5_training_freeze.py"
            ),
        },
        "parent_digests": {
            "protocol_digest": protocol["protocol_digest"],
            "teacher_contract_digest": teacher_contract["teacher_contract_digest"],
            "teacher_ledger_artifact_digest": summary["artifact_digest"],
            "teacher_run_key": summary["run_key"],
        },
        "internal_split": {
            "assignment_reference": _artifact_reference(root, internal_split_path),
            "assignment_digest": canonical_json_sha256(assignments),
            "seed_parent_digests": sorted(parents),
            "seeds_by_detector": seeds,
            "block_counts": counts,
            "row_counts": row_counts,
        },
        "compact_teacher_targets": {
            "reference": _artifact_reference(root, targets_path),
            "row_count": len(targets),
            "rows_digest": canonical_json_sha256(targets),
        },
        "target_standardization": target_standardization(targets),
        "student_architectures": {
            "raw_1d_depthwise_trainable_parameters": model_counts["raw_1d_depthwise"],
            "complex_stft_2d_trainable_parameters": model_counts["complex_stft_2d"],
        },
        "training_replicate_seeds": protocol["training_replicate_seeds"],
        "student_training_executed": False,
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
    contract = {**body, "training_contract_digest": canonical_json_sha256(body)}
    return contract, assignments, targets


def validate_training_freeze(
    contract: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    payload = dict(contract)
    declared = payload.pop("training_contract_digest", None)
    if declared != canonical_json_sha256(payload):
        raise ContractError("v5 training contract self-digest mismatch")
    payload["training_contract_digest"] = declared
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("status") != "FROZEN_TRAINING_ONLY_BEFORE_STUDENT_FIT"
    ):
        raise ContractError("v5 training contract is not frozen before fit")
    if payload["student_training_executed"] is not False or any(
        payload[field]
        for field in (
            "development_rows_accessed",
            "confirmation_rows_accessed",
            "o4b_rows_accessed",
        )
    ):
        raise ContractError("v5 training freeze crossed its outcome boundary")
    references = {
        label: _reference(root, reference, label)
        for label, reference in payload["source_references"].items()
    }
    design = validate_training_design(_load_json(references["design"]))
    if payload["design"] != design:
        raise ContractError("v5 training embedded design changed")
    protocol = load_protocol(references["protocol"], root=root)
    teacher_contract = load_teacher_contract(references["teacher_contract"], root=root)
    summary = _load_json(references["teacher_ledger_summary"])
    parents = [
        protocol["protocol_digest"],
        teacher_contract["teacher_contract_digest"],
        summary["artifact_digest"],
        sha256_path(references["design"]),
    ]
    expected_assignments, expected_seeds = assign_training_blocks(
        _block_keys_from_summary(summary),
        fit_fraction=float(design["internal_split"]["fit_fraction"]),
        seed_purpose=str(design["internal_split"]["seed_purpose"]),
        parent_digests=parents,
    )
    assignment_path = _reference(
        root, payload["internal_split"]["assignment_reference"], "assignments"
    )
    assignments = _load_jsonl(assignment_path)
    if (
        assignments != expected_assignments
        or payload["internal_split"]["assignment_digest"]
        != canonical_json_sha256(assignments)
        or payload["internal_split"]["seeds_by_detector"] != expected_seeds
    ):
        raise ContractError("v5 training internal split does not reproduce")
    expected_block_counts = {
        detector: {
            subset: sum(
                1
                for row in assignments
                if row["detector"] == detector and row["subset"] == subset
            )
            for subset in ("fit", "validation")
        }
        for detector in ("H1", "L1")
    }
    if payload["internal_split"]["block_counts"] != expected_block_counts:
        raise ContractError("v5 training internal block counts changed")
    targets_path = _reference(
        root, payload["compact_teacher_targets"]["reference"], "compact targets"
    )
    targets = _load_jsonl(targets_path)
    _header, training_rows = load_training_rows(root=root)
    expected_ids = [row["window"]["window_id"] for row in training_rows]
    target_ids = [row["window_id"] for row in targets]
    if (
        target_ids != expected_ids
        or len(target_ids) != len(set(target_ids))
        or payload["compact_teacher_targets"]["row_count"] != len(targets)
        or payload["compact_teacher_targets"]["rows_digest"]
        != canonical_json_sha256(targets)
        or payload["target_standardization"] != target_standardization(targets)
    ):
        raise ContractError("v5 training compact targets do not reproduce")
    expected_row_counts = {
        detector: {
            subset: sum(
                1
                for row in targets
                if row["detector"] == detector and row["subset"] == subset
            )
            for subset in ("fit", "validation")
        }
        for detector in ("H1", "L1")
    }
    if payload["internal_split"]["row_counts"] != expected_row_counts:
        raise ContractError("v5 training internal row counts changed")
    expected_model_counts = {
        "raw_1d_depthwise_trainable_parameters": trainable_parameter_count(
            Raw1DDepthwiseStudentProxy()
        ),
        "complex_stft_2d_trainable_parameters": trainable_parameter_count(
            ComplexSTFT2DStudentProxy()
        ),
    }
    if payload["student_architectures"] != expected_model_counts:
        raise ContractError("v5 training student architecture changed")
    if payload["training_replicate_seeds"] != protocol["training_replicate_seeds"]:
        raise ContractError("v5 training replicate seeds changed")
    return payload


def load_training_freeze(
    path: str | Path = DEFAULT_CONTRACT,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    return validate_training_freeze(_load_json(Path(path)), root=root)


def verify_training_freeze_against_cache(
    contract: Mapping[str, Any],
    *,
    root: Path = ROOT,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    checked = validate_training_freeze(contract, root=root)
    summary = _load_json(root / checked["source_references"]["teacher_ledger_summary"]["path"])
    selected_cache_root = (cache_root or default_cache_root()).resolve()
    run_dir = selected_cache_root / summary["cache_location"]["run_subdirectory"]
    assignments = _load_jsonl(
        root / checked["internal_split"]["assignment_reference"]["path"]
    )
    observed = extract_compact_targets(
        summary=summary,
        run_dir=run_dir,
        assignments=assignments,
    )
    expected = _load_jsonl(
        root / checked["compact_teacher_targets"]["reference"]["path"]
    )
    if observed != expected:
        raise ContractError("v5 training compact targets mismatch the teacher cache")
    return {
        "status": "PASS_TRAINING_FREEZE",
        "training_contract_digest": checked["training_contract_digest"],
        "block_count": len(assignments),
        "row_count": len(expected),
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
