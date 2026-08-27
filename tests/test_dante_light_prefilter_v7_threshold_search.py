from __future__ import annotations

import copy
import json

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training_freeze import ROOT
import src.dante_light.prefilter_v7_threshold_search as search


def _row(detector: str, role: str, score: float, label: int) -> dict:
    return {
        "detector": detector,
        "sampling_role": role,
        "student": {"ensemble_defer_score": score},
        "teacher_target": {"defer_label": label},
    }


def test_v7_threshold_authorization_is_search_only() -> None:
    payload = search.load_threshold_search_authorization(root=ROOT)
    assert payload["status"] == "AUTHORIZED_THRESHOLD_SEARCH_ONLY"
    assert payload["allowed"]["partition"] == "threshold_search"
    assert payload["selection_rule"]["safety_endpoint"] == "pre_audit_model_retention"
    assert payload["forbidden"] == {
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
        "routing": False,
        "retuning": False,
        "fallback_threshold": False,
        "member_selection": False,
    }


def test_v7_threshold_rows_are_exactly_the_frozen_60x4_partition() -> None:
    rows = search.threshold_search_rows(root=ROOT)
    assert len(rows) == 240
    assert {row["partition"] for row in rows} == {"threshold_search"}
    for detector in ("H1", "L1"):
        for role in ("background", "teacher_positive"):
            assert sum(
                row["detector"] == detector and row["sampling_role"] == role
                for row in rows
            ) == 60


def test_v7_threshold_selection_maximizes_discard_under_compound_gate() -> None:
    rows = []
    rows.extend(_row("H1", "background", value / 100, 0) for value in range(60))
    rows.extend(_row("H1", "teacher_positive", 0.90 + value / 1000, 1) for value in range(60))
    selected = search.select_detector_threshold(rows)
    assert selected["teacher_positive_retention"]["pass"] is True
    assert selected["natural_background_discard_fraction"] == 1.0
    assert selected["threshold"] == pytest.approx(0.90)


def test_v7_threshold_tie_break_is_lower_and_more_conservative() -> None:
    rows = [_row("H1", "background", 0.1, 0) for _ in range(60)]
    rows += [_row("H1", "teacher_positive", 0.8, 1) for _ in range(60)]
    selected = search.select_detector_threshold(rows)
    assert selected["threshold"] == 0.8
    assert selected["natural_background_discard_fraction"] == 1.0


def test_v7_historical_sampling_role_is_not_itself_the_positive_condition() -> None:
    rows = [_row("H1", "background", 0.1, 0) for _ in range(60)]
    rows += [_row("H1", "teacher_positive", 0.9, 0) for _ in range(60)]
    with pytest.raises(ContractError, match="conditioning cohort is empty"):
        search.select_detector_threshold(rows)


def test_v7_retention_gate_keeps_point_and_wilson_as_an_and_rule() -> None:
    assert search.retention_gate(55, 60)["pass"] is True
    assert search.retention_gate(54, 60)["pass"] is False


def test_v7_execute_rejects_wrong_stage_receipt_before_identity_rows(monkeypatch) -> None:
    authorization = search.load_threshold_search_authorization(root=ROOT)
    stability = search.verify_stability_contract(root=ROOT)
    baseline = json.loads(search.DEFAULT_STABILITY_RECEIPT.parent.parent.joinpath(
        "prefilter_l4_v7_stability/teacher_stability_baseline_v7.json"
    ).read_text(encoding="utf-8"))
    wrong = copy.deepcopy(baseline)
    wrong["requested_partition"] = "baseline"
    body = dict(wrong)
    body.pop("stability_receipt_digest")
    wrong["stability_receipt_digest"] = canonical_json_sha256(body)
    monkeypatch.setattr(search, "load_threshold_search_authorization", lambda **_: authorization)
    monkeypatch.setattr(search, "verify_stability_contract", lambda **_: stability)
    monkeypatch.setattr(search, "_read_json", lambda _path: wrong)
    reached_rows = False

    def forbidden_rows(**_kwargs):
        nonlocal reached_rows
        reached_rows = True
        raise AssertionError("protected rows must not be read")

    monkeypatch.setattr(search, "threshold_search_rows", forbidden_rows)
    with pytest.raises(ContractError, match="wrong stability receipt stage"):
        search.run_threshold_search()
    assert reached_rows is False


def test_v7_redigested_authorization_cannot_open_calibration() -> None:
    path = ROOT / "config/dante_light_prefilter_v7_threshold_search_authorization.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["forbidden"]["risk_calibration"] = ["opened"]
    body = dict(payload)
    body.pop("authorization_digest")
    payload["authorization_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="protected boundary widened"):
        temporary = path.with_name("tampered_threshold_authorization.json")
        try:
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            search.load_threshold_search_authorization(temporary, root=ROOT)
        finally:
            temporary.unlink(missing_ok=True)
