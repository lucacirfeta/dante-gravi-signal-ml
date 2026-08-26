from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

import pytest
import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training_freeze import (
    ROOT,
    build_ensemble,
    load_training_freeze,
    validate_training_freeze,
)


CONTRACT = ROOT / "config/dante_light_prefilter_v7_training_contract.json"
SPLIT = ROOT / "config/dante_light_prefilter_v7_training_split.jsonl"
ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_design"
    / "five_member_compute_benchmark_v7.json"
)


def _contract() -> dict:
    return load_training_freeze(CONTRACT, root=ROOT)


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_v7_training_freeze_is_outcome_blind_and_unapproved_for_fit() -> None:
    contract = _contract()
    result = validate_training_freeze(contract, root=ROOT)
    assert result["status"] == "PASS"
    boundary = contract["access_boundary"]
    assert boundary["training_execution_authorized"] is False
    assert boundary["routing_enabled"] is False
    for key in (
        "training_strain_or_teacher_labels",
        "threshold_search",
        "risk_calibration",
        "confirmation",
        "o4b",
    ):
        assert boundary[key] == []


def test_v7_score_is_explicitly_not_a_population_probability() -> None:
    contract = _contract()
    amendment = contract["semantic_amendment"]
    assert amendment["parent_value"] == "estimated_probability_of_defer_label"
    assert amendment["replacement_name"] == "defer_score"
    assert amendment["probability_calibration_allowed"] is False
    assert amendment["identity_or_gate_change"] is False
    assert "not_population_probability" in amendment["interpretation"]


def test_v7_internal_split_is_disjoint_and_balanced_by_role() -> None:
    rows = _jsonl(SPLIT)
    assert len(rows) == len({row["identity_id"] for row in rows}) == 600
    assert len({row["block_key"] for row in rows}) == 600
    counts = Counter(
        (row["detector"], row["sampling_role"], row["subset"]) for row in rows
    )
    for detector in ("H1", "L1"):
        for role in ("background", "teacher_positive"):
            assert counts[(detector, role, "fit")] == 120
            assert counts[(detector, role, "internal_validation")] == 30


def test_v7_ensemble_executes_all_five_members_and_returns_mean_sigmoid() -> None:
    contract = _contract()
    model = build_ensemble(ROOT, contract["candidate"]["member_seeds"]).eval()
    calls = [0] * len(model.members)
    handles = []
    for index, member in enumerate(model.members):
        def count_call(_module, _inputs, _output, *, current=index):
            calls[current] += 1

        handles.append(member.register_forward_hook(count_call))
    values = torch.zeros(2, 1, 131072)
    try:
        with torch.inference_mode():
            member_logits = model.member_logits(values)
            expected = torch.sigmoid(member_logits).mean(dim=-1, keepdim=True)
            calls[:] = [0] * len(calls)
            actual = model(values)
    finally:
        for handle in handles:
            handle.remove()
    assert calls == [1, 1, 1, 1, 1]
    assert actual.shape == (2, 1)
    assert torch.isfinite(actual).all()
    torch.testing.assert_close(actual, expected)


def test_v7_ensemble_contract_forbids_member_selection_and_redistillation() -> None:
    candidate = _contract()["candidate"]
    assert candidate["member_count"] == 5
    assert candidate["all_members_execute_per_window"] is True
    assert candidate["member_selection_allowed"] is False
    assert candidate["second_stage_distillation_allowed"] is False
    assert candidate["trainable_parameters_per_member"] == 3665
    assert candidate["trainable_parameters_total"] == 18325
    assert candidate["student_top_k"] == 13


def test_v7_audit_contract_separates_nominal_and_realized_fraction() -> None:
    audit = _contract()["audit"]
    assert audit["nominal_fraction"] == 0.05
    assert audit["finite_cohort_realized_fraction_must_be_reported"] is True
    assert audit["safety_gates_use_pre_audit_predictions"] is True
    assert audit["operational_gate_uses_realized_post_audit_exact_calls"] is True


def test_v7_contract_digest_fails_closed() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    contract["candidate"]["member_count"] = 1
    body = dict(contract)
    body.pop("training_contract_digest")
    contract["training_contract_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="ensemble contract changed"):
        validate_training_freeze(contract, root=ROOT)


def test_v7_optimizer_and_audit_cannot_change_behind_a_new_digest() -> None:
    for path, value, message in (
        (("optimization", "optimizer", "learning_rate"), 0.01, "optimization contract changed"),
        (("audit", "nominal_fraction"), 0.10, "audit contract changed"),
    ):
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        target = contract
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        body = dict(contract)
        body.pop("training_contract_digest")
        contract["training_contract_digest"] = canonical_json_sha256(body)
        with pytest.raises(ContractError, match=message):
            validate_training_freeze(contract, root=ROOT)


def test_v7_complete_ensemble_benchmark_verifies() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_dante_light_prefilter_v7_training.py"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    benchmark = payload["benchmark"]
    assert benchmark["status"] == "PASS_ARTIFACT_INTEGRITY_ONLY"
    assert benchmark["outcome_access"] == {
        "training_strain_or_teacher_labels": [],
        "threshold_search": [],
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
    }


def test_v7_benchmark_cannot_promote_the_candidate() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert artifact["production_candidate"]["member_count"] == 5
    assert artifact["production_candidate"]["all_members_executed_per_window"] is True
    assert artifact["diagnostic_single_member"]["promotion_or_compute_gate_role"] is False
    assert artifact["decision"]["compute_feasibility_gate_frozen"] is False
    assert artifact["decision"]["candidate_promoted"] is False
    assert artifact["decision"]["training_authorized"] is False
    assert artifact["decision"]["routing_enabled"] is False
