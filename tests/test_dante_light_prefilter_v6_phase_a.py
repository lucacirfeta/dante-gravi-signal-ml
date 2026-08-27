from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_student import Raw1DDepthwiseStudentProxy
from src.dante_light.prefilter_v6_phase_a import (
    AggregationContract,
    Raw1DAttentionMILStudent,
    Raw1DLocalEncoder,
    Raw1DTeacherAlignedStudent,
    TopFractionMeanPool1d,
    aggregation_contract,
    build_candidate,
    load_phase_a_contract,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/dante_light_prefilter_v6_phase_a.json"
ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v6_design"
    / "phase_a_compute_feasibility_v6.json"
)


def _contract() -> dict:
    return load_phase_a_contract(CONFIG, root=ROOT)


def _aggregation() -> AggregationContract:
    contract = _contract()
    reference = contract["parent_references"]["teacher_contract"]
    teacher = json.loads((ROOT / reference["path"]).read_text(encoding="utf-8"))
    return aggregation_contract(contract, teacher)


def test_phase_a_freeze_is_strictly_outcome_blind() -> None:
    payload = _contract()
    assert payload["status"] == "FROZEN_OUTCOME_BLIND_COMPUTE_FEASIBILITY"
    boundary = payload["scientific_boundary"]
    assert boundary["scope"] == "random-weight compute and memory feasibility only"
    for key in (
        "training_allowed",
        "teacher_scores_allowed",
        "morphology_labels_allowed",
        "development_access_allowed",
        "confirmation_access_allowed",
        "o4b_access_allowed",
        "candidate_promotion_allowed",
        "routing_enabled",
    ):
        assert boundary[key] is False


def test_teacher_fraction_uses_patch_instances_not_centroids() -> None:
    contract = _aggregation()
    assert contract.teacher_top_k == 68
    assert contract.teacher_instance_count == 37 * 37 == 1369
    assert contract.retained_fraction == pytest.approx(68 / 1369)
    assert contract.student_top_k(256) == 13
    assert contract.retained_fraction != pytest.approx(68 / 275)


def test_exact_top_fraction_pooling_has_known_value_and_gradient() -> None:
    values = torch.tensor([[1.0, 4.0, 2.0, 3.0]], requires_grad=True)
    pool = TopFractionMeanPool1d(AggregationContract(2, 4))
    result = pool(values)
    assert result.item() == pytest.approx(3.5)
    result.sum().backward()
    assert values.grad is not None
    assert values.grad.tolist() == [[0.0, 0.5, 0.0, 0.5]]


def test_v6_local_encoder_is_exact_v5_encoder_before_global_pooling() -> None:
    torch.manual_seed(17)
    baseline = Raw1DDepthwiseStudentProxy().eval()
    local = Raw1DLocalEncoder(width_multiplier=1).eval()
    local.features.load_state_dict(baseline.features[:-1].state_dict())
    values = torch.randn(2, 1, 131072)
    with torch.inference_mode():
        expected = baseline.features[:-1](values)
        actual = local(values)
    assert actual.shape == (2, 64, 256)
    torch.testing.assert_close(actual, expected, rtol=0.0, atol=0.0)


def test_phase_a_candidates_are_finite_and_preserve_frozen_matrix() -> None:
    contract = _contract()
    aggregation = _aggregation()
    observed = {}
    values = torch.zeros(2, 1, 131072)
    for row in contract["candidate_matrix"]:
        model = build_candidate(row, aggregation).eval()
        with torch.inference_mode():
            result = model(values)
        assert result.shape == (2, 1)
        assert torch.isfinite(result).all()
        observed[row["id"]] = sum(parameter.numel() for parameter in model.parameters())
    assert observed["raw_v5_global_average"] == 3665
    assert observed["raw_teacher_top_fraction"] == 3665
    assert observed["raw_attention_mil"] > observed["raw_teacher_top_fraction"]
    assert observed["raw_teacher_top_fraction_x2"] > observed["raw_teacher_top_fraction"]


def test_attention_mil_is_permutation_invariant_over_instances() -> None:
    torch.manual_seed(7)
    model = Raw1DAttentionMILStudent().eval()
    features = torch.randn(3, model.encoder.output_channels, 11)
    permutation = torch.tensor([4, 1, 8, 0, 10, 2, 9, 3, 7, 5, 6])
    with torch.inference_mode():
        first_values = model.value_head(features).squeeze(1)
        first_weights = torch.softmax(model.attention_head(features).squeeze(1), dim=-1)
        first = torch.sum(first_values * first_weights, dim=-1)
        shuffled = features[..., permutation]
        second_values = model.value_head(shuffled).squeeze(1)
        second_weights = torch.softmax(model.attention_head(shuffled).squeeze(1), dim=-1)
        second = torch.sum(second_values * second_weights, dim=-1)
    torch.testing.assert_close(first, second)


def test_contract_digest_and_parent_hashes_fail_closed(tmp_path: Path) -> None:
    payload = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload["scientific_boundary"]["training_allowed"] = True
    body = dict(payload)
    body.pop("contract_digest")
    payload["contract_digest"] = canonical_json_sha256(body)
    corrupted = tmp_path / "contract.json"
    corrupted.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="forbidden action"):
        load_phase_a_contract(corrupted, root=ROOT)


def test_committed_phase_a_artifact_verifies_fail_closed(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v6_phase_a.py"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"status": "PASS"' in completed.stdout

    corrupted = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    corrupted["aggregation"]["retained_fraction"] = 68 / 275
    corrupted_path = tmp_path / "corrupted.json"
    corrupted_path.write_text(json.dumps(corrupted), encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v6_phase_a.py"),
            "--artifact",
            str(corrupted_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "artifact digest mismatch" in rejected.stderr


def test_phase_a_verifier_passes_from_relocated_checkout(tmp_path: Path) -> None:
    clone = tmp_path / "checkout"
    required = (
        "src/__init__.py",
        "src/dante_light/__init__.py",
        "src/dante_light/contracts.py",
        "src/dante_light/prefilter_v4_student.py",
        "src/dante_light/prefilter_v6_phase_a.py",
        "src/core/patch_scorer.py",
        "scripts/run_dante_light_prefilter_v6_phase_a.py",
        "scripts/verify_dante_light_prefilter_v6_phase_a.py",
        "config/dante_light_prefilter_v6_phase_a.json",
        "config/dante_light_prefilter_v5_teacher_contract.json",
        "artifacts/dante_light/prefilter_l4_v5_training/diagnostics_v5.json",
        "artifacts/dante_light/prefilter_l4_v6_design/phase_a_compute_feasibility_v6.json",
    )
    for relative in required:
        source = ROOT / relative
        destination = clone / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    completed = subprocess.run(
        [
            sys.executable,
            str(clone / "scripts/verify_dante_light_prefilter_v6_phase_a.py"),
        ],
        cwd=clone,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert '"status": "PASS"' in completed.stdout
