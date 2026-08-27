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


def test_v7_saved_risk_calibration_result_replays_fail_closed() -> None:
    verified = risk.verify_result(root=ROOT)
    assert verified["status"] == "PASS_VERIFIED_RISK_CALIBRATION"
    assert verified["scientific_status"] == "V7_NOT_READY_RISK_CALIBRATION"
    assert verified["risk_calibration_result_digest"] == (
        "96ee7626f3c6ee57333110eda4c776f490e0ddd87a7240fde766b6446fcafd43"
    )
    assert verified["gate_summary"] == {
        "all_pass": False,
        "primary_pass": False,
        "protected_pass": False,
        "operational_pass": True,
    }
    assert verified["confirmation"] == []
    assert verified["o4b"] == []
    assert verified["routing_enabled"] is False


def test_v7_saved_risk_calibration_preserves_separate_safety_cells() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/prefilter_l4_v7_risk_calibration"
        / "risk_calibration_summary_v7.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    evaluation = payload["evaluation"]
    primary = evaluation["primary_teacher_positive"]
    assert primary["H1"]["retained"] == 53
    assert primary["H1"]["total"] == 58
    assert primary["H1"]["pass"] is True
    assert primary["L1"]["retained"] == 51
    assert primary["L1"]["total"] == 60
    assert primary["L1"]["pass"] is False

    protected = evaluation["protected_morphology"]
    assert len(protected) == 16
    assert {key for key, cell in protected.items() if cell["pass"]} == {
        "H1|robust_candidate|DANTE_ROBUST"
    }
    assert protected["H1|injection|NSBH_10_1.4_LEGACY"]["retained"] == 0
    assert protected["L1|injection|NSBH_10_1.4_LEGACY"]["retained"] == 2
    assert protected["H1|injection|NSBH_ALIGNED_TIDAL_STRESS"]["retained"] == 2
    assert protected["L1|injection|NSBH_ALIGNED_TIDAL_STRESS"]["retained"] == 2


def test_v7_saved_risk_calibration_operational_pass_cannot_promote_failure() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/prefilter_l4_v7_risk_calibration"
        / "risk_calibration_summary_v7.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    operational = payload["evaluation"]["operational"]
    assert operational["background_by_detector"]["H1"]["realized_post_audit_reduction"] == pytest.approx(
        0.9333333333333333
    )
    assert operational["background_by_detector"]["L1"]["realized_post_audit_reduction"] == pytest.approx(
        0.9333333333333333
    )
    assert operational["combined_net_saving"]["lower95"] == pytest.approx(
        0.6999854297081078
    )
    assert operational["combined_net_saving"]["pass"] is True
    assert payload["candidate_promoted"] is False
    assert payload["routing_enabled"] is False
