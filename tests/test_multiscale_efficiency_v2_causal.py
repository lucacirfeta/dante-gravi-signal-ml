from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import sha256_file
from src.pipeline_v3_multiscale.efficiency_v2_causal import (
    _diagnostic_trial_id,
    _run_key,
    load_causal_contract,
    paired_block_bootstrap,
    select_diagnostic_rows,
    summarize_diagnostic_rows,
    validate_causal_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def _rehash(payload: dict) -> dict:
    value = deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def test_causal_contract_accepts_checked_in_freeze() -> None:
    contract = load_causal_contract(ROOT)
    assert contract["selection"]["reads_outcomes"] is False
    assert contract["expected_cardinality"] == {
        "clean_controls": 80,
        "primary_trials": 960,
        "secondary_trials": 240,
        "total_trials": 1200,
        "detector_morphology_snr_cells": 60,
        "trials_per_cell": 20,
    }
    assert contract["scientific_boundary"]["automatic_causal_label_allowed"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["selection"].__setitem__("rows_per_detector_role", 21),
            "selection",
        ),
        (
            lambda value: value["uncertainty"].__setitem__("method", "iid"),
            "uncertainty",
        ),
        (
            lambda value: value["replay"].__setitem__("score_absolute_tolerance", 1e-3),
            "tolerance",
        ),
        (
            lambda value: value["scientific_boundary"].__setitem__(
                "automatic_causal_label_allowed", True
            ),
            "interpretation",
        ),
    ],
)
def test_causal_contract_rejects_scientific_drift(mutation, message: str) -> None:
    payload = json.loads(
        (ROOT / "config/dante_multiscale_efficiency_v2_causal.json").read_text()
    )
    mutation(payload)
    with pytest.raises(ContractError, match=message):
        validate_causal_contract(_rehash(payload), root=ROOT)


def test_outcome_blind_selection_uses_only_lowest_role_indices() -> None:
    contract = {
        "selection": {
            "rows_per_detector_role": 2,
            "roles": {"primary_injection": [], "secondary_dsd_control": []},
        }
    }
    rows = []
    for role in contract["selection"]["roles"]:
        for detector in ("H1", "L1"):
            for role_index in (2, 0, 1):
                rows.append(
                    {
                        "role": role,
                        "detector": detector,
                        "role_index": role_index,
                        "outcome_that_must_not_be_read": role_index == 2,
                    }
                )
    selected = select_diagnostic_rows(rows, contract)
    assert len(selected) == 8
    assert {row["role_index"] for row in selected} == {0, 1}


def test_paired_block_bootstrap_rejects_duplicate_block_units() -> None:
    rows = [
        {"raw_source_sha256": "same", "metrics": {"x": 1.0}},
        {"raw_source_sha256": "same", "metrics": {"x": 2.0}},
    ]
    with pytest.raises(ContractError, match="one row per block"):
        paired_block_bootstrap(
            rows, metrics=["x"], n_resamples=20, confidence=0.95, seed=42
        )


def test_paired_block_bootstrap_is_deterministic_and_shared_across_metrics() -> None:
    rows = [
        {
            "raw_source_sha256": f"block-{index}",
            "metrics": {"x": float(index), "twice_x": float(2 * index)},
        }
        for index in range(5)
    ]
    first = paired_block_bootstrap(
        rows,
        metrics=["x", "twice_x"],
        n_resamples=200,
        confidence=0.95,
        seed=42,
    )
    second = paired_block_bootstrap(
        rows,
        metrics=["x", "twice_x"],
        n_resamples=200,
        confidence=0.95,
        seed=42,
    )
    assert first == second
    assert first["twice_x"]["mean"] == 2 * first["x"]["mean"]
    assert first["twice_x"]["ci_lower"] == 2 * first["x"]["ci_lower"]
    assert first["twice_x"]["ci_upper"] == 2 * first["x"]["ci_upper"]


def test_cell_summary_keeps_detector_and_morphology_separate() -> None:
    contract = {
        "selection": {"rows_per_detector_role": 2},
        "trace": {"reported_metrics": ["x"]},
        "uncertainty": {"resamples": 50, "confidence": 0.95, "seed": 42},
    }
    rows = []
    for detector in ("H1", "L1"):
        for morphology in ("Blip", "Whistle"):
            for index in range(2):
                rows.append(
                    {
                        "detector": detector,
                        "morphology": morphology,
                        "target_snr": 8.0,
                        "raw_source_sha256": f"{detector}-{morphology}-{index}",
                        "metrics": {"x": float(index)},
                        "recovered": False,
                    }
                )
    summary = summarize_diagnostic_rows(rows, contract)
    assert len(summary) == 4
    assert {
        (row["detector"], row["morphology"], row["target_snr"]) for row in summary
    } == {
        (detector, morphology, 8.0)
        for detector in ("H1", "L1")
        for morphology in ("Blip", "Whistle")
    }


def test_diagnostic_identity_and_run_key_bind_frozen_inputs() -> None:
    trial = _diagnostic_trial_id("a" * 64, "b" * 64)
    assert trial != _diagnostic_trial_id("a" * 64, "c" * 64)
    arguments = {
        "contract_digest": "a" * 64,
        "injection_artifact_digest": "b" * 64,
        "runtime_environment_digest": "c" * 64,
    }
    baseline = _run_key(**arguments)
    changed = _run_key(**{**arguments, "runtime_environment_digest": "d" * 64})
    assert baseline != changed


def test_checked_in_causal_evidence_is_hash_bound() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/multiscale_efficiency_v2/causal_diagnostic_summary.json"
    )
    summary = json.loads(path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest")
    assert declared == canonical_json_sha256(body)
    assert summary["status"] == (
        "PASS_VERIFIED_MULTISCALE_EFFICIENCY_V2_CAUSAL_DIAGNOSTIC"
    )
    assert summary["selection"]["trace_rows"] == 1200
    assert summary["selection"]["trace_cells"] == 60
    report = ROOT / summary["report"]["path"]
    assert sha256_file(report) == summary["report"]["sha256"]
    assert summary["scientific_boundary"]["unique_mechanism_proven"] is False
    assert summary["scientific_boundary"]["production_outputs_changed"] is False
