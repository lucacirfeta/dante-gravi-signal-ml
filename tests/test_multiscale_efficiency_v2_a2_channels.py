from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2_a2_channels import (
    load_a2_contract,
    project_trial,
    validate_a2_contract,
)


ROOT = Path(__file__).resolve().parents[1]
VERSIONED_SUMMARY = (
    ROOT
    / "artifacts"
    / "dante_light"
    / "multiscale_efficiency_v2_a1"
    / "a2_channels_summary.json"
)


def _trial() -> dict:
    return {
        "trial_id": "trial-1",
        "identity_digest": "a" * 64,
        "detector": "H1",
        "role": "heldout_primary_injection",
        "role_index": 3,
        "morphology": "Blip",
        "target_snr": 16.0,
        "endpoint": {
            "baseline_32_recovered": False,
            "a1_recovered": True,
            "baseline_32_threshold": 0.2,
            "joint_threshold": 2.5,
            "joint_surprise": 3.0,
            "scores": {"primary_32": 0.1, "0.5": 0.4},
            "tail_probability_by_endpoint": {
                "primary_32": 0.5,
                "0.5": 0.001,
            },
        },
    }


def test_a2_contract_freezes_separate_channel_policy() -> None:
    contract = load_a2_contract(root=ROOT)
    assert contract["combination_policy"]["logical_or_allowed"] is False
    assert contract["channels"]["production"]["decision_authority"] is True
    assert contract["channels"]["diagnostic"]["decision_authority"] is False


def test_a2_contract_rejects_diagnostic_promotion() -> None:
    contract = json.loads(
        (ROOT / "config" / "dante_multiscale_efficiency_v2_a2.json").read_text(
            encoding="utf-8"
        )
    )
    contract["combination_policy"]["diagnostic_may_promote_candidate"] = True
    body = copy.deepcopy(contract)
    body.pop("contract_digest")
    contract["contract_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="combination policy"):
        validate_a2_contract(contract, root=ROOT)


def test_projection_keeps_diagnostic_only_trigger_out_of_production() -> None:
    projected = project_trial(_trial())
    assert projected["production"]["recovered"] is False
    assert projected["diagnostic"]["triggered"] is True
    assert projected["separation"] == {
        "production_changed": False,
        "diagnostic_has_decision_authority": False,
    }
    assert "union_recovered" not in projected
    assert "combined_recovered" not in projected


def test_projection_rejects_missing_native_score() -> None:
    trial = _trial()
    trial["endpoint"]["scores"].pop("primary_32")
    with pytest.raises(ContractError, match="native 32 s score"):
        project_trial(trial)


def test_versioned_a2_summary_preserves_channel_separation() -> None:
    evidence = json.loads(VERSIONED_SUMMARY.read_text(encoding="utf-8"))
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert evidence["status"] == "PASS_A2_SEPARATE_DIAGNOSTIC_CHANNELS"
    assert evidence["ledger"]["rows"] == 7440
    counts = evidence["aggregate_counts"]
    assert counts["both"] + counts["production_only"] == counts["production_recovered"]
    assert counts["both"] + counts["diagnostic_only"] == counts["diagnostic_triggered"]
    assert evidence["separation_invariants"] == {
        "production_decision_source": "detector_native_32s_only",
        "diagnostic_decision_authority": False,
        "combined_decision_emitted": False,
        "production_threshold_changed": False,
        "diagnostic_threshold_changed": False,
    }
