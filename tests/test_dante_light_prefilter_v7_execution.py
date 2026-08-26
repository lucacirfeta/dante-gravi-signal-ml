from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training import (
    DEFAULT_AUTHORIZATION,
    ROLES,
    SUBSETS,
    TrainingArrays,
    balanced_epoch_batches,
    checkpoint_better,
    load_training_authorization,
    strict_defer_label,
    training_rows,
)


def test_v7_authorization_is_training_only_and_digest_closed() -> None:
    receipt = load_training_authorization()
    assert receipt["allowed"]["partition"] == "training"
    assert receipt["forbidden"] == {
        "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
        "routing": False, "member_selection": False, "second_stage_distillation": False,
    }


def test_v7_authorization_rejects_widened_scope(tmp_path: Path) -> None:
    receipt = json.loads(DEFAULT_AUTHORIZATION.read_text(encoding="utf-8"))
    receipt["forbidden"]["threshold_search"] = ["opened"]
    body = dict(receipt); body.pop("authorization_digest")
    receipt["authorization_digest"] = canonical_json_sha256(body)
    path = tmp_path / "authorization.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ContractError, match="boundary widened"):
        load_training_authorization(path)


def test_v7_authorized_rows_remain_training_only() -> None:
    rows = training_rows()
    assert len(rows) == len({row["identity_id"] for row in rows}) == 600
    assert len({row["block_key"] for row in rows}) == 600
    assert {row["partition"] for row in rows} == {"training"}


def test_v7_label_rule_is_strictly_greater() -> None:
    assert strict_defer_label(0.2, 0.1) == 1
    assert strict_defer_label(0.1, 0.1) == 0
    assert strict_defer_label(0.0, 0.1) == 0


def _arrays() -> TrainingArrays:
    detectors=[]; roles=[]; subsets=[]; ids=[]
    for subset_index, subset in enumerate(SUBSETS):
        count = 5 if subset == "fit" else 2
        for detector in range(2):
            for role in range(2):
                for index in range(count):
                    detectors.append(detector); roles.append(role); subsets.append(subset_index)
                    ids.append(f"{subset}-{detector}-{role}-{index}")
    n=len(ids)
    return TrainingArrays(
        strain=np.zeros((n, 4), dtype=np.float32), labels=np.zeros(n, dtype=np.float32),
        detectors=np.asarray(detectors, dtype=np.int8), roles=np.asarray(roles, dtype=np.int8),
        subsets=np.asarray(subsets, dtype=np.int8), identity_ids=tuple(ids),
    )


def test_v7_balanced_batches_retain_final_partial_without_replacement() -> None:
    arrays = _arrays()
    batches = balanced_epoch_batches(arrays, subset="fit", seed=17, epoch=1, batch_per_cell=3)
    assert [len(batch) for batch in batches] == [12, 8]
    flat = np.concatenate(batches)
    assert len(flat) == len(set(flat.tolist())) == 20
    for batch in batches:
        cells = [(arrays.detectors[i], arrays.roles[i]) for i in batch]
        counts = {cell: cells.count(cell) for cell in set(cells)}
        assert len(set(counts.values())) == 1


def test_v7_checkpoint_minimizes_equal_detector_bce_and_keeps_ties_early() -> None:
    first = {"equal_detector_mean_bce": 0.4}
    assert checkpoint_better(first, None)
    assert checkpoint_better({"equal_detector_mean_bce": 0.3}, first)
    assert not checkpoint_better({"equal_detector_mean_bce": 0.4}, first)
