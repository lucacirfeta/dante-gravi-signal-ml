from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

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


def test_v3_protocol_rejects_noncanonical_whitening_pad(tmp_path):
    payload = deepcopy(dict(load_prefilter_v3_protocol().payload))
    payload["feature_extraction"]["whitening_context_pad_s"] = 0.0
    with pytest.raises(ContractError, match="four-second whitening pad"):
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


def test_committed_v3_summary_is_not_ready_and_sealed():
    root = Path(__file__).resolve().parents[1]
    protocol = load_prefilter_v3_protocol()
    path = root / "artifacts/dante_light/prefilter_l4_v3/screening_summary_v3.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("summary_digest")
    assert declared == canonical_json_sha256(body)
    assert payload["status"] == "NOT_READY"
    assert payload["protocol"]["protocol_digest"] == protocol.payload["protocol_digest"]
    assert payload["sealed_boundaries"] == {
        "routing_enabled": False,
        "confirmation_values_used": [],
        "o4b_outcomes_used": [],
        "can_authorize_operational_pass": False,
        "next_stage": "stop_without_opening_reserved_confirmation_or_o4b",
    }
    assert (
        payload["candidate_results"]["signed_plus_ridge"]["development_criteria"]
        == "NOT_MET"
    )
