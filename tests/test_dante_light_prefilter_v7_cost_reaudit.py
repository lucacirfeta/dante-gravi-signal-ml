from __future__ import annotations

import copy
import json

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
