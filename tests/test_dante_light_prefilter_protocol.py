from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_protocol import load_prefilter_protocol


ROOT = Path(__file__).resolve().parents[1]


def test_versioned_prefilter_protocol_is_frozen_and_self_hashed() -> None:
    protocol = load_prefilter_protocol()
    assert protocol.payload["status"] == "frozen"
    assert protocol.payload["required_detectors"] == ["H1", "L1"]
    assert protocol.reference["sha256"] == protocol.sha256
    assert protocol.reference["protocol_digest"] == protocol.payload["protocol_digest"]


def test_prefilter_protocol_rejects_criterion_change_without_digest(tmp_path) -> None:
    payload = deepcopy(dict(load_prefilter_protocol().payload))
    payload["evaluation"]["minimum_compute_reduction"] = 0.1
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContractError, match="digest mismatch"):
        load_prefilter_protocol(path)


def test_prefilter_protocol_accepts_a_valid_explicit_fixture(tmp_path) -> None:
    payload = deepcopy(dict(load_prefilter_protocol().payload))
    payload["protocol_id"] = "unit-fixture"
    payload.pop("protocol_digest")
    payload["protocol_digest"] = canonical_json_sha256(payload)
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_prefilter_protocol(path).payload["protocol_id"] == "unit-fixture"


def test_frozen_l4_v1_tuning_result_is_an_auditable_not_ready() -> None:
    path = (
        ROOT
        / "artifacts"
        / "dante_light"
        / "prefilter_l4_v1"
        / "threshold_tuning_v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    assert body.pop("artifact_digest") == canonical_json_sha256(body)
    protocol = load_prefilter_protocol()
    assert payload["protocol"] == protocol.reference
    assert payload["status"] == "NOT_READY"
    assert payload["routing_enabled"] is False
    assert (
        payload["operating_point"]["effective_background_reduction"]
        < protocol.payload["tuning"]["minimum_effective_reduction"]
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "36d77d4bd3e2c668b633b6baaf8bd9fef7d8b6df7d3c2abb60666950f975aceb"
    )
