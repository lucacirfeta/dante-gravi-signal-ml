from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

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
from src.dante_light.prefilter_v7_verification import (
    _portable_reference_matches,
    load_training_authorization_for_verification,
)


def test_v7_authorization_is_training_only_and_digest_closed() -> None:
    receipt = load_training_authorization_for_verification(
        DEFAULT_AUTHORIZATION, root=Path(__file__).resolve().parents[1]
    )
    assert receipt["allowed"]["partition"] == "training"
    assert receipt["forbidden"] == {
        "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
        "routing": False, "member_selection": False, "second_stage_distillation": False,
    }


def test_v7_verification_accepts_only_line_ending_equivalence(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=tmp_path,
        check=True,
    )
    path = tmp_path / "sample.py"
    path.write_bytes(b"a=1\nb=2\n")
    subprocess.run(["git", "add", "sample.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=tmp_path, check=True)
    crlf_reference = {
        "path": "sample.py",
        "sha256": hashlib.sha256(b"a=1\r\nb=2\r\n").hexdigest(),
    }
    basis = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    bridge_entry = {
        "path": "sample.py",
        "legacy_checkout_sha256": crlf_reference["sha256"],
        "basis_blob_sha256": hashlib.sha256(b"a=1\nb=2\n").hexdigest(),
        "normalized_lf_sha256": hashlib.sha256(b"a=1\nb=2\n").hexdigest(),
    }
    assert _portable_reference_matches(
        tmp_path,
        crlf_reference,
        "fixture",
        bridge_entry=bridge_entry,
        basis_commit=basis,
    ) == path

    path.write_bytes(b"a=1\nb=3\n")
    with pytest.raises(ContractError, match="hash mismatch"):
        _portable_reference_matches(
            tmp_path,
            crlf_reference,
            "fixture",
            bridge_entry=bridge_entry,
            basis_commit=basis,
        )


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
