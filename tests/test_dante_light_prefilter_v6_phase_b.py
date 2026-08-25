from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v6_phase_b import (
    detector_balanced_smooth_l1,
    equal_gradient_backward,
    load_phase_b_contract,
    ranknet_block_loss,
    select_phase_b_arm,
)


ROOT = Path(__file__).resolve().parents[1]


def test_equal_gradient_has_frozen_value_norm_and_no_hidden_balancer_state() -> None:
    parameter = torch.nn.Parameter(torch.tensor([0.25, -0.5], dtype=torch.float32))
    value_loss = torch.square(parameter - torch.tensor([1.0, 2.0])).sum()
    rank_loss = torch.square(parameter - torch.tensor([-2.0, 1.0])).sum()
    value_gradient = torch.autograd.grad(value_loss, parameter, retain_graph=True)[0]
    expected_norm = torch.linalg.vector_norm(value_gradient).item()
    diagnostic = equal_gradient_backward(
        value_loss=value_loss,
        rank_loss=rank_loss,
        parameters=[parameter],
    )
    assert torch.isfinite(parameter.grad).all()
    assert torch.linalg.vector_norm(parameter.grad).item() == pytest.approx(expected_norm)
    assert diagnostic["final_gradient_l2"] == pytest.approx(expected_norm)
    assert diagnostic["detached_lambda_equivalent"] > 0


def test_equal_gradient_fails_closed_on_zero_or_cancelling_component() -> None:
    parameter = torch.nn.Parameter(torch.tensor([1.0, 2.0]))
    with pytest.raises(ContractError, match="component norm is zero"):
        equal_gradient_backward(
            value_loss=(parameter * 0).sum(),
            rank_loss=torch.square(parameter).sum(),
            parameters=[parameter],
        )
    with pytest.raises(ContractError, match="combined direction"):
        equal_gradient_backward(
            value_loss=parameter.sum(),
            rank_loss=-parameter.sum(),
            parameters=[parameter],
        )


def test_losses_preserve_detector_and_block_structure() -> None:
    targets = torch.arange(16, dtype=torch.float32).reshape(2, 1, 8)
    aligned = targets.clone().requires_grad_(True)
    reversed_prediction = torch.flip(targets, dims=(-1,)).requires_grad_(True)
    assert ranknet_block_loss(aligned, targets) < ranknet_block_loss(reversed_prediction, targets)
    assert detector_balanced_smooth_l1(aligned, targets, beta=1.0).item() == 0.0
    with pytest.raises(ContractError, match="eight windows"):
        ranknet_block_loss(torch.zeros(2, 1, 7), torch.zeros(2, 1, 7))


def _arm_results(contract: dict[str, object]) -> list[dict[str, object]]:
    results = []
    for arm_index, arm in enumerate(contract["arms"]):
        cells = [
            {
                "detector": detector,
                "replicate_index": replicate,
                "spearman": 0.91 + arm_index * 0.005,
                "smooth_l1": 0.2 - arm_index * 0.01,
            }
            for detector in ("H1", "L1")
            for replicate in range(5)
        ]
        results.append(
            {
                "arm_id": arm["id"],
                "validation_cells": cells,
                "numerical_failure": False,
                "audited_cpu_mean_inference_s": 0.001 + arm_index * 0.0001,
                "trainable_parameters": 3665 + arm_index,
            }
        )
    return results


def test_selection_is_worst_cell_screening_not_confirmation() -> None:
    contract = load_phase_b_contract()
    results = _arm_results(contract)
    selected = select_phase_b_arm(results, contract=contract)
    assert selected["selected"]["arm_id"] == contract["arms"][-1]["id"]
    assert selected["phase_c_unlock_allowed"] is True
    assert "no_confirmatory_claim" in selected["multiplicity_interpretation"]
    results[-1]["numerical_failure"] = True
    selected = select_phase_b_arm(results, contract=contract)
    assert selected["selected"]["arm_id"] == contract["arms"][-2]["id"]


def test_phase_b_freeze_recomputes_without_outcomes() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_dante_light_prefilter_v6_phase_b.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "PASS"
    assert payload["arm_count"] == 5
    assert payload["replicate_count"] == 5
    assert payload["outcomes_accessed"] == []
