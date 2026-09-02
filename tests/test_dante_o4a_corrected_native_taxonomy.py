from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_taxonomy import (
    assign_historical_family_ids,
    build_taxonomy_rows,
    cluster_primary_mil_vectors,
    load_native_taxonomy_contract,
    validate_native_taxonomy_contract,
)

ROOT = Path(__file__).resolve().parents[1]


def _redigest(contract: dict) -> dict:
    updated = json.loads(json.dumps(contract))
    updated.pop("contract_digest", None)
    updated["contract_digest"] = canonical_json_sha256(updated)
    return updated


def test_native_taxonomy_contract_preserves_v1_morphology() -> None:
    contract = load_native_taxonomy_contract(ROOT)
    taxonomy = contract["taxonomy"]
    assert taxonomy["representation"] == "corrected_primary_scan_mil_v1"
    assert taxonomy["similarity_threshold"] == 0.75
    assert taxonomy["distance_threshold"] == 0.25
    assert taxonomy["linkage"] == "single"
    assert contract["gates"]["exact_total_rows"] == 10942
    assert contract["scientific_boundary"]["native_index_used_for_morphology"] is False


def test_native_taxonomy_contract_rejects_threshold_drift() -> None:
    contract = load_native_taxonomy_contract(ROOT)
    changed = json.loads(json.dumps(contract))
    changed["taxonomy"]["similarity_threshold"] = 0.8
    with pytest.raises(ContractError, match="numerical method changed"):
        validate_native_taxonomy_contract(_redigest(changed), ROOT)


def test_single_linkage_preserves_transitive_v1_families() -> None:
    angle_a = np.deg2rad(0.0)
    angle_b = np.deg2rad(35.0)
    angle_c = np.deg2rad(70.0)
    vectors = np.asarray(
        [
            [np.cos(angle_a), np.sin(angle_a)],
            [np.cos(angle_b), np.sin(angle_b)],
            [np.cos(angle_c), np.sin(angle_c)],
            [-1.0, 0.0],
        ],
        dtype=np.float32,
    )
    labels = cluster_primary_mil_vectors(
        vectors,
        distance_threshold=0.25,
        linkage_method="single",
        criterion="distance",
    )
    assert labels[0] == labels[1] == labels[2]
    assert labels[3] != labels[0]


def test_historical_family_naming_is_deterministic() -> None:
    family_ids, sizes = assign_historical_family_ids(
        [2, 2, 1],
        [("H1", 100.0), ("L1", 200.0), ("H1", 300.0)],
    )
    assert family_ids == ["Family_01", "Family_01", "Singleton_300"]
    assert sizes == [2, 2, 1]


def test_taxonomy_rows_preserve_native_classification() -> None:
    contract = {
        "taxonomy": {
            "representation": "corrected_primary_scan_mil_v1",
            "distance_threshold": 0.25,
            "linkage": "single",
            "flat_cluster_criterion": "distance",
        }
    }
    classified = [
        {"detector": "H1", "gps_start": 1.0, "native_class": "ROBUST"},
        {"detector": "L1", "gps_start": 2.0, "native_class": "BACKGROUND"},
    ]
    rows, metrics = build_taxonomy_rows(
        classified,
        np.asarray([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
        ["a" * 64, "b" * 64],
        contract=contract,
    )
    assert [row["native_class"] for row in rows] == ["ROBUST", "BACKGROUND"]
    assert {row["global_family_id"] for row in rows} == {"Family_01"}
    assert metrics["multi_member_family_count"] == 1
