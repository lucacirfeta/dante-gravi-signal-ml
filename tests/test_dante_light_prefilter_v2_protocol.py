from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v2_protocol import load_prefilter_v2_protocol


def _write_protocol(tmp_path, payload):
    payload.pop("protocol_digest", None)
    payload["protocol_digest"] = canonical_json_sha256(payload)
    path = tmp_path / "protocol_v2.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_prefilter_v2_protocol_freezes_run_boundary_and_coherent_gates():
    protocol = load_prefilter_v2_protocol()
    boundary = protocol.payload["scientific_boundary"]
    assert boundary["primary_development_run"] == "O4A"
    assert boundary["external_known_glitch_run"] == "O3B"
    assert boundary["prospective_evaluation_run"] == "O4B"
    assert boundary["o4b_outcomes_allowed_during_development"] is False
    assert boundary["routing_enabled"] is False
    for role in ("robust_candidate", "known_glitch", "injection"):
        assert (
            protocol.payload["development"]["minimum_retention_by_role"][role]
            == protocol.payload["evaluation"]["minimum_retention_by_role"][role]
        )
        assert (
            protocol.payload["development"]["minimum_wilson_lower_by_role"][role]
            == protocol.payload["evaluation"]["minimum_wilson_lower_by_role"][role]
        )


def test_prefilter_v2_protocol_rejects_o4b_development_leakage(tmp_path):
    payload = deepcopy(dict(load_prefilter_v2_protocol().payload))
    payload["scientific_boundary"]["o4b_outcomes_allowed_during_development"] = True
    path = _write_protocol(tmp_path, payload)
    with pytest.raises(ContractError, match="scientific boundary"):
        load_prefilter_v2_protocol(path)


def test_prefilter_v2_protocol_rejects_development_wilson_mismatch(tmp_path):
    payload = deepcopy(dict(load_prefilter_v2_protocol().payload))
    payload["development"]["minimum_wilson_lower_by_role"]["known_glitch"] = 0.7
    path = _write_protocol(tmp_path, payload)
    with pytest.raises(ContractError, match="Wilson mismatch"):
        load_prefilter_v2_protocol(path)


def test_prefilter_v2_protocol_rejects_unhashed_change(tmp_path):
    payload = deepcopy(dict(load_prefilter_v2_protocol().payload))
    payload["development"]["minimum_effective_reduction"] = 0.1
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="digest mismatch"):
        load_prefilter_v2_protocol(path)
