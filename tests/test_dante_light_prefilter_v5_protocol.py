from __future__ import annotations

import json
from pathlib import Path

from src.dante_light.prefilter_v5_protocol import ROOT, load_protocol, protocol_digest


def test_frozen_protocol_is_self_consistent_and_outcome_blind() -> None:
    protocol = load_protocol(ROOT / "config/dante_light_prefilter_protocol_v5.json")
    assert protocol["protocol_digest"] == protocol_digest(protocol)
    assert protocol["outcome_access_at_freeze"] == {
        "teacher_scores": [], "student_outputs": [], "development": [], "confirmation": [], "o4b": []
    }
    assert len(protocol["training_replicate_seeds"]) == 5


def test_nsbh_spin_and_confirmation_cost_scope_are_explicit() -> None:
    protocol = load_protocol(ROOT / "config/dante_light_prefilter_protocol_v5.json")
    design = protocol["approved_design"]
    stress = design["waveforms"]["aligned_tidal_nsbh_stress"]
    assert stress["approximant"] == "IMRPhenomNSBH"
    assert stress["neutron_star_aligned_spin"] == 0.0
    assert stress["precession"] == "OUT_OF_SCOPE"
    endpoints = set(design["confirmation"]["protected_endpoints"])
    assert {"paired_prefilter_costs", "paired_avoidable_exact_path_costs", "block_bootstrap_net_saving"} <= endpoints


def test_design_has_no_hidden_confirmation_or_o4b_access() -> None:
    design = json.loads((ROOT / "config/dante_light_prefilter_v5_design.json").read_text(encoding="utf-8"))
    boundary = design["scientific_boundary"]
    assert boundary["development_outcomes_allowed"] is False
    assert boundary["confirmation_outcomes_allowed"] is False
    assert boundary["o4b_outcomes_allowed"] is False
    assert boundary["routing_enabled"] is False
