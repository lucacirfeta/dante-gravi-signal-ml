from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import (
    build_dq_snapshot,
    load_authorization,
    load_dq_snapshot,
    load_runtime_contract,
    load_scope_contract,
    load_stage_decision_gate,
    validate_scope_contract,
    validate_dq_snapshot,
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


def test_checked_in_dq_snapshot_is_public_metadata_only() -> None:
    value = load_dq_snapshot(root=ROOT)
    assert value["source"]["flags"] == {
        "H1": "H1_CBC_CAT1",
        "L1": "L1_CBC_CAT1",
    }
    assert value["source"]["outcome_data_accessed"] is False
    assert value["source"]["strain_data_accessed"] is False
    assert value["summaries"]["H1"]["segment_count"] > 0
    assert value["summaries"]["L1"]["livetime_s"] > 0


def test_dq_snapshot_builder_is_deterministic_and_detector_specific() -> None:
    calls: list[tuple[str, int, int]] = []

    def fake(flag: str, start: int, end: int) -> list[tuple[int, int]]:
        calls.append((flag, start, end))
        return [(start + 10, start + 20), (start + 30, start + 50)]

    first = build_dq_snapshot(root=ROOT, segment_fetcher=fake)
    second = build_dq_snapshot(root=ROOT, segment_fetcher=fake)
    assert first == second
    assert first["summaries"] == {
        "H1": {"segment_count": 2, "livetime_s": 30},
        "L1": {"segment_count": 2, "livetime_s": 30},
    }
    assert {call[0] for call in calls} == {"H1_CBC_CAT1", "L1_CBC_CAT1"}


def test_dq_snapshot_rejects_overlap_even_with_valid_self_digest() -> None:
    value = load_dq_snapshot(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["segments"]["H1"][1][0] = mutated["segments"]["H1"][0][1] - 1
    mutated = _resign(mutated, "snapshot_digest")
    with pytest.raises(ContractError, match="overlap or are unsorted"):
        validate_dq_snapshot(mutated)


def test_scope_contract_is_approved_but_execution_remains_fail_closed() -> None:
    value = load_scope_contract(root=ROOT)
    assert value["scope_execution_authorized"] is True
    assert value["pipeline_execution_allowed"] is False
    assert value["public_dq_semantics"] == "CBC_CAT1"
    assert value["unresolved_stage_parameters"]
    assert value["references"]["initial_source_representation"]["role"] == (
        "PRIMARY_SCAN_SEED_ONLY"
    )


def test_stage_decision_gate_is_unresolved_and_non_executable() -> None:
    value = load_stage_decision_gate(root=ROOT)
    assert value["status"] == "AUTHOR_DECISION_REQUIRED"
    assert value["execution_allowed"] is False
    assert value["outcome_data_accessed"] is False
    assert value["strain_data_accessed"] is False
    assert all(item is None for item in value["author_decisions"].values())
    assert value["recommendations"]["native_threshold_statistics"][
        "bootstrap_unit"
    ] == "COMPLETE_NON_OVERLAPPING_TEMPORAL_BLOCKS"


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
