from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_native_index import (
    _read_shard,
    _write_shard,
    build_index_contract,
    load_index_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_o3a_index_contract_binds_frozen_cohort_and_method() -> None:
    contract = load_index_contract(root=ROOT)
    assert contract == build_index_contract(root=ROOT)
    assert contract["gates"]["exact_cohort_rows"] == 1294
    assert contract["gates"]["exact_patch_token_total"] == 1_771_486
    assert contract["clustering"]["centroid_count"] == 1216
    assert contract["clustering"]["raw_embedding_sample_size"] == 50_000
    assert contract["execution"]["token_order"] == "FROZEN_COHORT_LEDGER_ORDER"
    assert contract["storage"]["full_raw_frame_archive_required"] is False
    assert contract["preprocessing"]["raw_context_hash_replay"] is True
    assert contract["preprocessing"]["clean_window_hash_replay"] is True


def test_token_shard_resume_verifies_hash_and_identity(tmp_path: Path) -> None:
    contract = {
        "contract_digest": "frozen",
        "representation": {"patch_tokens_per_image": 3, "embedding_dimension": 2},
    }
    row = {
        "detector": "H1",
        "gps_start": 100,
        "identity_digest": "identity",
        "cohort_detector_index": 0,
        "clean_window_sha256": "clean",
        "raw_context": {"values_sha256": "raw"},
        "context_sources_digest": "sources",
    }
    values = np.asarray([[1, 0], [0, 1], [0.6, 0.8]], dtype=np.float32)
    replay = {
        "detector": "H1",
        "gps_start": 100,
        "identity_digest": "identity",
        "cohort_detector_index": 0,
        "clean_window_sha256": "clean",
        "raw_context_values_sha256": "raw",
        "context_sources_digest": "sources",
    }
    _write_shard(
        run_dir=tmp_path,
        position=0,
        row=row,
        replay=replay,
        values=values,
        contract=contract,
    )
    read = _read_shard(run_dir=tmp_path, position=0, row=row, contract=contract)
    assert read is not None
    assert np.array_equal(read[0], values)
    assert read[1]["replay"] == replay
    with pytest.raises(ContractError, match="overwrite"):
        _write_shard(
            run_dir=tmp_path,
            position=0,
            row=row,
            replay=replay,
            values=values,
            contract=contract,
        )
    with pytest.raises(ContractError, match="changed"):
        _read_shard(
            run_dir=tmp_path,
            position=0,
            row={**row, "gps_start": 101},
            contract=contract,
        )
    token_path = tmp_path / "tokens" / "0000.npy"
    token_path.write_bytes(token_path.read_bytes() + b"tamper")
    with pytest.raises(ContractError, match="changed"):
        _read_shard(run_dir=tmp_path, position=0, row=row, contract=contract)


def test_index_contract_rejects_local_drift(tmp_path: Path) -> None:
    contract = load_index_contract(root=ROOT)
    target = tmp_path / "config" / "dante_o3a_native_index_v1.json"
    target.parent.mkdir()
    target.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises((FileNotFoundError, ContractError)):
        load_index_contract(root=tmp_path)
