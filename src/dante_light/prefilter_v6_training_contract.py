"""Fail-closed Phase-B training-input freeze for DANTE-Light v6."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path
from src.dante_light.prefilter_v6_phase_b import derive_seed, load_phase_b_contract
from src.dante_light.prefilter_v6_teacher import (
    DEFAULT_CONTRACT as DEFAULT_TEACHER_CONTRACT,
    TARGET_NAME,
    load_teacher_contract,
    verify_teacher_ledger_summary,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TEACHER_SUMMARY = ROOT / "artifacts/dante_light/prefilter_l4_v6_training/teacher_ledger_summary_v6.json"
DEFAULT_TARGETS = ROOT / "artifacts/dante_light/prefilter_l4_v6_training/teacher_targets_compact_v6.jsonl"
DEFAULT_CONTRACT = ROOT / "config/dante_light_prefilter_v6_training_contract.json"


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


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def build_training_freeze(
    *,
    root: Path = ROOT,
    teacher_summary_path: Path = DEFAULT_TEACHER_SUMMARY,
    teacher_cache_root: Path,
    targets_path: Path = DEFAULT_TARGETS,
    write_targets: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    phase_b = load_phase_b_contract(root=root)
    teacher = load_teacher_contract(DEFAULT_TEACHER_CONTRACT, root=root)
    summary = json.loads(teacher_summary_path.read_text(encoding="utf-8"))
    verify_teacher_ledger_summary(
        summary,
        root=root,
        cache_root=teacher_cache_root,
        require_complete=True,
    )
    if summary["teacher_contract_digest"] != teacher["teacher_contract_digest"]:
        raise ContractError("v6 training teacher contract mismatch")
    run_dir = teacher_cache_root / summary["cache_location"]["run_subdirectory"]
    compact: list[dict[str, Any]] = []
    for reference in summary["block_references"]:
        block_path = run_dir / reference["path"]
        if sha256_path(block_path) != reference["sha256"]:
            raise ContractError("v6 training teacher block changed")
        block = json.loads(block_path.read_text(encoding="utf-8"))
        shard = block["strain_shard"]
        for row in block["rows"]:
            compact.append(
                {
                    "schema_version": 1,
                    "detector": block["detector"],
                    "block_index": int(block["block_index"]),
                    "subset": row["subset"],
                    "span_stratum": int(row["span_stratum"]),
                    "window_index": int(row["window_index"]),
                    "window_id": row["window"]["window_id"],
                    "gps_start": float(row["window"]["gps_start"]),
                    "teacher_target_float32_hex": row["teacher_target"]["float32_hex"],
                    "strain_shard_path": f"blocks/{shard['path']}",
                    "strain_shard_sha256": shard["sha256"],
                }
            )
    compact.sort(key=lambda row: (row["detector"], row["block_index"], row["window_index"]))
    if len(compact) != 2880 or len({row["window_id"] for row in compact}) != len(compact):
        raise ContractError("v6 compact training target population changed")
    counts: dict[str, dict[str, int]] = {}
    standardization: dict[str, dict[str, float | int]] = {}
    for detector in ("H1", "L1"):
        fit = [row for row in compact if row["detector"] == detector and row["subset"] == "fit"]
        validation = [
            row
            for row in compact
            if row["detector"] == detector and row["subset"] == "internal_validation"
        ]
        if len(fit) != 1152 or len(validation) != 288:
            raise ContractError("v6 training fit/internal-validation count changed")
        values = np.asarray(
            [np.frombuffer(bytes.fromhex(row["teacher_target_float32_hex"]), dtype=np.float32)[0] for row in fit],
            dtype=np.float64,
        )
        mean = float(np.mean(values))
        std = float(np.std(values, ddof=0))
        if not np.isfinite(values).all() or not np.isfinite(mean) or not np.isfinite(std) or std <= 0:
            raise ContractError("v6 training target standardization is degenerate")
        counts[detector] = {"fit": len(fit), "internal_validation": len(validation)}
        standardization[detector] = {
            "fit_window_count": len(fit),
            "mean_float64": mean,
            "standard_deviation_float64_ddof0": std,
        }
    target_bytes = _jsonl_bytes(compact)
    if write_targets:
        _atomic_bytes(targets_path, target_bytes)
    body = {
        "schema_version": 1,
        "status": "FROZEN_PHASE_B_TRAINING_INPUT",
        "training_id": "dante-light-l4-prefilter-v6-phase-b-training",
        "phase_b_contract_digest": phase_b["contract_digest"],
        "teacher_contract_digest": teacher["teacher_contract_digest"],
        "teacher_ledger_digest": summary["artifact_digest"],
        "source_references": {
            "phase_b_contract": repository_reference(root, root / "config/dante_light_prefilter_v6_phase_b_freeze.json"),
            "phase_a_contract": repository_reference(root, root / "config/dante_light_prefilter_v6_phase_a.json"),
            "partitions": repository_reference(root, root / "config/dante_light_prefilter_v6_partitions.jsonl"),
            "teacher_contract": repository_reference(root, DEFAULT_TEACHER_CONTRACT),
            "teacher_ledger_summary": repository_reference(root, teacher_summary_path),
            "teacher_targets_compact": {
                "path": targets_path.resolve().relative_to(root.resolve()).as_posix(),
                "sha256": __import__("hashlib").sha256(target_bytes).hexdigest(),
            },
        },
        "population": {
            "allowed_partition": "phase_b",
            "allowed_role": "background",
            "row_count": len(compact),
            "block_count": 360,
            "counts": counts,
            "independence_unit": "detector_gps_4096s_block",
        },
        "target": {
            "name": TARGET_NAME,
            "serialization": "float32_hex",
            "standardization": "per_detector_fit_subset_mean_std_ddof0",
            "clipping": False,
            "physical_truth_label": False,
        },
        "target_standardization": standardization,
        "arms": phase_b["arms"],
        "optimization": phase_b["optimization"],
        "objective": phase_b["objective"],
        "replicate_seeds": [
            derive_seed(phase_b["contract_digest"], "phase_b_training_replicate", index)
            for index in range(int(phase_b["replicates"]["count"]))
        ],
        "selection_rule": phase_b["selection_rule"],
        "access_boundary": {
            "phase_c": [],
            "phase_d": [],
            "o4b": [],
            "morphology_labels": [],
        },
    }
    return {**body, "training_contract_digest": canonical_json_sha256(body)}, compact


def load_training_freeze(path: Path = DEFAULT_CONTRACT, *, root: Path = ROOT) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("training_contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 training contract digest mismatch")
    if payload.get("status") != "FROZEN_PHASE_B_TRAINING_INPUT":
        raise ContractError("v6 training contract is not frozen")
    for name, reference in payload["source_references"].items():
        source = root / reference["path"]
        if (
            not source.is_file()
            or repository_reference(root, source)["sha256"] != reference["sha256"]
        ):
            raise ContractError(f"v6 training source mismatch: {name}")
    phase_b = load_phase_b_contract(root=root)
    if payload["phase_b_contract_digest"] != phase_b["contract_digest"]:
        raise ContractError("v6 training Phase-B contract changed")
    if (
        payload["arms"] != phase_b["arms"]
        or payload["optimization"] != phase_b["optimization"]
        or payload["objective"] != phase_b["objective"]
    ):
        raise ContractError("v6 training matrix or optimization changed")
    if any(payload["access_boundary"].values()):
        raise ContractError("v6 training contract crossed a protected boundary")
    return payload
