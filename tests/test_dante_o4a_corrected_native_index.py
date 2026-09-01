from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_corrected_native_index import (
    _read_ledger_context,
    _source_registry,
    _verify_source,
    cluster_native_tokens,
    load_native_index_contract,
    validate_native_index_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_native_index_contract_is_hash_bound_and_inherits_science() -> None:
    contract = load_native_index_contract(ROOT)

    assert contract["contract_digest"] == (
        "a34cea01026355219d7d55750b16a1cf1c5c832f49de6c77f24caa0c57741a90"
    )
    assert contract["parent_native_contract_digest"] == (
        "66f5796aecdea5a1009257a96a351e960c0801eadb60dc40bbf01bdfa74378c2"
    )
    assert contract["clustering"]["centroid_count"] == 1216
    assert contract["gates"]["exact_patch_token_total"] == 1_771_486
    assert contract["scientific_boundary"] == {
        "cohort_changed": False,
        "preprocessing_changed": False,
        "representation_changed": False,
        "clustering_hyperparameters_changed": False,
        "historical_artifacts_immutable": True,
        "detector_identity_inferred": False,
    }


def test_native_index_contract_rejects_clustering_drift() -> None:
    payload = json.loads(
        (ROOT / "config/dante_o4a_corrected_native_index_v1.json").read_text(
            encoding="utf-8"
        )
    )
    payload["clustering"]["centroid_count"] = 1215

    with pytest.raises(ContractError, match="digest mismatch"):
        validate_native_index_contract(payload, ROOT)


def test_source_registry_is_detector_ledger_bound(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    source = raw_root / "session" / "H1_test.hdf5"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"immutable")
    digest = hashlib.sha256(b"immutable").hexdigest()
    context_sources = [
        {
            "relative_path": "session/H1_test.hdf5",
            "block_interval": [100.0, 140.0],
            "used_interval": [104.0, 108.0],
            "sha256": digest,
        }
    ]
    from src.dante_light.contracts import canonical_json_sha256

    rows = [
        {
            "detector": "H1",
            "context_sources": context_sources,
            "context_sources_digest": canonical_json_sha256(context_sources),
        }
    ]

    registry = _source_registry(rows, raw_root)
    assert len(registry) == 1
    verified = _verify_source(registry[0])
    assert verified["sha256"] == digest
    source.write_bytes(b"changed")
    with pytest.raises(ContractError, match="hash mismatch"):
        _verify_source(registry[0])


def test_ledger_context_reader_uses_exact_declared_slice(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    path = raw_root / "session" / "H1_test.hdf5"
    path.parent.mkdir(parents=True)
    values = np.arange(160, dtype=np.float64)
    with h5py.File(path, "w") as handle:
        handle.create_dataset("Strain", data=values)
    row = {
        "detector": "H1",
        "gps_start": 104.0,
        "context_sources": [
            {
                "relative_path": "session/H1_test.hdf5",
                "block_interval": [100.0, 140.0],
                "used_interval": [100.0, 140.0],
                "sha256": "unused-by-slice-reader",
            }
        ],
    }

    series, actual = _read_ledger_context(
        row, raw_root=raw_root, sample_rate_hz=4, pad_s=4.0
    )

    assert float(series.t0.value) == 100.0
    assert actual.shape == (160,)
    assert np.array_equal(actual, values)


def test_frozen_minibatch_clustering_is_deterministic_and_normalized() -> None:
    rng = np.random.default_rng(7)
    tokens = rng.normal(size=(96, 384)).astype(np.float32)
    tokens /= np.linalg.norm(tokens, axis=1, keepdims=True)

    first = cluster_native_tokens(
        tokens,
        centroid_count=8,
        batch_size=32,
        seed=42,
        n_init="auto",
        raw_sample_size=24,
    )
    second = cluster_native_tokens(
        tokens,
        centroid_count=8,
        batch_size=32,
        seed=42,
        n_init="auto",
        raw_sample_size=24,
    )

    assert first[0].shape == (8, 384)
    assert first[1].shape == (24, 384)
    assert np.array_equal(first[0], second[0])
    assert np.array_equal(first[1], second[1])
    assert np.allclose(np.linalg.norm(first[0], axis=1), 1.0, atol=2e-6)
    assert np.allclose(np.linalg.norm(first[1], axis=1), 1.0, atol=2e-6)
