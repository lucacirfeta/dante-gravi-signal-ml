"""Fail-closed checks for the O3a/O4a common-channel PEM input freeze."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_o4a_common_pem_contract import (
    CONTRACT_REL,
    load_contract,
    validate_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def _contract() -> dict:
    return json.loads((ROOT / CONTRACT_REL).read_text(encoding="utf-8"))


def _resign(contract: dict) -> dict:
    value = deepcopy(contract)
    value.pop("contract_digest")
    contract["contract_digest"] = canonical_json_sha256(value)
    return contract


def test_real_parent_and_full_selection_preflight() -> None:
    contract = load_contract(root=ROOT)
    assert contract["status"] == "FROZEN_INPUTS_NO_COMPARATIVE_RESULTS"
    assert set(contract["runs"]) == {"O3a", "O4a"}
    for run in contract["runs"].values():
        assert run["targets"]["expected_count"] == (
            run["primary"]["total"] + run["diagnostic"]["total"]
        )


def test_unsigned_comparative_contract_change_fails() -> None:
    contract = _contract()
    contract["method"]["channels"]["H1"].pop()
    with pytest.raises(ContractError, match="digest"):
        validate_contract(contract, root=ROOT)


def test_resigned_channel_substitution_fails() -> None:
    contract = _contract()
    contract["method"]["channels"]["H1"][0] = "H1:UNAPPROVED_CHANNEL"
    with pytest.raises(ContractError, match="channel intersection"):
        validate_contract(_resign(contract), root=ROOT)


def test_resigned_measurement_change_fails() -> None:
    contract = _contract()
    contract["method"]["measurement"]["bootstrap_resamples"] += 1
    with pytest.raises(ContractError, match="measurement parity"):
        validate_contract(_resign(contract), root=ROOT)


def test_resigned_interpretation_promotion_fails() -> None:
    contract = _contract()
    contract["comparison_boundary"]["global_significance_claim"] = True
    with pytest.raises(ContractError, match="interpretation boundary"):
        validate_contract(_resign(contract), root=ROOT)


def test_resigned_target_receipt_change_fails() -> None:
    contract = _contract()
    contract["runs"]["O4a"]["targets"]["sha256"] = "0" * 64
    with pytest.raises(ContractError, match="raw replay parent|reference digest"):
        validate_contract(_resign(contract), root=ROOT)


def test_resigned_candidate_exclusion_change_fails() -> None:
    contract = _contract()
    contract["runs"]["O3a"]["candidate_exclusion"]["digest"] = "0" * 64
    with pytest.raises(ContractError, match="candidate-exclusion receipt"):
        validate_contract(_resign(contract), root=ROOT)
