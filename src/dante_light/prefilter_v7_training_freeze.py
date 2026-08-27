"""Outcome-blind training freeze and deployable ensemble graph for v7.

This module may inspect frozen identities and configuration metadata only.  It
must not read strain, teacher outputs, morphology outcomes, threshold-search,
risk-calibration, confirmation, or O4b values.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping, Sequence

import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_student import trainable_parameter_count
from src.dante_light.prefilter_v6_phase_a import (
    Raw1DTeacherAlignedStudent,
    aggregation_contract,
)
from src.dante_light.prefilter_v7_freeze import verify_freeze


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
MEMBER_COUNT = 5
DETECTORS = ("H1", "L1")
SAMPLING_ROLES = ("background", "teacher_positive")
DEFAULT_CONTRACT = ROOT / "config/dante_light_prefilter_v7_training_contract.json"
DEFAULT_SPLIT = ROOT / "config/dante_light_prefilter_v7_training_split.jsonl"
PROPOSAL = (
    ROOT
    / "docs/DANTE_LIGHT_L4_PREFILTER_V7_TRAINING_FREEZE_PROPOSAL_2026-08-26.md"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def repository_reference(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    relative = resolved.relative_to(root.resolve()).as_posix()
    return {"path": relative, "sha256": file_sha256(resolved)}


def _resolve_reference(root: Path, value: Mapping[str, Any], label: str) -> Path:
    if set(value) != {"path", "sha256"}:
        raise ContractError(f"v7 training reference is malformed: {label}")
    relative = Path(str(value["path"]))
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(value["path"]):
        raise ContractError(f"v7 training reference is not portable: {label}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError(f"v7 training reference is absent: {label}")
    candidates = {file_sha256(path)}
    try:
        candidates.add(
            hashlib.sha256(
                subprocess.check_output(
                    ["git", "show", f"HEAD:{value['path']}"],
                    cwd=root,
                    stderr=subprocess.DEVNULL,
                )
            ).hexdigest()
        )
    except (OSError, subprocess.SubprocessError):
        pass
    if str(value["sha256"]) not in candidates:
        raise ContractError(f"v7 training reference hash mismatch: {label}")
    return path


def derive_seed(parent_digests: Sequence[str], purpose: str) -> int:
    digest = canonical_json_sha256(
        {"protocol": "dante-light-l4-prefilter-v7", "purpose": purpose,
         "parent_digests": sorted(str(value) for value in parent_digests)}
    )
    return int(digest[:16], 16) & ((1 << 63) - 1)


def _priority(seed: int, row: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "seed": int(seed),
            "detector": row["detector"],
            "role": row["role"],
            "block_key": row["block_key"],
            "identity_id": row["identity_id"],
        }
    )


def assign_internal_split(
    rows: Sequence[Mapping[str, Any]], *, parent_digests: Sequence[str]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    training = [row for row in rows if row["partition"] == "training"]
    assignments: list[dict[str, Any]] = []
    seeds: dict[str, int] = {}
    for detector in DETECTORS:
        for role in SAMPLING_ROLES:
            cell = [
                row
                for row in training
                if row["detector"] == detector and row["role"] == role
            ]
            if len(cell) != 150:
                raise ContractError(f"v7 training cell count changed: {detector}/{role}")
            block_keys = [str(row["block_key"]) for row in cell]
            if len(block_keys) != len(set(block_keys)):
                raise ContractError(f"v7 training cell repeats a block: {detector}/{role}")
            purpose = f"internal_split_{detector}_{role}"
            seed = derive_seed(parent_digests, purpose)
            seeds[f"{detector}/{role}"] = seed
            ordered = sorted(cell, key=lambda row: (_priority(seed, row), row["identity_id"]))
            validation_ids = {row["identity_id"] for row in ordered[:30]}
            for row in cell:
                assignments.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "identity_id": row["identity_id"],
                        "window_id": row["window"]["window_id"],
                        "detector": detector,
                        "sampling_role": role,
                        "block_key": row["block_key"],
                        "subset": (
                            "internal_validation"
                            if row["identity_id"] in validation_ids
                            else "fit"
                        ),
                    }
                )
    assignments.sort(key=lambda row: (row["detector"], row["sampling_role"], row["identity_id"]))
    if len(assignments) != 600 or len({row["identity_id"] for row in assignments}) != 600:
        raise ContractError("v7 internal split is incomplete or duplicated")
    if len({row["block_key"] for row in assignments}) != 600:
        raise ContractError("v7 internal split violates block independence")
    return assignments, seeds


def _aggregation(root: Path):
    phase_path = root / "config/dante_light_prefilter_v6_phase_a.json"
    phase = _read_json(phase_path)
    body = dict(phase)
    declared = body.pop("contract_digest", None)
    if (
        phase.get("status") != "FROZEN_OUTCOME_BLIND_COMPUTE_FEASIBILITY"
        or declared != canonical_json_sha256(body)
    ):
        raise ContractError("v6 Phase-A aggregation parent is not frozen")
    teacher_ref = phase["parent_references"]["teacher_contract"]
    teacher_path = _resolve_reference(root, teacher_ref, "v6_phase_a/teacher_contract")
    teacher = _read_json(teacher_path)
    return aggregation_contract(phase, teacher)


class V7SelectiveDeferralEnsemble(torch.nn.Module):
    """Five-member deployable candidate; every forward executes every member."""

    def __init__(self, aggregation: Any, member_seeds: Sequence[int]) -> None:
        super().__init__()
        if len(member_seeds) != MEMBER_COUNT or len(set(member_seeds)) != MEMBER_COUNT:
            raise ContractError("v7 requires five unique frozen member seeds")
        members = []
        for seed in member_seeds:
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(int(seed))
                members.append(Raw1DTeacherAlignedStudent(aggregation))
        self.members = torch.nn.ModuleList(members)

    def member_logits(self, values: torch.Tensor) -> torch.Tensor:
        return torch.cat([member(values) for member in self.members], dim=-1)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(self.member_logits(values)).mean(dim=-1, keepdim=True)


def build_ensemble(root: Path, member_seeds: Sequence[int]) -> V7SelectiveDeferralEnsemble:
    return V7SelectiveDeferralEnsemble(_aggregation(root), member_seeds)


def _counts(assignments: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    observed = Counter(
        (row["detector"], row["sampling_role"], row["subset"])
        for row in assignments
    )
    return {
        detector: {
            f"{role}/{subset}": observed[(detector, role, subset)]
            for role in SAMPLING_ROLES
            for subset in ("fit", "internal_validation")
        }
        for detector in DETECTORS
    }


def build_training_freeze(
    root: Path = ROOT, *, freeze_basis_commit: str, write_artifacts: bool
) -> dict[str, Any]:
    frozen = verify_freeze(root)
    design_path = root / "config/dante_light_prefilter_v7_outcome_blind_contract.json"
    identities_path = root / "config/dante_light_prefilter_v7_identities.jsonl"
    header_path = root / "config/dante_light_prefilter_v7_identities.json"
    audit_source_path = root / "config/dante_light_prefilter_v5_development_design.json"
    design = _read_json(design_path)
    header = _read_json(header_path)
    audit_source = _read_json(audit_source_path)
    if design["task"]["student_score"] != "estimated_probability_of_defer_label":
        raise ContractError("v7 semantic amendment no longer matches its frozen parent")
    audit_fraction = float(audit_source["audit_stream"]["fraction"])
    if not math.isclose(audit_fraction, 0.05, rel_tol=0.0, abs_tol=0.0):
        raise ContractError("versioned audit fraction changed")
    parent_digests = [
        frozen["contract_digest"],
        file_sha256(identities_path),
        header["manifest_digest"],
        file_sha256(PROPOSAL),
        file_sha256(root / "src/dante_light/prefilter_v6_phase_a.py"),
    ]
    assignments, split_seeds = assign_internal_split(
        _read_jsonl(identities_path), parent_digests=parent_digests
    )
    split_path = root / DEFAULT_SPLIT.relative_to(ROOT)
    if write_artifacts:
        _write_jsonl(split_path, assignments)
    elif not split_path.is_file():
        raise ContractError("v7 training split artifact is absent")
    if _read_jsonl(split_path) != assignments:
        raise ContractError("v7 training split differs from deterministic rebuild")
    member_seeds = [
        derive_seed(parent_digests, f"ensemble_member_{index}")
        for index in range(MEMBER_COUNT)
    ]
    ensemble = build_ensemble(root, member_seeds)
    per_member_parameters = trainable_parameter_count(ensemble.members[0])
    total_parameters = trainable_parameter_count(ensemble)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_BEFORE_TRAINING",
        "training_id": "dante-light-l4-prefilter-v7-selective-deferral-training",
        "freeze_basis_commit": freeze_basis_commit,
        "semantic_amendment": {
            "parent_field": "task.student_score",
            "parent_value": design["task"]["student_score"],
            "replacement_name": "defer_score",
            "range": [0.0, 1.0],
            "interpretation": "bounded_uncalibrated_ranking_score_not_population_probability",
            "reason": "case_control_sampling_does_not_identify_natural_population_posterior",
            "probability_calibration_allowed": False,
            "identity_or_gate_change": False,
        },
        "candidate": {
            "id": "raw_teacher_top_fraction_five_member_mean_sigmoid",
            "architecture": "V7SelectiveDeferralEnsemble",
            "member_architecture": "Raw1DTeacherAlignedStudent",
            "member_count": MEMBER_COUNT,
            "member_seeds": member_seeds,
            "all_members_execute_per_window": True,
            "member_selection_allowed": False,
            "second_stage_distillation_allowed": False,
            "ensemble_operator": "arithmetic_mean_of_member_sigmoid_outputs",
            "teacher_top_k": int(ensemble.members[0].pool.contract.teacher_top_k),
            "teacher_instance_count": int(
                ensemble.members[0].pool.contract.teacher_instance_count
            ),
            "student_instance_count": 256,
            "student_top_k": int(
                ensemble.members[0].pool.contract.student_top_k(256)
            ),
            "trainable_parameters_per_member": per_member_parameters,
            "trainable_parameters_total": total_parameters,
            "detector_as_model_input": False,
            "detector_specific_thresholds_downstream": True,
            "failed_member_action": "FAILED_NUMERICAL_NO_REPLACEMENT",
        },
        "labels": {
            "name": "historical_exact_DANTE_defer_label",
            "rule": "native_exact_DANTE_score_strictly_greater_than_historical_detector_threshold",
            "background_is_sampling_role_not_assumed_negative": True,
            "physical_truth_label": False,
            "morphology_labels_in_loss": False,
        },
        "internal_split": {
            "unit": "detector_gps_4096s_block",
            "stratify_by": ["detector", "sampling_role"],
            "fit_fraction": 0.8,
            "internal_validation_fraction": 0.2,
            "assignment_reference": repository_reference(root, split_path),
            "assignment_digest": canonical_json_sha256(assignments),
            "seeds_by_cell": split_seeds,
            "counts": _counts(assignments),
            "teacher_labels_used_for_assignment": False,
        },
        "optimization": {
            "loss": {"name": "BCEWithLogitsLoss", "weighting": "none", "reduction": "mean"},
            "batch": {
                "size": 64,
                "full_batch_per_detector_sampling_role": 16,
                "without_replacement": True,
                "final_partial_batch_retained": True,
                "synthetic_oversampling": False,
            },
            "optimizer": {
                "name": "AdamW",
                "learning_rate": 0.001,
                "weight_decay": 0.0001,
                "betas": [0.9, 0.999],
                "epsilon": 1e-8,
            },
            "scheduler": "none_intentional",
            "gradient_clipping": False,
            "automatic_mixed_precision": False,
            "dtype": "float32",
            "maximum_epochs": 100,
            "checkpoint": "minimum_equal_detector_internal_validation_BCE_then_earliest_epoch",
            "augmentation": "none_beyond_canonical_whitening_and_clean_crop",
        },
        "audit": {
            "nominal_fraction": audit_fraction,
            "selection": audit_source["audit_stream"]["selection"],
            "finite_cohort_realized_fraction_must_be_reported": True,
            "safety_gates_use_pre_audit_predictions": True,
            "operational_gate_uses_realized_post_audit_exact_calls": True,
            "final_seed_frozen_only_with_threshold_contract": True,
        },
        "benchmark": {
            "device": "cpu",
            "batch_size": 1,
            "torch_num_threads": 1,
            "warmup_repetitions": 50,
            "timed_repetitions": 300,
            "deterministic_algorithms": True,
            "input": "deterministic_standard_normal_float32_whitened_subwindow_proxy",
            "timing_boundary": [
                "numpy_float32_to_tensor_view",
                "five_member_forwards",
                "sigmoid_mean_aggregation",
                "routing_comparison",
                "deterministic_audit_hash_decision",
            ],
            "mechanical_routing_threshold": 0.5,
            "mechanical_threshold_has_scientific_role": False,
            "startup_reported_separately": True,
            "single_member_timing_role": "diagnostic_only",
            "authoritative_latency": "complete_five_member_path",
            "compute_pass_threshold": None,
        },
        "access_boundary": {
            "training_strain_or_teacher_labels": [],
            "threshold_search": [],
            "risk_calibration": [],
            "confirmation": [],
            "o4b": [],
            "training_execution_authorized": False,
            "routing_enabled": False,
        },
        "source_references": {
            "outcome_blind_contract": repository_reference(root, design_path),
            "identity_header": repository_reference(root, header_path),
            "identity_manifest": repository_reference(root, identities_path),
            "proposal": repository_reference(root, PROPOSAL),
            "v6_phase_a_contract": repository_reference(
                root, root / "config/dante_light_prefilter_v6_phase_a.json"
            ),
            "v6_member_architecture": repository_reference(
                root, root / "src/dante_light/prefilter_v6_phase_a.py"
            ),
            "audit_fraction_source": repository_reference(root, audit_source_path),
            "freeze_implementation": repository_reference(root, Path(__file__)),
            "freeze_builder": repository_reference(
                root, root / "scripts/freeze_dante_light_prefilter_v7_training.py"
            ),
            "benchmark_runner": repository_reference(
                root, root / "scripts/run_dante_light_prefilter_v7_compute_benchmark.py"
            ),
            "verifier": repository_reference(
                root, root / "scripts/verify_dante_light_prefilter_v7_training.py"
            ),
        },
        "parent_digests": {
            "outcome_blind_contract_digest": frozen["contract_digest"],
            "identity_manifest_sha256": file_sha256(identities_path),
            "confirmation_seal_digest": frozen["seal_digest"],
            "identity_header_digest": header["manifest_digest"],
        },
    }
    contract = {**body, "training_contract_digest": canonical_json_sha256(body)}
    if write_artifacts:
        _write_json(root / DEFAULT_CONTRACT.relative_to(ROOT), contract)
    return contract


def validate_training_freeze(
    contract: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    payload = dict(contract)
    declared = payload.pop("training_contract_digest", None)
    if declared != canonical_json_sha256(payload):
        raise ContractError("v7 training contract self-digest mismatch")
    payload["training_contract_digest"] = declared
    if payload.get("status") != "FROZEN_OUTCOME_BLIND_BEFORE_TRAINING":
        raise ContractError("v7 training contract status changed")
    if any(
        payload["access_boundary"][field]
        for field in (
            "training_strain_or_teacher_labels",
            "threshold_search",
            "risk_calibration",
            "confirmation",
            "o4b",
        )
    ):
        raise ContractError("v7 training freeze crossed an outcome boundary")
    if payload["access_boundary"]["training_execution_authorized"] is not False:
        raise ContractError("v7 training was authorized before its checkpoint")
    references = {
        label: _resolve_reference(root, reference, label)
        for label, reference in payload["source_references"].items()
    }
    frozen = verify_freeze(root)
    if payload["parent_digests"] != {
        "outcome_blind_contract_digest": frozen["contract_digest"],
        "identity_manifest_sha256": file_sha256(references["identity_manifest"]),
        "confirmation_seal_digest": frozen["seal_digest"],
        "identity_header_digest": frozen["manifest_digest"],
    }:
        raise ContractError("v7 training parent digests changed")
    design = _read_json(references["outcome_blind_contract"])
    amendment = payload["semantic_amendment"]
    if (
        design["task"]["student_score"] != amendment["parent_value"]
        or amendment["replacement_name"] != "defer_score"
        or amendment["interpretation"]
        != "bounded_uncalibrated_ranking_score_not_population_probability"
        or amendment["probability_calibration_allowed"] is not False
        or amendment["identity_or_gate_change"] is not False
    ):
        raise ContractError("v7 defer-score semantic amendment changed")
    candidate = payload["candidate"]
    seeds = [int(value) for value in candidate["member_seeds"]]
    seed_parents = [
        payload["parent_digests"]["outcome_blind_contract_digest"],
        payload["parent_digests"]["identity_manifest_sha256"],
        payload["parent_digests"]["identity_header_digest"],
        file_sha256(references["proposal"]),
        file_sha256(references["v6_member_architecture"]),
    ]
    expected_seeds = [
        derive_seed(seed_parents, f"ensemble_member_{index}")
        for index in range(MEMBER_COUNT)
    ]
    ensemble = build_ensemble(root, seeds)
    aggregation = ensemble.members[0].pool.contract
    if (
        candidate["member_count"] != MEMBER_COUNT
        or seeds != expected_seeds
        or candidate["all_members_execute_per_window"] is not True
        or candidate["member_selection_allowed"] is not False
        or candidate["second_stage_distillation_allowed"] is not False
        or candidate["ensemble_operator"]
        != "arithmetic_mean_of_member_sigmoid_outputs"
        or int(candidate["teacher_top_k"]) != aggregation.teacher_top_k
        or int(candidate["teacher_instance_count"]) != aggregation.teacher_instance_count
        or int(candidate["student_top_k"]) != aggregation.student_top_k(256)
        or trainable_parameter_count(ensemble.members[0])
        != int(candidate["trainable_parameters_per_member"])
        or trainable_parameter_count(ensemble)
        != int(candidate["trainable_parameters_total"])
    ):
        raise ContractError("v7 ensemble contract changed")
    split_path = references.get("identity_manifest")
    if split_path is None:
        raise ContractError("v7 identity manifest reference is absent")
    assignments = _read_jsonl(
        root / payload["internal_split"]["assignment_reference"]["path"]
    )
    assignment_reference = payload["internal_split"]["assignment_reference"]
    _resolve_reference(root, assignment_reference, "internal_split")
    rebuilt, seeds_by_cell = assign_internal_split(
        _read_jsonl(split_path),
        parent_digests=seed_parents,
    )
    if (
        assignments != rebuilt
        or canonical_json_sha256(assignments)
        != payload["internal_split"]["assignment_digest"]
        or seeds_by_cell != payload["internal_split"]["seeds_by_cell"]
        or _counts(assignments) != payload["internal_split"]["counts"]
    ):
        raise ContractError("v7 internal split does not reproduce")
    expected_counts = {
        detector: {
            f"{role}/{subset}": 120 if subset == "fit" else 30
            for role in SAMPLING_ROLES
            for subset in ("fit", "internal_validation")
        }
        for detector in DETECTORS
    }
    split = payload["internal_split"]
    if (
        split["unit"] != "detector_gps_4096s_block"
        or split["stratify_by"] != ["detector", "sampling_role"]
        or float(split["fit_fraction"]) != 0.8
        or float(split["internal_validation_fraction"]) != 0.2
        or split["teacher_labels_used_for_assignment"] is not False
        or split["counts"] != expected_counts
    ):
        raise ContractError("v7 internal split semantics changed")
    labels = payload["labels"]
    if labels != {
        "name": "historical_exact_DANTE_defer_label",
        "rule": "native_exact_DANTE_score_strictly_greater_than_historical_detector_threshold",
        "background_is_sampling_role_not_assumed_negative": True,
        "physical_truth_label": False,
        "morphology_labels_in_loss": False,
    }:
        raise ContractError("v7 teacher-label semantics changed")
    optimization = payload["optimization"]
    if (
        optimization["loss"]
        != {"name": "BCEWithLogitsLoss", "weighting": "none", "reduction": "mean"}
        or optimization["batch"]
        != {
            "size": 64,
            "full_batch_per_detector_sampling_role": 16,
            "without_replacement": True,
            "final_partial_batch_retained": True,
            "synthetic_oversampling": False,
        }
        or optimization["optimizer"]
        != {
            "name": "AdamW",
            "learning_rate": 0.001,
            "weight_decay": 0.0001,
            "betas": [0.9, 0.999],
            "epsilon": 1e-8,
        }
        or optimization["scheduler"] != "none_intentional"
        or optimization["gradient_clipping"] is not False
        or optimization["automatic_mixed_precision"] is not False
        or optimization["dtype"] != "float32"
        or int(optimization["maximum_epochs"]) != 100
        or optimization["checkpoint"]
        != "minimum_equal_detector_internal_validation_BCE_then_earliest_epoch"
        or optimization["augmentation"]
        != "none_beyond_canonical_whitening_and_clean_crop"
    ):
        raise ContractError("v7 optimization contract changed")
    audit_source = _read_json(references["audit_fraction_source"])["audit_stream"]
    audit = payload["audit"]
    if (
        float(audit["nominal_fraction"]) != float(audit_source["fraction"])
        or audit["selection"] != audit_source["selection"]
        or audit["finite_cohort_realized_fraction_must_be_reported"] is not True
        or audit["safety_gates_use_pre_audit_predictions"] is not True
        or audit["operational_gate_uses_realized_post_audit_exact_calls"] is not True
        or audit["final_seed_frozen_only_with_threshold_contract"] is not True
    ):
        raise ContractError("v7 audit contract changed")
    benchmark = payload["benchmark"]
    if (
        benchmark["device"] != "cpu"
        or int(benchmark["batch_size"]) != 1
        or int(benchmark["torch_num_threads"]) != 1
        or int(benchmark["warmup_repetitions"]) != 50
        or int(benchmark["timed_repetitions"]) != 300
        or benchmark["authoritative_latency"] != "complete_five_member_path"
        or benchmark["single_member_timing_role"] != "diagnostic_only"
        or benchmark["mechanical_threshold_has_scientific_role"] is not False
        or benchmark["compute_pass_threshold"] is not None
    ):
        raise ContractError("v7 compute benchmark contract changed")
    return {
        "status": "PASS",
        "training_contract_digest": declared,
        "member_count": MEMBER_COUNT,
        "trainable_parameters_total": trainable_parameter_count(ensemble),
        "split_row_count": len(assignments),
        "access_boundary": payload["access_boundary"],
    }


def load_training_freeze(
    path: Path = DEFAULT_CONTRACT, *, root: Path = ROOT
) -> dict[str, Any]:
    payload = _read_json(path)
    validate_training_freeze(payload, root=root)
    return payload
