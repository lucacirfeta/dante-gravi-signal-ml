"""Fail-closed checks for the O3a/O4a common-channel PEM input freeze."""

from __future__ import annotations

from copy import deepcopy
import inspect
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


def test_shared_null_core_matches_frozen_measurement() -> None:
    from src.pipeline_v2_production import pem_null_calibration as null

    measurement = load_contract(root=ROOT)["method"]["measurement"]
    assert null.WINDOW_S == measurement["background_window_s"]
    assert null.STRIDE_S == measurement["background_stride_s"]
    assert null.GUARD_S == measurement["surrogate_guard_s"]
    assert null.FFTLENGTH_S == measurement["coherence_fftlength_s"]
    assert null.OVERLAP_S == measurement["coherence_overlap_s"]
    assert (null.F_LOW, null.F_HIGH) == tuple(measurement["frequency_band_hz"])
    assert null.CANDIDATE_EXCLUSION_S == measurement["candidate_exclusion_s"]
    assert (
        inspect.signature(null._pick_background_span)
        .parameters["min_clean_windows"]
        .default
        == measurement["minimum_clean_windows"]
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
