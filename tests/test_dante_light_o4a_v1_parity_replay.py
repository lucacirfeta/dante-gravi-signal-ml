from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_v1_parity_replay import (
    EXECUTION_PATH, build_execution_contract, validate_execution_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_parity_execution_is_current_and_canonical() -> None:
    stored = json.loads(EXECUTION_PATH.read_text(encoding="utf-8"))
    validate_execution_contract(stored, root=ROOT)
    assert stored == build_execution_contract(ROOT)
    assert stored["scientific_engine"] == "canonical_two_encoder"
    assert stored["scorer_construction"]["shared_encoder"] is False
    assert stored["scorer_construction"]["top_k_source"] == "RepresentationContract.top_k"
    assert stored["data"]["local_only"] is True


def test_parity_execution_rejects_engine_substitution() -> None:
    value = build_execution_contract(ROOT)
    value["scientific_engine"] = "shared_encoder_score_only"
    body = dict(value); body.pop("execution_digest")
    value["execution_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="canonical two-encoder"):
        validate_execution_contract(value, root=ROOT)
