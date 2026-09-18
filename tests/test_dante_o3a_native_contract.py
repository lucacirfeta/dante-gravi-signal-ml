from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import (
    load_authorization,
    load_runtime_contract,
    load_scope_contract,
    validate_scope_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def _resign(value: dict, field: str = "contract_digest") -> dict:
    payload = copy.deepcopy(value)
    payload.pop(field, None)
    payload[field] = canonical_json_sha256(payload)
    return payload


def test_authorization_records_all_four_approved_decisions() -> None:
    value = load_authorization(root=ROOT)
    assert value["status"] == "AUTHOR_APPROVED_O3A_NATIVE_SCOPE"
    assert value["author_decisions"] == {
        "scope": "O3A_ONLY_COMPLETE_NATIVE_RECONSTRUCTION",
        "dq_semantics": "CBC_CAT1",
        "run_dependent_artifacts": "FRESH_O3A_ONLY",
        "multiscale": "DIAGNOSTIC_ONLY_DEFERRED",
    }
    assert value["outcome_data_accessed"] is False


def test_runtime_contract_binds_wsl_cuda_and_encoder() -> None:
    value = load_runtime_contract(root=ROOT)
    assert value["runtime_environment"]["operating_system"]["wsl"] is True
    assert value["runtime_environment"]["cuda_device"]["request"] == "cuda"
    assert value["encoder_fingerprint"]["model"]["weights_sha256"]


def test_scope_contract_is_approved_but_execution_remains_fail_closed() -> None:
    value = load_scope_contract(root=ROOT)
    assert value["scope_execution_authorized"] is True
    assert value["pipeline_execution_allowed"] is False
    assert value["public_dq_semantics"] == "CBC_CAT1"
    assert value["unresolved_stage_parameters"]
    assert value["references"]["initial_source_representation"]["role"] == (
        "PRIMARY_SCAN_SEED_ONLY"
    )


def test_scope_contract_rejects_o4a_scientific_import() -> None:
    value = json.loads((ROOT / "config/dante_o3a_native_v1_contract.json").read_text())
    value["scientific_invariants"][
        "o4a_populations_thresholds_scores_classes_import_allowed"
    ] = True
    with pytest.raises(ContractError, match="invariants were weakened"):
        validate_scope_contract(_resign(value), root=ROOT)


def test_scope_contract_rejects_multiscale_promotion() -> None:
    value = json.loads((ROOT / "config/dante_o3a_native_v1_contract.json").read_text())
    value["scientific_invariants"]["multiscale_a2_role"] = "PRODUCTION_GATE"
    with pytest.raises(ContractError, match="invariants were weakened"):
        validate_scope_contract(_resign(value), root=ROOT)


def test_scope_contract_rejects_silent_execution_promotion() -> None:
    value = json.loads((ROOT / "config/dante_o3a_native_v1_contract.json").read_text())
    value["pipeline_execution_allowed"] = True
    with pytest.raises(ContractError, match="silently promoted"):
        validate_scope_contract(_resign(value), root=ROOT)
