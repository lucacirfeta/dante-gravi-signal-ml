from __future__ import annotations

import copy
import json

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import ROOT
from src.pipeline_v3_multiscale.efficiency_v2_reference import (
    _reference_run_key,
    _score_tokens,
    load_reference_contract,
    raw_block_bootstrap_p99,
    validate_reference_contract,
)


def _rehash(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def test_reference_contract_accepts_checked_in_protocol() -> None:
    contract = load_reference_contract(ROOT)
    assert contract["status"] == "APPROVED_REFERENCE_BUILD_INPUT"
    assert contract["gates"]["bootstrap_unit"] == "raw_source_block"
    assert contract["gates"]["legacy_artifacts_consumed"] is False


def test_reference_run_key_binds_contract_cohort_and_runtime() -> None:
    baseline = _reference_run_key(
        reference_contract_digest="a" * 64,
        cohort_artifact_digest="b" * 64,
        runtime_environment_digest="c" * 64,
    )
    changed_runtime = _reference_run_key(
        reference_contract_digest="a" * 64,
        cohort_artifact_digest="b" * 64,
        runtime_environment_digest="d" * 64,
    )
    assert len(baseline) == 64
    assert baseline != changed_runtime


def test_checked_in_preflight_evidence_is_self_consistent() -> None:
    path = (
        ROOT
        / "artifacts/dante_light/multiscale_efficiency_v2"
        / "reference_preflight_summary.json"
    )
    evidence = json.loads(path.read_text(encoding="utf-8"))
    declared = evidence.pop("artifact_digest")
    assert declared == canonical_json_sha256(evidence)
    assert evidence["status"] == "PASS_MULTISCALE_EFFICIENCY_V2_REFERENCE_PREFLIGHT"
    assert evidence["replay"]["token_shape"] == [4, 1369, 384]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["gates"].update(index_rows_per_detector=499),
        lambda value: value["gates"].update(bootstrap_unit="row"),
        lambda value: value["gates"].update(detectors_pooled=True),
        lambda value: value["gates"].update(legacy_artifacts_consumed=True),
    ],
)
def test_reference_contract_rejects_scientific_drift(mutation) -> None:
    contract = load_reference_contract(ROOT)
    mutation(contract)
    with pytest.raises(ContractError, match="reference gates changed"):
        validate_reference_contract(_rehash(contract), root=ROOT)


def test_raw_block_bootstrap_is_deterministic_and_block_based() -> None:
    arguments = {
        "scores": [0.0, 0.0, 1.0, 1.0],
        "raw_block_labels": ["block-a", "block-a", "block-b", "block-b"],
        "n_resamples": 200,
        "seed": 17,
        "confidence": 0.95,
        "percentile": 99.0,
    }
    first = raw_block_bootstrap_p99(**arguments)
    second = raw_block_bootstrap_p99(**arguments)
    assert first == second
    assert first["raw_block_count"] == 2
    assert first["score_count"] == 4
    assert first["point_p99"] == pytest.approx(1.0)
    assert first["ci_lower"] <= first["ci_upper"]


@pytest.mark.parametrize(
    ("scores", "labels"),
    [([1.0], ["only"]), ([1.0, float("nan")], ["a", "b"])],
)
def test_raw_block_bootstrap_rejects_invalid_inputs(scores, labels) -> None:
    with pytest.raises(ContractError):
        raw_block_bootstrap_p99(
            scores,
            labels,
            n_resamples=10,
            seed=1,
            confidence=0.95,
            percentile=99.0,
        )


def test_topk_scoring_uses_patch_to_nearest_centroid_distance() -> None:
    torch = pytest.importorskip("torch")
    tokens = torch.tensor([[[1.0, 0.0], [0.0, 1.0], [2**-0.5, 2**-0.5]]])
    centroids = torch.tensor([[1.0, 0.0], [0.0, 1.0]])
    score = _score_tokens(tokens, centroids, top_k=1)
    assert score == pytest.approx([1.0 - 2**-0.5])
