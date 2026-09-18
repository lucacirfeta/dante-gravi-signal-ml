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
    / "analysis_summary.json"
)
REPORT = ROOT / "docs" / "MULTISCALE_EFFICIENCY_V2_A1_REPORT.md"


def _summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def test_a1_analysis_summary_digest_and_provenance_are_frozen() -> None:
    evidence = _summary()
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert evidence["status"] == "PASS_VERIFIED_A1_ANALYSIS"
    assert evidence["assessment"] == "GENUINE_CONFIRMATORY_ADVANCE_WITH_MORPHOLOGY_LIMITS"
    assert evidence["heldout"]["clean_controls"] == 2280
    assert evidence["heldout"]["paired_injections"] == 7440


def test_a1_confirmatory_claims_are_detector_separated_and_complete() -> None:
    evidence = _summary()
    gains = evidence["confirmatory"]["paired_curve_gain"]
    assert set(gains) == {"H1|Blip", "L1|Blip", "H1|Whistle", "L1|Whistle"}
    assert all(item["mean"] > 0.4 for item in gains.values())
    assert all(item["ci95"][0] > 0.0 for item in gains.values())
    assert all(not row["significant_excess"] for row in evidence["confirmatory"]["background_fpr"].values())


def test_a1_report_preserves_limitations_and_decision_boundary() -> None:
    evidence = _summary()
    h1 = evidence["descriptive_recovery"]["H1"]
    l1 = evidence["descriptive_recovery"]["L1"]
    assert sum(h1["HarmonicComb"]["a1"]) < sum(h1["HarmonicComb"]["baseline_32"])
    assert sum(l1["HarmonicComb"]["a1"]) < sum(l1["HarmonicComb"]["baseline_32"])
    assert sum(h1["WallOfLines"]["a1"]) == 0
    assert sum(l1["WallOfLines"]["a1"]) == 0
    assert evidence["descriptive_recovery"]["no_additional_inference"] is True
    audit = evidence["harmonic_comb_regression_audit"]
    assert audit["status"] == "CHARACTERIZED_MULTIPLICITY_PENALTY_NOT_REPRESENTATION_REMOVAL"
    for detector in ("H1", "L1"):
        assert (
            audit[detector]["baseline_only_minimum_endpoint_tail_probability_range"][0]
            > audit[detector]["joint_critical_tail_probability"]
        )
    boundary = evidence["decision_boundary"]
    assert boundary["automatic_production_promotion"] is False
    assert boundary["o3_transfer_claim"] is False
    report = REPORT.read_text(encoding="utf-8")
    assert "not ready for automatic production promotion" in report
    assert "do not transfer the result to O3 yet" in report
