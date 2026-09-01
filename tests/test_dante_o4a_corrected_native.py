from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native import (
    load_native_contract,
    select_native_proposals,
    validate_native_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_native_contract_is_hash_bound_and_balanced() -> None:
    contract = load_native_contract(ROOT)
    parity = contract["historical_parity"]
    assert parity["source_training_total"] == 1294
    assert parity["balanced_target_per_detector"] == 647
    assert contract["gates"]["exact_cardinality_by_detector"] == {
        "H1": 647,
        "L1": 647,
    }
    assert contract["authorization"]["historical_detector_identity_inferred"] is False


def test_native_contract_rejects_scientific_drift() -> None:
    payload = json.loads(
        (ROOT / "config/dante_o4a_corrected_native_v1.json").read_text(
            encoding="utf-8"
        )
    )
    changed = deepcopy(payload)
    changed["historical_parity"]["balanced_target_per_detector"] = 646
    body = dict(changed)
    body.pop("contract_digest")
    changed["contract_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="balanced parity"):
        validate_native_contract(changed, ROOT)


def test_selector_is_outcome_blind_guarded_and_detector_aware() -> None:
    identities = [
        ("H1", 0.0, False),
        ("H1", 200.0, False),
        ("H1", 400.0, True),
        ("H1", 600.0, False),
        ("H1", 800.0, False),
        ("L1", 0.0, False),
        ("L1", 200.0, False),
        ("L1", 400.0, False),
        ("L1", 600.0, False),
        ("L1", 800.0, False),
    ]
    proposals, counts = select_native_proposals(
        identities,
        candidate_times=[400.0],
        calibration_identities={("H1", 0.0), ("L1", 800.0)},
        seed_by_detector={"H1": 42, "L1": 43},
        proposal_limit_per_detector=2,
        minimum_separation_s=96.0,
        candidate_guard_delta_s=128.0,
    )
    assert {row["gps_start"] for row in proposals["H1"]} == {600.0, 800.0}
    assert {row["gps_start"] for row in proposals["L1"]} == {200.0, 600.0}
    assert counts["H1"]["direct_candidate"] == 1
    assert counts["H1"]["candidate_guard"] == 0
    assert counts["H1"]["native_calibration"] == 1
    assert counts["L1"]["candidate_guard"] == 1
    assert counts["L1"]["native_calibration"] == 1


def test_selector_rejects_an_incomplete_frozen_proposal_pool() -> None:
    with pytest.raises(ContractError, match="proposal pool is incomplete"):
        select_native_proposals(
            [("H1", 0.0, False), ("L1", 0.0, False)],
            candidate_times=[],
            calibration_identities=set(),
            seed_by_detector={"H1": 42, "L1": 43},
            proposal_limit_per_detector=2,
            minimum_separation_s=96.0,
            candidate_guard_delta_s=128.0,
        )
