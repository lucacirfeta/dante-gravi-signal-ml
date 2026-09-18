from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import ROOT
from src.pipeline_v3_multiscale.efficiency_v2_scale_diagnostic import (
    DEGENERATE_EXCEEDANCE,
    PASS_CI,
    UNDEFINED_CORRELATIONS,
    _mean_statistic,
    _ordered_cell,
    _paired_exceedance_statistic,
    _run_key,
    _trajectory_statistic,
    load_scale_diagnostic_contract,
    validate_scale_diagnostic_contract,
)


def _rehash(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def _draws(seed: int = 42) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 4, size=(2000, 4))


def test_scale_diagnostic_contract_accepts_checked_in_freeze() -> None:
    contract = load_scale_diagnostic_contract(ROOT)
    assert contract["population"]["uses_all_frozen_blocks"]
    assert contract["uncertainty"]["unit"] == "raw_source_block"
    assert contract["uncertainty"]["resamples"] == 2000
    assert contract["uncertainty"][
        "shared_draws_across_morphology_snr_scale_and_metric"
    ]
    assert contract["metrics"]["scale_or_fusion_allowed"] is False
    assert contract["scientific_boundary"]["primary_endpoint_changed"] is False


def test_checked_in_scale_diagnostic_evidence_is_self_consistent() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/multiscale_efficiency_v2"
        / "scale_diagnostic_summary.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert evidence["status"] == (
        "PASS_VERIFIED_MULTISCALE_EFFICIENCY_V2_SCALE_DIAGNOSTIC"
    )
    assert evidence["selection"]["selected_trial_rows"] == 5280
    assert evidence["selection"]["scale_cells"] == 240
    assert evidence["selection"]["trajectories"] == 40
    assert evidence["snr_48_summary"]["Whistle"]["injected_exceeds"] == 800
    assert evidence["snr_48_summary"]["NoiseBlob"]["injected_exceeds"] == 5
    assert evidence["snr_48_summary"]["WallOfLines"]["injected_exceeds"] == 6
    assert evidence["scientific_boundary"]["scale_or_fusion_applied"] is False
    assert evidence["scientific_boundary"]["automatic_best_scale_selected"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["population"]["target_snr"].append(64),
            "population",
        ),
        (
            lambda value: value["metrics"].update(scale_or_fusion_allowed=True),
            "metrics",
        ),
        (
            lambda value: value["uncertainty"].update(unit="trial"),
            "bootstrap",
        ),
        (
            lambda value: value["uncertainty"].update(detectors_pooled=True),
            "bootstrap",
        ),
        (
            lambda value: value["scientific_boundary"].update(
                automatic_best_scale_selected=True
            ),
            "scientific boundary",
        ),
    ],
)
def test_scale_diagnostic_contract_rejects_scientific_drift(
    mutation, message: str
) -> None:
    contract = load_scale_diagnostic_contract(ROOT)
    mutation(contract)
    with pytest.raises(ContractError, match=message):
        validate_scale_diagnostic_contract(_rehash(contract), root=ROOT)


def test_continuous_block_bootstrap_is_deterministic() -> None:
    values = np.asarray([0.0, 1.0, 2.0, 5.0])
    result = _mean_statistic(values, _draws(), confidence=0.95)
    replay = _mean_statistic(values, _draws(), confidence=0.95)
    assert result == replay
    assert result["mean"] == 2.0
    assert result["status"] == PASS_CI
    assert result["bootstrap_replicates"] == 2000


def test_degenerate_paired_exceedance_has_null_interval() -> None:
    result = _paired_exceedance_statistic(
        np.asarray([True] * 4),
        np.asarray([False] * 4),
        _draws(),
        confidence=0.95,
    )
    assert result["mean_gain"] == 1.0
    assert result["confidence_interval_95"] is None
    assert result["bootstrap_replicates"] == 0
    assert result["status"] == DEGENERATE_EXCEEDANCE


def test_interior_paired_exceedance_uses_shared_block_draws() -> None:
    result = _paired_exceedance_statistic(
        np.asarray([True, True, False, False]),
        np.asarray([False, True, False, True]),
        _draws(),
        confidence=0.95,
    )
    assert result["mean_gain"] == 0.0
    assert result["confidence_interval_95"] is not None
    assert result["bootstrap_replicates"] == 2000
    assert result["status"] == PASS_CI


def test_trajectory_fails_closed_when_any_block_correlation_is_undefined() -> None:
    result = _trajectory_statistic(
        np.asarray([0.5, np.nan, 1.0, 0.0]),
        _draws(),
        confidence=0.95,
    )
    assert result["median"] == 0.5
    assert result["confidence_interval_95"] is None
    assert result["defined_blocks"] == 3
    assert result["undefined_blocks"] == 1
    assert result["status"] == UNDEFINED_CORRELATIONS


def test_ordered_cell_requires_each_source_block_exactly_once() -> None:
    rows = [
        {"raw_source_sha256": "b"},
        {"raw_source_sha256": "a"},
    ]
    assert [row["raw_source_sha256"] for row in _ordered_cell(rows, ["a", "b"])] == [
        "a",
        "b",
    ]
    with pytest.raises(ContractError, match="repeats"):
        _ordered_cell([rows[0], rows[0]], ["a", "b"])


def test_run_key_binds_contract_and_injection_artifact() -> None:
    baseline = _run_key("contract-a", "artifact-a")
    assert baseline != _run_key("contract-b", "artifact-a")
    assert baseline != _run_key("contract-a", "artifact-b")
