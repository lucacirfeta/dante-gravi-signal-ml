from __future__ import annotations

import copy
import json

import pytest

from src.dante_light.contracts import ContractError
import src.dante_light.v8_1_phase0 as phase0


def test_phase0_result_recomputes_from_bound_evidence() -> None:
    result = phase0.verify_result()
    assert result["status"] == "PASS_PHASE0_ENGINEERING_AUDIT"
    assert result["exact_profile"]["equivalence"]["pass"] is True
    assert result["exact_profile"]["equivalence"]["mismatches"] == {}
    replay = json.loads(
        (phase0.ROOT / "config/dante_light_replay_v1.json").read_text(encoding="utf-8")
    )
    assert result["top_k_source_of_truth"]["value"] == replay["representation"]["top_k"]
    assert result["top_k_source_of_truth"]["source"] == (
        "versioned_representation_contract"
    )


def test_phase0_profile_is_balanced_and_bitwise_exact() -> None:
    result = phase0.verify_result()
    equivalence = result["exact_profile"]["equivalence"]
    assert equivalence["windows"] == 8
    assert equivalence["detectors"] == {"H1": 4, "L1": 4}
    assert equivalence["max_abs_score_delta"] == {"native": 0.0, "primary": 0.0}


def test_phase0_capacity_does_not_invent_operator_capacity() -> None:
    result = phase0.verify_result()
    capacity = result["capacity_audit"]
    assert capacity["nominal_input"]["windows_per_s"] == pytest.approx(0.0625)
    assert capacity["compute_only"]["service_rate_windows_per_s"] > 2.0
    assert capacity["staged_o4b_executor"]["throughput_windows_per_s"] > 0.5
    assert capacity["human_review"]["observed_exact_escalations"] == 18
    assert capacity["human_review"]["operator_capacity_status"] == "UNMEASURED"
    assert capacity["prioritizer_budget_freeze_allowed"] is False
    assert result["decision"]["default_engine_promoted"] is False


def test_profile_comparison_fails_closed_on_score_change(monkeypatch) -> None:
    original = phase0._validate_profile_run
    calls = 0

    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            result = copy.deepcopy(result)
            first = next(iter(result["records"].values()))
            first["scores"]["native"] += 1e-3
        return result

    monkeypatch.setattr(phase0, "_validate_profile_run", changed)
    with pytest.raises(ContractError, match="profile mismatch"):
        phase0.build_result()


def test_saved_result_digest_fails_closed(monkeypatch) -> None:
    saved = json.loads(phase0.DEFAULT_RESULT.read_text(encoding="utf-8"))
    saved["decision"]["default_engine_promoted"] = True
    monkeypatch.setattr(phase0, "_read_json", lambda _path: saved)
    with pytest.raises(ContractError, match="result digest mismatch"):
        phase0.verify_result()
