from __future__ import annotations
import copy
import json
import numpy as np
import pytest
import src.dante_light.prefilter_v7_risk_calibration as risk
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training_freeze import ROOT


def test_v7_risk_rows_match_every_frozen_cell() -> None:
    rows = risk.risk_calibration_rows(root=ROOT)
    assert len(rows) == 1620
    assert len({row["identity_id"] for row in rows}) == 1620
    assert {row["partition"] for row in rows} == {"risk_calibration"}


def test_v7_risk_authorization_binds_fixed_thresholds_and_sealed_successors() -> None:
    authorization = risk.load_authorization(root=ROOT)
    assert authorization["status"] == "AUTHORIZED_RISK_CALIBRATION_ONLY"
    assert authorization["authorization_digest"] == (
        "0795eae5ee1c89b4a27f6b3a84de421f942ef72ef6bc5d307413746717d67433"
    )
    assert authorization["gate_interpretation"]["background_reduction"] == (
        "realized_post_audit_separate_by_detector_gte_0.50"
    )
    assert authorization["forbidden"]["confirmation"] == []
    assert authorization["forbidden"]["o4b"] == []


def test_v7_risk_retention_gate_preserves_compound_rule() -> None:
    assert risk.retention_gate(55, 60)["pass"] is True
    assert risk.retention_gate(54, 60)["pass"] is False
    assert risk.retention_gate(81, 90)["pass"] is True
    assert risk.retention_gate(80, 90)["pass"] is False


def test_v7_risk_block_bootstrap_is_deterministic() -> None:
    rows = [{"block_key": f"H1:{index}"} for index in range(12)]
    values = np.arange(12, dtype=np.float64)
    assert risk._bootstrap_mean(rows, values, seed=123) == risk._bootstrap_mean(rows, values, seed=123)


def test_v7_risk_execute_rejects_wrong_receipt_before_rows(monkeypatch) -> None:
    authorization = {"threshold_contract_digest": "x"}
    stability = risk.verify_stability_contract(root=ROOT)
    baseline = json.loads((ROOT / "artifacts/dante_light/prefilter_l4_v7_stability/teacher_stability_baseline_v7.json").read_text(encoding="utf-8"))
    wrong = copy.deepcopy(baseline)
    body = dict(wrong); body.pop("stability_receipt_digest"); wrong["stability_receipt_digest"] = canonical_json_sha256(body)
    monkeypatch.setattr(risk, "load_authorization", lambda **_: authorization)
    monkeypatch.setattr(risk, "verify_stability_contract", lambda **_: stability)
    monkeypatch.setattr(risk, "_read_json", lambda _path: wrong)
    monkeypatch.setattr(risk, "risk_calibration_rows", lambda **_: (_ for _ in ()).throw(AssertionError("rows accessed")))
    with pytest.raises(ContractError, match="invalid risk-calibration stability receipt"):
        risk.run_risk_calibration()
