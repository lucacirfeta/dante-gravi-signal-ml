from __future__ import annotations

import json
from pathlib import Path

from src.dante_light.contracts import canonical_json_sha256


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = (
    ROOT
    / "artifacts"
    / "dante_light"
    / "multiscale_efficiency_v2_a1"
    / "a2_feasibility_summary.json"
)


def test_a2_feasibility_evidence_is_self_consistent() -> None:
    evidence = json.loads(SUMMARY.read_text(encoding="utf-8"))
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert evidence["status"] == "A2_SCIENTIFIC_DECISION_REQUIRED"
    assert evidence["inputs"]["heldout_outcomes_used"] is False


def test_fixed_native_threshold_has_no_common_one_percent_rescue_budget() -> None:
    evidence = json.loads(SUMMARY.read_text(encoding="utf-8"))
    transfer = evidence["fixed_native_threshold_transfer"]
    assert transfer["H1"]["exceedances"] == 35
    assert transfer["L1"]["exceedances"] == 75
    assert transfer["H1"]["nominal_slots_remaining"] == 15
    assert transfer["L1"]["nominal_slots_remaining"] == -25
    assert (
        evidence["finding"][
            "fixed_native_gate_plus_positive_rescue_at_global_one_percent_feasible_in_both_detectors"
        ]
        is False
    )


def test_a2_does_not_silently_select_a_new_scientific_gate() -> None:
    evidence = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert set(evidence["scientific_options"]) == {
        "separate_diagnostic_channels",
        "unified_one_percent_gate",
        "preserve_native_and_raise_global_alpha",
    }
    assert evidence["recommended_option"] == "separate_diagnostic_channels"
