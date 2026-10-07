"""Fixtures only: no real model, Stage A run or detector data."""

import json
from pathlib import Path

import numpy as np
import pytest

from src.validation.cw_stage_c import (
    paired_metrics,
    pin,
    select_inputs,
    summarize,
    top_k_mean,
    validate_output,
)


def test_top_k():
    assert top_k_mean([1, 4, 2, 3], 2) == 3.5


@pytest.mark.parametrize(
    "values,k", [([1], 0), ([1], 2), ([float("nan")], 1), ([[1]], 1)]
)
def test_invalid_top_k(values, k):
    with pytest.raises(ValueError):
        top_k_mean(values, k)


def test_patch_bound_allows_top_k_switch():
    rng = np.random.default_rng(12)
    centroids = rng.normal(size=(7, 3))
    centroids /= np.linalg.norm(centroids, axis=1)[:, None]
    for _ in range(30):
        base, other = rng.normal(size=(2, 9, 3))
        base /= np.linalg.norm(base, axis=1)[:, None]
        other /= np.linalg.norm(other, axis=1)[:, None]
        a = top_k_mean(1 - (base @ centroids.T).max(axis=1), 3)
        b = top_k_mean(1 - (other @ centroids.T).max(axis=1), 3)
        result = paired_metrics(base, other, a, b, 3, 1)
        assert abs(b - a) <= result["patch_top_k_l2_bound"]


def test_identity_has_zero_metrics():
    x = np.ones((4, 3))
    assert all(v == 0 for v in paired_metrics(x, x, 1, 1, 2, 1).values())


def test_correspondence_required():
    with pytest.raises(ValueError):
        paired_metrics(np.ones((4, 3)), np.ones((3, 3)), 0, 0, 2, 1)


def test_pin_never_waives_mismatch(tmp_path):
    p = tmp_path / "file"
    p.write_text("input")
    with pytest.raises(ValueError, match="provenance"):
        pin(p, "0" * 64)


def test_summary_keeps_dose_phase_groups():
    rows = []
    for phase in (0, 1):
        for score in (-1, 2):
            rows.append(
                {
                    "pulsar": 14,
                    "dose": 0.01,
                    "phase": phase,
                    **paired_metrics(np.ones((4, 3)), np.ones((4, 3)), 0, score, 2, 1),
                }
            )
    result = summarize(rows, ("pulsar", "dose", "phase"))
    assert len(result) == 2
    assert result[0]["signed_score_delta"]["minimum"] == -1


def test_disabled_claims_contract():
    c = json.loads(
        (
            Path(__file__).resolve().parents[1] / "config/dante_cw_stage_c_v1.json"
        ).read_text()
    )
    assert c["acceptance_threshold"] is None
    assert c["equivalence_claim_allowed"] is False
    assert {
        "o4b_execution",
        "flags",
        "threshold_calibration",
        "network_download",
    } <= set(c["forbidden"])


@pytest.mark.parametrize("wrong", ["noise", "hash"])
def test_canonical_baseline_is_bound_to_same_noise(tmp_path, monkeypatch, wrong):
    from src.validation import cw_stage_a

    tasks = [
        {"kind": "baseline", "noise": 0, "id": "a", "components": []},
        {"kind": "baseline", "noise": 1, "id": "b", "components": []},
        {
            "kind": "single",
            "noise": 0,
            "id": "c",
            "pulsar": 0,
            "dose": 0.01,
            "phase": 0,
            "components": [],
        },
    ]
    monkeypatch.setattr(cw_stage_a, "task_grid", lambda _: tasks)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    for task in tasks:
        row = {**task, "arrays_sha256": task["id"]}
        if task["kind"] == "single":
            row.update(
                baseline_id="b" if wrong == "noise" else "a", baseline_sha256="b"
            )
        (receipts / f"{task['id']}.json").write_text(json.dumps(row))
    with pytest.raises(ValueError, match="same-noise"):
        select_inputs(tmp_path, {})


@pytest.mark.parametrize(
    "target",
    [
        "/mnt/c/run",
        "/home/atafe/dante_bench/cw_stage_a_20261007/run_v1/new",
        "/home/atafe/dante_bench/cw_stage_c_20261007",
    ],
)
def test_output_outside_fresh_namespace_rejected(target):
    with pytest.raises(ValueError):
        validate_output(target, "/home/atafe/dante_bench/cw_stage_c_20261007")
