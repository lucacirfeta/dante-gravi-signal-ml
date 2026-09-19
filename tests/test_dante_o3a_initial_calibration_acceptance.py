from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_initial_calibration_acceptance import (
    RawSliceReader,
    load_acceptance_contract,
    score_prepared_rows,
    validate_acceptance_contract,
    validate_block_shard,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeScorer:
    def __init__(self, *, finite_tokens: bool = True) -> None:
        self.finite_tokens = finite_tokens

    def encode_patch_tokens(self, images: list[np.ndarray]) -> np.ndarray:
        value = 1.0 if self.finite_tokens else np.nan
        return np.full((len(images), 2, 3), value, dtype=np.float32)

    def score_patch_tokens(
        self, tokens: np.ndarray, threshold: float, *, output_mode: str
    ) -> list[dict[str, float | bool]]:
        assert threshold == 1.0
        assert output_mode == "score_only"
        return [
            {"novelty_score": float(index - 4), "is_novel": False}
            for index in range(len(tokens))
        ]


def _prepared_rows() -> list[dict[str, object]]:
    return [
        {
            "detector": "H1",
            "analysis_gps_start": 1000 + 64 * index,
            "context_interval_gps": [996 + 64 * index, 1036 + 64 * index],
            "raw_sources": [{"relative_path": "H1/raw.hdf5"}],
            "image": np.full((256, 256, 3), index, dtype=np.uint8),
        }
        for index in range(17)
    ]


def test_frozen_contract_binds_verified_raw_and_disables_downstream_science() -> None:
    value = load_acceptance_contract(root=ROOT)
    assert value["verified_raw_input"]["download_run_key"] == (
        "b6f43f84cde717eed478947ac4fccaa0f6fd5f5b16fc2740521fcca5f94b9f9f"
    )
    assert value["verified_raw_input"]["manifest_sha256"] == (
        "9a60a2990cdee999e48d919bf20adf2ae5c5decd5a954440bd682c2ced7a6926"
    )
    assert value["method_parity"]["top_k"] == 68
    assert value["population"] == {
        "provisional_block_count": 590,
        "blocks_per_detector": 295,
        "candidate_rows_per_block": 17,
        "evaluated_rows_per_detector": 5_015,
        "point_estimate_rows_per_detector": 5_000,
        "bootstrap_rows_per_detector": 4_998,
        "point_only_tail_rows_per_detector": 2,
    }
    assert value["scientific_boundary"]["threshold_fitting_allowed"] is False
    assert value["scientific_boundary"]["classification_allowed"] is False
    assert value["scientific_boundary"]["native_index_selection_allowed"] is False
    assert value["acceptance"][
        "score_value_or_class_may_affect_acceptance"
    ] is False


def test_contract_rejects_scientific_boundary_drift() -> None:
    value = load_acceptance_contract(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["method_parity"]["top_k"] = 1
    body = {key: item for key, item in mutated.items() if key != "contract_digest"}
    mutated["contract_digest"] = canonical_json_sha256(body)
    with pytest.raises(ContractError, match="scientific boundary mismatch"):
        validate_acceptance_contract(mutated, root=ROOT)


def test_complete_block_scoring_does_not_gate_on_score_magnitude() -> None:
    rows = score_prepared_rows(
        _prepared_rows(), scorer=FakeScorer(), batch_size=8
    )
    assert len(rows) == 17
    assert [row["analysis_gps_start"] for row in rows] == [
        1000 + 64 * index for index in range(17)
    ]
    assert any(float(row["primary_score"]) < 0 for row in rows)
    assert any(float(row["primary_score"]) > 0 for row in rows)
    assert all(len(str(row["primary_score_float32_hex"])) == 8 for row in rows)


def test_block_scoring_rejects_nonfinite_tokens_and_partial_blocks() -> None:
    with pytest.raises(ContractError, match="exactly 17"):
        score_prepared_rows(
            _prepared_rows()[:-1], scorer=FakeScorer(), batch_size=8
        )
    with pytest.raises(ContractError, match="tokens are non-finite"):
        score_prepared_rows(
            _prepared_rows(),
            scorer=FakeScorer(finite_tokens=False),
            batch_size=8,
        )


def test_block_shard_validation_is_atomic() -> None:
    identity = {
        "detector": "H1",
        "stratum_index": 0,
        "candidate_rank_in_stratum": 0,
        "selection_priority_sha256": "a" * 64,
        "analysis_gps_starts": [1000 + 64 * index for index in range(17)],
        "output_row_count": 17,
    }
    rows = score_prepared_rows(
        _prepared_rows(), scorer=FakeScorer(), batch_size=8
    )
    body = {
        "schema_version": 1,
        "status": "PASS_BLOCK_ATOMIC_ACCEPTANCE",
        "run_key": "run",
        "block_identity": identity,
        "rows": rows,
        "failures": [],
        "score_value_or_class_used_for_acceptance": False,
        "threshold_fitted": False,
    }
    value = {**body, "shard_digest": canonical_json_sha256(body)}
    assert validate_block_shard(
        value, run_key="run", identity=identity
    )["status"] == "PASS_BLOCK_ATOMIC_ACCEPTANCE"

    partial = copy.deepcopy(value)
    partial["rows"].pop()
    partial_body = {
        key: item for key, item in partial.items() if key != "shard_digest"
    }
    partial["shard_digest"] = canonical_json_sha256(partial_body)
    with pytest.raises(ContractError, match="accepted block shard is invalid"):
        validate_block_shard(partial, run_key="run", identity=identity)


def _write_frame(path: Path, values: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as handle:
        dataset = handle.create_dataset("strain/Strain", data=values)
        dataset.attrs["Xspacing"] = 1.0 / 4096
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_raw_slice_reader_stitches_exact_manifest_bound_context(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    first = raw_root / "H1" / "first.hdf5"
    second = raw_root / "H1" / "second.hdf5"
    first_hash = _write_frame(first, np.arange(4096, dtype=np.float64))
    second_hash = _write_frame(second, np.arange(4096, dtype=np.float64) + 4096)
    manifest = tmp_path / "manifest.jsonl"
    rows = [
        {
            "detector": "H1",
            "gps_start": index,
            "gps_end": index + 1,
            "sha256": digest,
            "physical_copies": [
                {
                    "relative_path": f"H1/{name}",
                    "sha256": digest,
                    "size_bytes": path.stat().st_size,
                }
            ],
        }
        for index, digest, name, path in (
            (0, first_hash, "first.hdf5", first),
            (1, second_hash, "second.hdf5", second),
        )
    ]
    manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    reader = RawSliceReader(
        manifest_path=manifest, raw_root=raw_root, detectors=("H1",)
    )
    values, sources = reader.read(detector="H1", start=0.5, end=1.5)
    assert values.shape == (4096,)
    assert np.array_equal(values[:2048], np.arange(2048, 4096))
    assert np.array_equal(values[2048:], np.arange(4096, 6144))
    assert [source["relative_path"] for source in sources] == [
        "H1/first.hdf5",
        "H1/second.hdf5",
    ]
