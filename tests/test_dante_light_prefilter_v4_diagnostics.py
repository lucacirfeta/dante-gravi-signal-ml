from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_dante_light_prefilter_v4_diagnostics import main


ROOT = Path(__file__).resolve().parents[1]


def test_v4_posthoc_diagnostic_recomputes_exactly(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "analyze_dante_light_prefilter_v4_diagnostics.py",
            "--artifact-dir",
            str(ROOT / "artifacts/dante_light/prefilter_l4_v4_development"),
            "--verify",
        ],
    )
    assert main() == 0


def test_v4_posthoc_diagnostic_preserves_scientific_boundary():
    diagnostic = json.loads(
        (
            ROOT
            / "artifacts/dante_light/prefilter_l4_v4_development/diagnostics_v4.json"
        ).read_text(encoding="utf-8")
    )
    assert diagnostic["status"] == "POSTHOC_DIAGNOSTIC_ONLY"
    assert diagnostic["eligible_for_pass_fail_gate"] is False
    assert diagnostic["updates_frozen_screening"] is False
    assert diagnostic["confirmation_values_used"] == []
    assert diagnostic["o4b_outcomes_used"] == []
    comparison = diagnostic["cross_protocol_descriptive_comparison"]
    assert comparison["controlled_head_to_head"] is False
    assert comparison["v2_spectral_baseline"]["overall_roc_auc"] > comparison[
        "v3_signed_plus_ridge_primary"
    ]["overall_roc_auc"]
    assert comparison["v3_signed_plus_ridge_primary"]["overall_roc_auc"] > comparison[
        "v4_phase_primary"
    ]["overall_roc_auc"]
