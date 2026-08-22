from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v3_protocol import (
    load_prefilter_v3_protocol,
    verify_prefilter_v3_sources,
)


def _write_protocol(tmp_path, payload):
    payload.pop("protocol_digest", None)
    payload["protocol_digest"] = canonical_json_sha256(payload)
    path = tmp_path / "protocol_v3.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_v3_protocol_freezes_non_circular_confirmation_boundary():
    protocol = load_prefilter_v3_protocol()
    cohort = protocol.payload["cohort_contract"]
    boundary = protocol.payload["scientific_boundary"]
    assert cohort["development_interpretation"] == "hypothesis_generating_exploratory"
    assert cohort["confirmation_partition"] == "evaluation"
    assert cohort["confirmation_feature_values_inspected_before_freeze"] == []
    assert cohort["require_zero_window_overlap"] is True
    assert boundary["o4b_outcomes_allowed_before_confirmation_pass"] is False
    assert boundary["routing_enabled"] is False
    assert protocol.payload["development"]["primary_feature_set"] == "signed_plus_ridge"
    assert protocol.payload["development"]["ablation_eligible_for_selection"] is False
    assert protocol.payload["confirmation"]["can_authorize_operational_pass"] is False


def test_v3_frozen_sources_have_disjoint_reserved_confirmation_cohort():
    evidence = verify_prefilter_v3_sources(load_prefilter_v3_protocol())
    assert evidence["status"] == "PASS"
    assert evidence["overlap_n"] == 0
    assert evidence["nsbh_confirmation_n"] == 180
    assert evidence["confirmation_group_counts"]["injection/H1/NSBH_10_1.4"] == 90
    assert evidence["confirmation_group_counts"]["injection/L1/NSBH_10_1.4"] == 90
    assert evidence["o4b_outcomes_used"] == []


def test_v3_protocol_rejects_prefreeze_confirmation_access(tmp_path):
    payload = deepcopy(dict(load_prefilter_v3_protocol().payload))
    payload["cohort_contract"]["confirmation_feature_values_inspected_before_freeze"] = [
        "injection/H1/NSBH_10_1.4"
    ]
    with pytest.raises(ContractError, match="anti-circularity"):
        load_prefilter_v3_protocol(_write_protocol(tmp_path, payload))


def test_v3_protocol_rejects_iid_uncertainty(tmp_path):
    payload = deepcopy(dict(load_prefilter_v3_protocol().payload))
    payload["uncertainty"]["method"] = "iid_bootstrap"
    with pytest.raises(ContractError, match="block bootstrap"):
        load_prefilter_v3_protocol(_write_protocol(tmp_path, payload))


def test_v3_protocol_rejects_gate_drift(tmp_path):
    payload = deepcopy(dict(load_prefilter_v3_protocol().payload))
    payload["confirmation"]["minimum_retention_by_role"]["injection"] = 0.85
    with pytest.raises(ContractError, match="retention criteria differ"):
        load_prefilter_v3_protocol(_write_protocol(tmp_path, payload))


def test_v3_protocol_rejects_unhashed_change(tmp_path):
    payload = deepcopy(dict(load_prefilter_v3_protocol().payload))
    payload["development"]["minimum_effective_reduction"] = 0.1
    path = tmp_path / "tampered_v3.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="digest mismatch"):
        load_prefilter_v3_protocol(path)
