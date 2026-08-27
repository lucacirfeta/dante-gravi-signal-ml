from __future__ import annotations

from collections import Counter
import copy
import json

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training_freeze import ROOT
import src.dante_light.prefilter_v7_teacher_stability as stability


CONTRACT = ROOT / "config/dante_light_prefilter_v7_teacher_stability.json"
BASELINE = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_stability"
    / "teacher_stability_baseline_v7.json"
)


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _redigest(payload: dict, field: str) -> dict:
    body = dict(payload)
    body.pop(field, None)
    return {**body, field: canonical_json_sha256(body)}


def test_v7_teacher_stability_contract_is_frozen_before_protected_access() -> None:
    contract = stability.verify_stability_contract(CONTRACT, root=ROOT)
    assert contract["status"] == "FROZEN_PRE_THRESHOLD_SEARCH"
    assert contract["stage_precondition"] == {
        "required_before_first_partition_row_read": [
            "threshold_search",
            "risk_calibration",
            "confirmation",
        ],
        "failure_action": "STOP_NO_ACCESS_NO_RETUNE",
        "partition_data_may_not_be_used_for_canary": True,
        "fingerprint_must_equal_training": True,
        "canary_must_equal_training": True,
        "receipt_chain_required_for_confirmation_unlock": [
            "threshold_search",
            "risk_calibration",
            "confirmation",
        ],
    }
    assert contract["accessed"] == {
        "threshold_search": [],
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
    }


def test_v7_canaries_are_training_only_and_balanced_by_detector_and_role() -> None:
    contract = _load(CONTRACT)
    rows = contract["canary_contract"]["rows"]
    assert len(rows) == len({row["identity_id"] for row in rows}) == 8
    assert Counter((row["detector"], row["sampling_role"]) for row in rows) == {
        ("H1", "background"): 2,
        ("H1", "teacher_positive"): 2,
        ("L1", "background"): 2,
        ("L1", "teacher_positive"): 2,
    }
    assert contract["canary_contract"]["source_partition"] == "training"
    assert contract["canary_contract"]["protected_partition_rows_used"] == 0


def test_v7_prior_partition_access_fails_before_contract_or_raw_access(monkeypatch) -> None:
    reached_contract_verification = False

    def forbidden_verification(*_args, **_kwargs):
        nonlocal reached_contract_verification
        reached_contract_verification = True
        raise AssertionError("contract verification must not be reached")

    monkeypatch.setattr(stability, "verify_stability_contract", forbidden_verification)
    with pytest.raises(ContractError, match="STOP_NO_ACCESS_NO_RETUNE"):
        stability.run_training_canary(
            requested_partition="threshold_search",
            prior_partition_access_entries=1,
        )
    assert reached_contract_verification is False


def test_v7_teacher_fingerprint_change_fails_closed(monkeypatch) -> None:
    contract = _load(CONTRACT)

    def changed_fingerprint(*_args, **_kwargs):
        result = copy.deepcopy(contract["teacher_fingerprint"])
        result["runtime_environment"]["torch"] = "changed"
        body = dict(result)
        body.pop("fingerprint_digest")
        result["fingerprint_digest"] = canonical_json_sha256(body)
        return result

    monkeypatch.setattr(stability, "_teacher_fingerprint", changed_fingerprint)
    with pytest.raises(ContractError, match="STOP_NO_ACCESS_NO_RETUNE"):
        stability.verify_stability_contract(CONTRACT, root=ROOT)


def test_v7_any_canary_mismatch_fails_closed() -> None:
    canary = _load(CONTRACT)["canary_contract"]["rows"][0]
    expected = canary["expected"]
    with pytest.raises(ContractError, match="STOP_NO_ACCESS_NO_RETUNE"):
        stability._require_canary_observation(
            canary,
            raw_strain_sha256=expected["raw_strain_sha256"],
            clean_strain_sha256=expected["clean_strain_sha256"],
            image_sha256="0" * 64,
            teacher_score_float32_hex=expected["teacher_score_float32_hex"],
        )


def test_v7_saved_training_canary_is_an_exact_no_access_pass() -> None:
    contract = stability.verify_stability_contract(CONTRACT, root=ROOT)
    receipt = _load(BASELINE)
    stability.verify_stability_receipt(receipt, contract=contract)
    assert receipt["requested_partition"] == "baseline"
    assert receipt["canary_count"] == 8
    assert receipt["partition_rows_accessed_before_check"] == 0
    assert receipt["accessed"] == {
        "threshold_search": [],
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
    }


def test_v7_redigested_receipt_with_protected_access_still_fails() -> None:
    contract = _load(CONTRACT)
    receipt = _load(BASELINE)
    receipt["accessed"]["threshold_search"] = ["forbidden-row"]
    receipt = _redigest(receipt, "stability_receipt_digest")
    with pytest.raises(ContractError, match="not a clean pre-access PASS"):
        stability.verify_stability_receipt(receipt, contract=contract)


def test_v7_unknown_stage_is_rejected_before_execution() -> None:
    with pytest.raises(ContractError, match="unknown teacher stability stage"):
        stability.run_training_canary(requested_partition="o4b")
