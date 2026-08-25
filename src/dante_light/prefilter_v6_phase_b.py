"""Frozen Phase-B objective and selection helpers for DANTE-Light v6."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_phase_b_planning import file_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "dante_light_prefilter_v6_phase_b_freeze.json"


def derive_seed(contract_digest: str, purpose: str, index: int) -> int:
    return int(
        canonical_json_sha256(
            {
                "contract_digest": contract_digest,
                "purpose": purpose,
                "index": int(index),
            }
        )[:16],
        16,
    )


def load_phase_b_contract(
    path: str | Path = DEFAULT_CONTRACT, *, root: Path = ROOT
) -> dict[str, Any]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 Phase-B contract digest mismatch")
    if payload.get("status") != "FROZEN_PHASE_B_SCREENING_CONTRACT":
        raise ContractError("v6 Phase-B contract is not frozen")
    scope = payload["scope"]
    if any(
        scope[key]
        for key in (
            "phase_c_access_allowed",
            "phase_d_access_allowed",
            "o4b_access_allowed",
            "morphology_labels_allowed",
            "routing_enabled",
        )
    ):
        raise ContractError("v6 Phase-B freeze permits forbidden access")
    if scope["phase_b_training_allowed"] is not True:
        raise ContractError("v6 Phase-B contract does not authorize its declared training")
    for name, reference in payload["source_references"].items():
        relative = Path(reference["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError(f"non-portable v6 Phase-B reference: {name}")
        candidate = root / relative
        if not candidate.is_file() or file_sha256(candidate) != reference["sha256"]:
            raise ContractError(f"v6 Phase-B source mismatch: {name}")
    return payload


def ranknet_block_loss(predictions: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    """Detector-balanced RankNet loss over within-block unordered pairs."""
    if predictions.shape != targets.shape or predictions.ndim != 3:
        raise ContractError("RankNet expects matching (detector, block, window) tensors")
    if predictions.shape[0] != 2 or predictions.shape[2] != 8:
        raise ContractError("RankNet requires two detectors and eight windows per block")
    detector_losses = []
    for detector in range(2):
        block_losses = []
        for block in range(predictions.shape[1]):
            prediction = predictions[detector, block]
            target = targets[detector, block]
            left, right = torch.triu_indices(8, 8, offset=1, device=prediction.device)
            target_difference = target[left] - target[right]
            keep = target_difference != 0
            if not bool(torch.any(keep)):
                raise ContractError("RankNet block has only exact target ties")
            signs = torch.sign(target_difference[keep])
            margins = prediction[left[keep]] - prediction[right[keep]]
            block_losses.append(torch.nn.functional.softplus(-signs * margins).mean())
        detector_losses.append(torch.stack(block_losses).mean())
    return torch.stack(detector_losses).mean()


def detector_balanced_smooth_l1(
    predictions: torch.Tensor, targets: torch.Tensor, *, beta: float
) -> torch.Tensor:
    if predictions.shape != targets.shape or predictions.ndim != 3:
        raise ContractError("SmoothL1 expects matching detector/block/window tensors")
    if predictions.shape[0] != 2:
        raise ContractError("SmoothL1 requires exactly two detector strata")
    return torch.stack(
        [
            torch.nn.functional.smooth_l1_loss(
                predictions[detector], targets[detector], beta=float(beta), reduction="mean"
            )
            for detector in range(2)
        ]
    ).mean()


def _gradient_tuple(
    loss: torch.Tensor, parameters: Sequence[torch.nn.Parameter], *, retain_graph: bool
) -> tuple[torch.Tensor, ...]:
    gradients = torch.autograd.grad(
        loss,
        parameters,
        retain_graph=retain_graph,
        allow_unused=True,
    )
    return tuple(
        torch.zeros_like(parameter) if gradient is None else gradient
        for parameter, gradient in zip(parameters, gradients, strict=True)
    )


def _norm(gradients: Iterable[torch.Tensor]) -> torch.Tensor:
    squares = [torch.sum(gradient.double() * gradient.double()) for gradient in gradients]
    if not squares:
        raise ContractError("equal-gradient objective has no trainable parameters")
    return torch.sqrt(torch.stack(squares).sum())


def equal_gradient_backward(
    *,
    value_loss: torch.Tensor,
    rank_loss: torch.Tensor,
    parameters: Sequence[torch.nn.Parameter],
) -> dict[str, float]:
    """Assign the frozen equal-direction hybrid gradient to ``parameter.grad``."""
    trainable = tuple(parameter for parameter in parameters if parameter.requires_grad)
    value_gradients = _gradient_tuple(value_loss, trainable, retain_graph=True)
    rank_gradients = _gradient_tuple(rank_loss, trainable, retain_graph=False)
    value_norm = _norm(value_gradients)
    rank_norm = _norm(rank_gradients)
    if not bool(torch.isfinite(value_norm)) or not bool(torch.isfinite(rank_norm)):
        raise ContractError("equal-gradient component norm is non-finite")
    if float(value_norm.item()) == 0.0 or float(rank_norm.item()) == 0.0:
        raise ContractError("equal-gradient component norm is zero")
    value_unit = tuple(gradient / value_norm.to(gradient.dtype) for gradient in value_gradients)
    rank_unit = tuple(gradient / rank_norm.to(gradient.dtype) for gradient in rank_gradients)
    direction = tuple(left + right for left, right in zip(value_unit, rank_unit, strict=True))
    direction_norm = _norm(direction)
    if not bool(torch.isfinite(direction_norm)) or float(direction_norm.item()) == 0.0:
        raise ContractError("equal-gradient combined direction is zero or non-finite")
    scale = value_norm / direction_norm
    for parameter, gradient in zip(trainable, direction, strict=True):
        assigned = gradient * scale.to(gradient.dtype)
        if not bool(torch.isfinite(assigned).all()):
            raise ContractError("equal-gradient assigned gradient is non-finite")
        parameter.grad = assigned.detach()
    dot = torch.stack(
        [
            torch.sum(left.double() * right.double())
            for left, right in zip(value_gradients, rank_gradients, strict=True)
        ]
    ).sum()
    cosine = dot / (value_norm * rank_norm)
    if not bool(torch.isfinite(cosine)):
        raise ContractError("equal-gradient component cosine is non-finite")
    final_norm = _norm(parameter.grad for parameter in trainable if parameter.grad is not None)
    return {
        "value_gradient_l2": float(value_norm.item()),
        "rank_gradient_l2": float(rank_norm.item()),
        "detached_lambda_equivalent": float((value_norm / rank_norm).item()),
        "component_cosine": float(cosine.item()),
        "unscaled_direction_l2": float(direction_norm.item()),
        "final_gradient_l2": float(final_norm.item()),
    }


def select_phase_b_arm(
    arm_results: Sequence[Mapping[str, Any]], *, contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply the frozen screening-only worst-cell selection rule."""
    selection = contract["selection_rule"]
    expected_replicates = int(contract["replicates"]["count"])
    expected_detectors = set(contract["data_contract"]["detectors"])
    expected_arms = {str(row["id"]) for row in contract["arms"]}
    observed_arms = [str(row["arm_id"]) for row in arm_results]
    if len(observed_arms) != len(set(observed_arms)) or set(observed_arms) != expected_arms:
        raise ContractError("Phase-B arm result matrix differs from the frozen five arms")
    eligible = []
    for arm in arm_results:
        if arm.get("numerical_failure"):
            continue
        cells = list(arm["validation_cells"])
        expected_cells = expected_replicates * len(expected_detectors)
        if len(cells) != expected_cells:
            raise ContractError(f"incomplete Phase-B validation matrix: {arm['arm_id']}")
        observed_cells = {
            (str(cell["detector"]), int(cell["replicate_index"])) for cell in cells
        }
        expected_cell_ids = {
            (detector, replicate)
            for detector in expected_detectors
            for replicate in range(expected_replicates)
        }
        if observed_cells != expected_cell_ids:
            raise ContractError(f"Phase-B detector/replicate matrix changed: {arm['arm_id']}")
        spearman = [float(cell["spearman"]) for cell in cells]
        smooth_l1 = [float(cell["smooth_l1"]) for cell in cells]
        if not all(math.isfinite(value) for value in (*spearman, *smooth_l1)):
            raise ContractError(f"non-finite Phase-B selection metric: {arm['arm_id']}")
        latency = float(arm["audited_cpu_mean_inference_s"])
        parameter_count = int(arm["trainable_parameters"])
        if not math.isfinite(latency) or latency <= 0 or parameter_count <= 0:
            raise ContractError(f"invalid Phase-B compute tie-break: {arm['arm_id']}")
        eligible.append(
            {
                "arm_id": str(arm["arm_id"]),
                "worst_cell_spearman": min(spearman),
                "worst_cell_smooth_l1": max(smooth_l1),
                "audited_cpu_mean_inference_s": latency,
                "trainable_parameters": parameter_count,
            }
        )
    if not eligible:
        return {"status": "NO_ELIGIBLE_ARM", "phase_c_unlock_allowed": False}
    eligible.sort(
        key=lambda row: (
            -row["worst_cell_spearman"],
            row["worst_cell_smooth_l1"],
            row["audited_cpu_mean_inference_s"],
            row["trainable_parameters"],
            row["arm_id"],
        )
    )
    winner = eligible[0]
    return {
        "status": "SCREENING_SELECTION_COMPLETE",
        "selected": winner,
        "phase_c_unlock_allowed": winner["worst_cell_spearman"]
        >= float(selection["minimum_worst_cell_spearman_for_phase_c_unlock"]),
        "multiplicity_interpretation": selection["multiplicity_interpretation"],
    }
