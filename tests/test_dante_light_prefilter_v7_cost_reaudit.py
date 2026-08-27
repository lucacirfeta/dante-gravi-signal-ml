from __future__ import annotations

import copy
import json

import numpy as np
import pytest

import src.dante_light.prefilter_v7_cost_reaudit as reaudit
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training_freeze import ROOT


def test_cost_reaudit_contract_fails_closed_and_preserves_one_shot() -> None:
    contract = reaudit.verify_contract(root=ROOT)
    assert contract["erratum"]["original_operational_cost_interpretation"] == (
        "INDETERMINATE_COST_ACCOUNTING"
    )
    assert contract["source_result"]["immutable"] is True
    assert contract["decision"]["promotion_allowed"] is False
    assert contract["decision"]["confirmation_access_allowed"] is False
    assert contract["decision"]["o4b_access_allowed"] is False


def test_cost_reaudit_contract_uses_two_nonmixed_estimands() -> None:
    contract = reaudit.verify_contract(root=ROOT)
    measurement = contract["measurement"]
    assert measurement["workers"] == 4
    assert measurement["batch_size"] == 8
    assert measurement["teacher_score_batch_size"] == 1
    assert measurement["data_read_excluded"] is True
    assert measurement["whitening_excluded"] is True
    assert measurement["model_load_excluded"] is True
    assert measurement["batch_statistical_role"] == (
        "point_and_batch_distribution_diagnostic_no_iid_bootstrap"
    )
    assert contract["bootstrap"]["unit"] == "detector_gps_4096s_block"


def test_cost_reaudit_contract_rejects_interpretation_widening(monkeypatch) -> None:
    source = json.loads(reaudit.DEFAULT_CONTRACT.read_text(encoding="utf-8"))
    changed = copy.deepcopy(source)
    changed["decision"]["promotion_allowed"] = True
    body = dict(changed)
    body.pop("contract_digest")
    changed["contract_digest"] = canonical_json_sha256(body)
    monkeypatch.setattr(reaudit, "_read_json", lambda _path: changed)
    with pytest.raises(ContractError, match="decision boundary changed"):
        reaudit.verify_contract(root=ROOT)


def test_saved_cost_reaudit_is_verified_and_cannot_promote() -> None:
    verified = reaudit.verify_result(root=ROOT)
    assert verified["status"] == "PASS_VERIFIED_COST_REAUDIT"
    assert verified["decision"]["original_cost_gate_superseded"] is True
    assert verified["decision"]["candidate_promoted"] is False
    assert verified["decision"]["routing_enabled"] is False
    assert verified["decision"]["confirmation"] == []
    assert verified["decision"]["o4b"] == []


def test_saved_cost_reaudit_numbers_recompute_from_bound_ledgers() -> None:
    result = json.loads(reaudit.DEFAULT_RESULT.read_text(encoding="utf-8"))
    ledger = [
        json.loads(line)
        for line in reaudit.DEFAULT_LEDGER.read_text(encoding="utf-8").splitlines()
    ]
    values = np.asarray(
        [row["sequential_isolated"]["net_saving_s"] for row in ledger],
        dtype=np.float64,
    )
    exact = np.asarray(
        [row["sequential_isolated"]["avoidable_exact_path_s"] for row in ledger],
        dtype=np.float64,
    )
    light = np.asarray(
        [row["sequential_isolated"]["light_path_s"] for row in ledger],
        dtype=np.float64,
    )
    assert len(ledger) == 300
    assert sum(row["avoided_exact_call"] for row in ledger) == 280
    assert np.mean(exact) == pytest.approx(
        result["sequential_isolated"]["mean_avoidable_exact_path_s"]
    )
    assert np.mean(light) == pytest.approx(
        result["sequential_isolated"]["mean_light_path_s"]
    )
    assert np.mean(values) == pytest.approx(
        result["sequential_isolated"]["paired_block_bootstrap"]["mean_net_saving_s"]
    )

    batches = result["batch_throughput"]["batches"]
    baseline = sum(row["baseline_exact_makespan_s"] for row in batches)
    light_total = sum(row["light_makespan_s"] for row in batches)
    residual = sum(row["residual_exact_makespan_s"] for row in batches)
    assert sum(row["row_count"] for row in batches) == 300
    assert sum(row["residual_exact_count"] for row in batches) == 20
    assert baseline == pytest.approx(
        result["batch_throughput"]["baseline_exact_total_makespan_s"]
    )
    assert light_total == pytest.approx(
        result["batch_throughput"]["light_total_makespan_s"]
    )
    assert residual == pytest.approx(
        result["batch_throughput"]["residual_exact_total_makespan_s"]
    )
    assert (baseline - light_total - residual) / 300 == pytest.approx(
        result["batch_throughput"]["net_saving_s_per_window"]
    )


def test_v7_result_document_marks_original_cost_claim_as_superseded() -> None:
    report = (
        ROOT / "docs/DANTE_LIGHT_L4_PREFILTER_V7_RISK_CALIBRATION_RESULT_2026-08-27.md"
    ).read_text(encoding="utf-8")
    assert "INDETERMINATE_COST_ACCOUNTING" in report
    assert "0.368600 s" in report
    assert "0.322849 s" in report
    assert "Direct negative NSBH evidence was obtained in v2, v3," in report
