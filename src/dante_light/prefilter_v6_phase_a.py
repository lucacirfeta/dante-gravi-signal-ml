"""Outcome-blind v6 Phase-A student graphs and contract helpers.

These modules are random-weight compute probes.  They are not trained models,
do not read teacher outcomes, and cannot be promoted by this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_student import Raw1DDepthwiseStudentProxy


SCHEMA_VERSION = 1


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_phase_a_contract(path: Path, *, root: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("v6 Phase-A schema mismatch")
    if payload.get("status") != "FROZEN_OUTCOME_BLIND_COMPUTE_FEASIBILITY":
        raise ContractError("v6 Phase-A contract is not frozen")

    body = dict(payload)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-A contract digest mismatch")

    boundary = payload.get("scientific_boundary", {})
    forbidden = (
        "training_allowed",
        "teacher_scores_allowed",
        "morphology_labels_allowed",
        "development_access_allowed",
        "confirmation_access_allowed",
        "o4b_access_allowed",
        "candidate_promotion_allowed",
        "routing_enabled",
    )
    if any(boundary.get(key) is not False for key in forbidden):
        raise ContractError("v6 Phase-A contract permits a forbidden action")

    for name, reference in payload.get("parent_references", {}).items():
        relative = Path(str(reference.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError(f"non-portable parent reference: {name}")
        source = root / relative
        if not source.is_file() or file_sha256(source) != reference.get("sha256"):
            raise ContractError(f"v6 Phase-A parent mismatch: {name}")
    return payload


@dataclass(frozen=True)
class AggregationContract:
    teacher_top_k: int
    teacher_instance_count: int

    @property
    def retained_fraction(self) -> float:
        return self.teacher_top_k / self.teacher_instance_count

    def student_top_k(self, student_instance_count: int) -> int:
        if student_instance_count < 1:
            raise ContractError("student instance count must be positive")
        return max(1, math.floor(student_instance_count * self.retained_fraction + 0.5))


def aggregation_contract(
    phase_a: Mapping[str, Any], teacher: Mapping[str, Any]
) -> AggregationContract:
    specification = phase_a["teacher_aligned_aggregation"]
    teacher_top_k = int(teacher["representation"]["top_k"])
    teacher_instances = int(specification["teacher_instance_count"])
    grid = tuple(int(value) for value in specification["teacher_patch_grid"])
    if len(grid) != 2 or math.prod(grid) != teacher_instances:
        raise ContractError("teacher patch-grid contract mismatch")
    if teacher_top_k < 1 or teacher_top_k > teacher_instances:
        raise ContractError("teacher top-k contract is invalid")
    if specification.get("operator") != "exact_top_fraction_mean":
        raise ContractError("unsupported Phase-A aggregation operator")
    if specification.get("soft_relaxation_frozen") is not False:
        raise ContractError("Phase A must not silently freeze a soft relaxation")
    return AggregationContract(teacher_top_k, teacher_instances)


class Raw1DLocalEncoder(torch.nn.Module):
    """The v5 raw local encoder without its final global average."""

    def __init__(self, *, width_multiplier: int = 1) -> None:
        super().__init__()
        if width_multiplier < 1:
            raise ContractError("width multiplier must be positive")
        c1, c2, c3, c4 = (value * width_multiplier for value in (8, 16, 32, 64))
        self.output_channels = c4
        self.features = torch.nn.Sequential(
            torch.nn.Conv1d(1, c1, 31, stride=8, padding=15),
            torch.nn.GELU(),
            torch.nn.Conv1d(c1, c1, 15, stride=4, padding=7, groups=c1),
            torch.nn.Conv1d(c1, c2, 1),
            torch.nn.GELU(),
            torch.nn.Conv1d(c2, c2, 9, stride=4, padding=4, groups=c2),
            torch.nn.Conv1d(c2, c3, 1),
            torch.nn.GELU(),
            torch.nn.Conv1d(c3, c3, 7, stride=4, padding=3, groups=c3),
            torch.nn.Conv1d(c3, c4, 1),
            torch.nn.GELU(),
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.features(values)


class TopFractionMeanPool1d(torch.nn.Module):
    """Teacher-aligned exact top-fraction mean, differentiable a.e."""

    def __init__(self, contract: AggregationContract) -> None:
        super().__init__()
        self.contract = contract

    def forward(self, instance_scores: torch.Tensor) -> torch.Tensor:
        if instance_scores.ndim != 2:
            raise ContractError("top-fraction pooling expects (batch, instances)")
        k = self.contract.student_top_k(instance_scores.shape[-1])
        return torch.topk(instance_scores, k=k, dim=-1).values.mean(dim=-1)


class Raw1DTeacherAlignedStudent(torch.nn.Module):
    """V5 local encoder with local scores and teacher-fraction pooling."""

    def __init__(
        self, contract: AggregationContract, *, width_multiplier: int = 1
    ) -> None:
        super().__init__()
        self.encoder = Raw1DLocalEncoder(width_multiplier=width_multiplier)
        self.instance_head = torch.nn.Conv1d(self.encoder.output_channels, 1, 1)
        self.pool = TopFractionMeanPool1d(contract)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        local_scores = self.instance_head(self.encoder(values)).squeeze(1)
        return self.pool(local_scores).unsqueeze(-1)


class Raw1DAttentionMILStudent(torch.nn.Module):
    """V5 local encoder with a parameter-light attention-MIL comparator."""

    def __init__(self, *, width_multiplier: int = 1) -> None:
        super().__init__()
        self.encoder = Raw1DLocalEncoder(width_multiplier=width_multiplier)
        channels = self.encoder.output_channels
        self.value_head = torch.nn.Conv1d(channels, 1, 1)
        self.attention_head = torch.nn.Conv1d(channels, 1, 1)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        features = self.encoder(values)
        values_local = self.value_head(features).squeeze(1)
        weights = torch.softmax(self.attention_head(features).squeeze(1), dim=-1)
        return torch.sum(weights * values_local, dim=-1, keepdim=True)


def build_candidate(
    candidate: Mapping[str, Any], contract: AggregationContract
) -> torch.nn.Module:
    candidate_id = str(candidate["id"])
    multiplier = int(candidate["width_multiplier"])
    if candidate_id == "raw_v5_global_average":
        if multiplier != 1:
            raise ContractError("the unchanged v5 baseline must have width multiplier 1")
        return Raw1DDepthwiseStudentProxy()
    if candidate_id in {"raw_teacher_top_fraction", "raw_teacher_top_fraction_x2"}:
        return Raw1DTeacherAlignedStudent(contract, width_multiplier=multiplier)
    if candidate_id == "raw_attention_mil":
        return Raw1DAttentionMILStudent(width_multiplier=multiplier)
    raise ContractError(f"unknown v6 Phase-A candidate: {candidate_id}")


def candidate_seed(contract_digest: str, candidate_id: str) -> int:
    digest = canonical_json_sha256(
        {"contract_digest": contract_digest, "purpose": "model_init", "candidate": candidate_id}
    )
    return int(digest[:16], 16)


def synthetic_seed(contract_digest: str) -> int:
    digest = canonical_json_sha256(
        {"contract_digest": contract_digest, "purpose": "v6_phase_a_outcome_blind_compute_input"}
    )
    return int(digest[:16], 16)
