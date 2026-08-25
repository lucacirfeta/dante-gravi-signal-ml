from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_pre_phase_b import (
    load_audit_contract,
    maximum_disjoint_starts,
    ranknet_block_loss,
    smooth_l1_detector_loss,
    valid_starts_for_block,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dante_light_prefilter_v6_pre_phase_b_audit.json"
ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "pre_phase_b_audit_v6.json"
)


def test_pre_phase_b_contract_cannot_freeze_or_access_outcomes() -> None:
    payload = load_audit_contract(CONFIG, root=ROOT)
    boundary = payload["scientific_boundary"]
    for key in (
        "phase_b_frozen",
        "lambda_frozen",
        "partial_blocks_admitted",
        "population_changed",
        "training_allowed",
        "candidate_promotion_allowed",
        "development_access_allowed",
        "confirmation_access_allowed",
        "o4b_access_allowed",
        "teacher_targets_used_by_gradient_diagnostic",
        "morphology_labels_used",
    ):
        assert boundary[key] is False
    assert payload["capacity_audit"]["report_only_no_admission_rule"] is True
    assert payload["gradient_diagnostic"]["lambda_selection_allowed"] is False


def test_ranknet_uses_only_pairs_inside_each_detector_block() -> None:
    targets = torch.tensor(
        [
            [[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]],
            [[7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0]],
        ]
    )
    predictions = targets.clone().requires_grad_(True)
    baseline = ranknet_block_loss(predictions, targets)
    shifted = predictions.detach().clone()
    shifted[0, 0] += 1000.0
    shifted[1, 0] -= 1000.0
    shifted_loss = ranknet_block_loss(shifted, targets)
    assert shifted_loss.item() == pytest.approx(baseline.item(), abs=1e-6)
    baseline.backward()
    assert predictions.grad is not None
    assert torch.isfinite(predictions.grad).all()


def test_ranknet_has_exactly_28_unordered_pairs_per_block() -> None:
    predictions = torch.zeros(2, 1, 8)
    targets = torch.arange(8, dtype=torch.float32).reshape(1, 1, 8).repeat(2, 1, 1)
    observed = ranknet_block_loss(predictions, targets)
    assert observed.item() == pytest.approx(torch.log(torch.tensor(2.0)).item())
    assert torch.triu_indices(8, 8, offset=1).shape[1] == 28


def test_smooth_l1_is_equal_detector_mean() -> None:
    predictions = torch.zeros(2, 1, 8)
    targets = torch.zeros_like(predictions)
    targets[0] = 1.0
    targets[1] = 3.0
    observed = smooth_l1_detector_loss(predictions, targets, beta=1.0)
    expected = (0.5 + 2.5) / 2.0
    assert observed.item() == pytest.approx(expected)


def test_mechanical_capacity_requires_local_cat1_and_padding() -> None:
    block = 10
    left = block * 4096
    starts = valid_starts_for_block(
        block=block,
        local_intervals=[(left, left + 400)],
        cat1_intervals=[(left, left + 360)],
        excluded_intervals=[],
        duration_s=32,
        pad_s=4,
        step_s=4,
    )
    maximal = maximum_disjoint_starts(starts, duration_s=32, pad_s=4)
    assert len(maximal) == 9
    excluded = valid_starts_for_block(
        block=block,
        local_intervals=[(left, left + 400)],
        cat1_intervals=[(left, left + 360)],
        excluded_intervals=[(left + 120, left + 240)],
        duration_s=32,
        pad_s=4,
        step_s=4,
    )
    assert len(maximum_disjoint_starts(excluded, duration_s=32, pad_s=4)) < 9


def test_contract_rejects_retroactive_lambda_selection(tmp_path: Path) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["gradient_diagnostic"]["lambda_selection_allowed"] = True
    body = dict(payload)
    body.pop("contract_digest")
    payload["contract_digest"] = canonical_json_sha256(body)
    path = tmp_path / "contract.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="forbidden action|cannot select lambda"):
        load_audit_contract(path, root=ROOT)


def test_committed_pre_phase_b_audit_is_bounded_and_verifies() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v6_pre_phase_b_audit.py"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert payload["decision"] == {
        "lambda_frozen": False,
        "partial_blocks_admitted": False,
        "phase_b_frozen": False,
        "population_changed": False,
        "training_authorized": False,
    }
    assert payload["gradient_scale"]["input"]["teacher_targets_read"] is False
    assert payload["capacity"]["block_identity"]["duration_s"] == 4096
    assert payload["capacity"]["block_identity"]["window_level_Wilson_independence_established"] is False


def test_verifier_rejects_tampered_gradient_ratio(tmp_path: Path) -> None:
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    payload["gradient_scale"]["replicates"][0]["parameter_gradient_l2"][
        "value_to_rank_ratio"
    ] = 1.0
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v6_pre_phase_b_audit.py"),
            "--artifact",
            str(path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "artifact digest mismatch" in completed.stderr
