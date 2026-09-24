from __future__ import annotations

import copy
import json
from pathlib import Path
import sqlite3

import numpy as np
import pytest

from src.dante_light import o3a_native_taxonomy as tx
from src.dante_light.contracts import ContractError
from src.dante_light.o4a_corrected_native_taxonomy import (
    assign_historical_family_ids,
    cluster_primary_mil_vectors,
)

ROOT = Path(__file__).resolve().parents[1]


def _classified() -> list[dict]:
    return [
        {
            "detector": detector,
            "gps_start": gps,
            "identity_digest": f"id-{detector}-{gps}",
            "image_sha256": f"image-{detector}-{gps}",
            "native_class": native_class,
            "native_score": score,
        }
        for detector, gps, native_class, score in (
            ("H1", 100.0, "ROBUST", 0.9),
            ("H1", 200.0, "BACKGROUND", 0.1),
            ("L1", 300.0, "AMBIGUOUS", 0.5),
        )
    ]


def _database(path: Path, rows: list[dict], vectors: np.ndarray) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE windows(detector TEXT,gps_start INTEGER,identity_digest TEXT,"
            "image_sha256 TEXT,mil_vector BLOB,is_candidate INTEGER)"
        )
        connection.executemany(
            "INSERT INTO windows VALUES(?,?,?,?,?,1)",
            [
                (
                    row["detector"],
                    int(row["gps_start"]),
                    row["identity_digest"],
                    row["image_sha256"],
                    np.asarray(vector, dtype="<f4").tobytes(),
                )
                for row, vector in zip(rows, vectors, strict=True)
            ],
        )


def _synthetic_contract() -> dict:
    return {
        "contract_digest": "synthetic",
        "taxonomy": {
            "representation": "o3a_primary_scan_mil_v1",
            "population": "all_frozen_o3a_primary_candidates",
            "distance_threshold": 0.25,
            "linkage": "single",
            "flat_cluster_criterion": "distance",
        },
        "parent_primary_scan": {"artifact_digest": "primary"},
        "parent_native_classification": {
            "artifact_digest": "classification",
            "output_sha256": "parent",
        },
        "runtime_environment_digest": "runtime",
        "pre_registered_expectation": {
            "prediction": "SINGLE_LINKAGE_CHAINING_DOMINANT_FAMILY_EXPECTED",
            "acceptance_cutoff": None,
        },
        "gates": {
            "exact_rows_by_detector": {"H1": 2, "L1": 1},
            "exact_total_rows": 3,
            "vector_dim": 2,
            "vector_blob_bytes": 8,
        },
        "scientific_boundary": {"taxonomy_is_not_physical_coincidence": True},
        "output": {
            "summary_filename": "summary.json",
            "taxonomy_filename": "taxonomy.jsonl",
        },
    }


def test_frozen_metadata_registers_parity_and_prediction_without_outcomes():
    contract = tx.build_contract(root=ROOT)
    old = tx.nt._read_json(ROOT / tx.O4A_METHOD_REL)["taxonomy"]
    assert {
        key: value
        for key, value in contract["taxonomy"].items()
        if key not in {"population", "representation"}
    } == {
        key: value
        for key, value in old.items()
        if key not in {"population", "representation"}
    }
    assert contract["taxonomy"]["linkage"] == "single"
    assert contract["taxonomy"]["similarity_threshold"] == 0.75
    assert contract["pre_registered_expectation"]["acceptance_cutoff"] is None
    o4a_receipt = tx.nt._read_json(ROOT / tx.O4A_RECEIPT_REL)
    assert (
        contract["pre_registered_expectation"]["o4a_largest_family"]
        == o4a_receipt["family_metrics"]["max_family_size"]
    )
    assert contract["gates"]["exact_rows_by_detector"] == {"H1": 3624, "L1": 5276}
    assert contract["scientific_boundary"]["global_significance_claim"] is False
    tx.nt._sealed(contract, "contract_digest")


def test_single_linkage_chain_and_historical_naming_match_o4a():
    angles = np.deg2rad([0, 35, 70])
    vectors = np.asarray(
        [[np.cos(a), np.sin(a)] for a in angles] + [[-1.0, 0.0]],
        dtype=np.float32,
    )
    labels = cluster_primary_mil_vectors(
        vectors, distance_threshold=0.25, linkage_method="single", criterion="distance"
    )
    assert labels[0] == labels[1] == labels[2] != labels[3]
    names, sizes = assign_historical_family_ids(
        labels, [("H1", 100.0), ("H1", 200.0), ("L1", 300.0), ("L1", 400.0)]
    )
    assert names[:3] == ["Family_01"] * 3
    assert names[3] == "Singleton_400"
    assert sizes == [3, 3, 3, 1]


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    classified = _classified()
    vectors = np.asarray([[1.0, 0.0], [0.99, 0.01], [-1.0, 0.0]], dtype="<f4")
    database = tmp_path / "primary.sqlite"
    _database(database, classified, vectors)
    contract = _synthetic_contract()
    monkeypatch.setattr(tx, "load_contract", lambda **kwargs: contract)
    monkeypatch.setattr(
        tx,
        "_verified_sources",
        lambda *args, **kwargs: (database, copy.deepcopy(classified)),
    )
    return tmp_path, contract, database, classified


def test_exact_identity_vector_join_preserves_classes_and_scores(synthetic):
    _, contract, database, classified = synthetic
    before = copy.deepcopy(classified)
    bases, vectors, hashes = tx._candidate_rows(database, classified, contract)
    assert bases == classified == before
    assert vectors.shape == (3, 2)
    assert len(hashes) == 3
    result, metrics = tx.build_taxonomy_rows(bases, vectors, hashes, contract=contract)
    assert [row["native_class"] for row in result] == [
        "ROBUST",
        "BACKGROUND",
        "AMBIGUOUS",
    ]
    assert [row["native_score"] for row in result] == [0.9, 0.1, 0.5]
    assert metrics["max_family_size"] == 2


@pytest.mark.parametrize(
    "corruption",
    ["identity", "image", "vector", "duplicate", "prior_label", "missing", "order"],
)
def test_corrupt_or_prior_taxonomy_source_rejected(synthetic, corruption):
    _, contract, database, classified = synthetic
    if corruption == "identity":
        classified[0]["identity_digest"] = "changed"
    elif corruption == "image":
        classified[0]["image_sha256"] = "changed"
    elif corruption == "vector":
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE windows SET mil_vector=NULL WHERE gps_start=100")
    elif corruption == "duplicate":
        classified[1]["gps_start"] = classified[0]["gps_start"]
    elif corruption == "missing":
        classified.pop()
    elif corruption == "order":
        classified[0], classified[1] = classified[1], classified[0]
    else:
        classified[0]["taxonomy"] = "prior"
    with pytest.raises(ContractError):
        tx._candidate_rows(database, classified, contract)


def test_replay_verification_and_compact_receipt(synthetic):
    root, contract, _, _ = synthetic
    summary, directory = tx.execute(root=root, external_root=root / "runs")
    assert not (root / tx.COMPACT_REL).exists()
    verified, _ = tx.execute(root=root, external_root=root / "runs", verify=True)
    assert verified == summary
    receipt = json.loads((root / tx.COMPACT_REL).read_text())
    tx.nt._sealed(receipt, "artifact_digest")
    assert receipt["status"] == "PASS_VERIFIED_O3A_NATIVE_TAXONOMY"
    assert receipt["run_artifact_digest"] == summary["artifact_digest"]
    assert summary["pre_registered_expectation"]["acceptance_cutoff"] is None
    assert summary["family_metrics"]["max_family_size"] == 2
    assert directory.name.startswith("native_taxonomy_")


def test_resealed_summary_or_output_divergence_preserved(synthetic):
    root, contract, _, _ = synthetic
    _, directory = tx.execute(root=root, external_root=root / "runs")
    output = directory / contract["output"]["taxonomy_filename"]
    original = output.read_bytes()
    output.write_bytes(original + b"\n")
    with pytest.raises(ContractError, match="replay changed"):
        tx.execute(root=root, external_root=root / "runs", verify=True)
    assert output.read_bytes() == original + b"\n"
    assert (directory / "failure.json").exists()
    with pytest.raises(ContractError, match="failure requires review"):
        tx.execute(root=root, external_root=root / "runs")


def test_missing_evidence_and_existing_lock(synthetic):
    root, contract, _, _ = synthetic
    with pytest.raises(ContractError, match="evidence missing"):
        tx.execute(root=root, external_root=root / "runs", verify=True)
    directory = tx._run_dir(contract, root / "runs")
    with tx.nt._lock(directory):
        with pytest.raises(ContractError, match="already active"):
            tx.execute(root=root, external_root=root / "runs")


def test_frozen_contract_rejects_resealed_drift(tmp_path, monkeypatch):
    contract = {"contract_digest": "before"}
    monkeypatch.setattr(tx, "build_contract", lambda **kwargs: contract)
    tx.freeze_contract(root=tmp_path)
    assert tx.load_contract(root=tmp_path) == contract
    monkeypatch.setattr(
        tx, "build_contract", lambda **kwargs: {"contract_digest": "after"}
    )
    with pytest.raises(ContractError, match="source changed"):
        tx.load_contract(root=tmp_path)
    with pytest.raises(ContractError):
        tx.freeze_contract(root=tmp_path)


def test_verified_parent_receipts_and_file_hashes_are_required(tmp_path, monkeypatch):
    root = tmp_path
    primary_dir = root / "primary"
    primary_dir.mkdir()
    database = primary_dir / "primary.sqlite"
    database.write_bytes(b"frozen-primary")
    classified_rows = _classified()
    classification_dir = root / "native_classification_synthetic"
    classification_dir.mkdir()
    output = classification_dir / "classified.jsonl"
    tx._atomic_jsonl(output, classified_rows)
    class_summary = {
        "status": "PASS_COMPLETE_O3A_NATIVE_CLASSIFICATION",
        "run_key": "synthetic",
        "output_sha256": tx.file_sha256(output),
        "output_row_digest": tx.canonical_json_sha256(classified_rows),
        "row_total": len(classified_rows),
        "counts_by_detector_and_class": {
            "H1": {"ROBUST": 1, "BACKGROUND": 1},
            "L1": {"AMBIGUOUS": 1},
        },
    }
    class_summary["artifact_digest"] = tx.canonical_json_sha256(class_summary)
    summary_path = classification_dir / "summary.json"
    tx._atomic_json(summary_path, class_summary)
    receipt = {
        "status": "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION",
        "run_artifact_digest": class_summary["artifact_digest"],
        "summary_sha256": tx.file_sha256(summary_path),
    }
    receipt["artifact_digest"] = tx.canonical_json_sha256(receipt)
    tx._atomic_json(root / tx.nc.COMPACT_REL, receipt)
    primary = {
        "artifact_digest": "primary-digest",
        "database": {"filename": database.name, "sha256": tx.file_sha256(database)},
        "candidate_counts": {"H1": 2, "L1": 1},
    }
    monkeypatch.setattr(
        tx.ps, "verify_primary_scan", lambda **kwargs: (primary, primary_dir)
    )
    monkeypatch.setattr(
        tx.nc,
        "load_contract",
        lambda **kwargs: {
            "output": {
                "summary_filename": "summary.json",
                "candidate_filename": output.name,
            }
        },
    )
    monkeypatch.setattr(tx.nc, "_run_dir", lambda *args: classification_dir)
    contract = {
        "parent_primary_scan": primary,
        "parent_native_classification": {
            "artifact_digest": receipt["artifact_digest"],
            "run_key": "synthetic",
            "run_artifact_digest": class_summary["artifact_digest"],
            "summary_sha256": tx.file_sha256(summary_path),
            "output_sha256": tx.file_sha256(output),
            "output_row_digest": class_summary["output_row_digest"],
            "row_total": 3,
            "counts_by_detector_and_class": class_summary[
                "counts_by_detector_and_class"
            ],
        },
    }
    path, rows = tx._verified_sources(contract, root=root, external_root=root)
    assert path == database and rows == classified_rows
    output.write_bytes(output.read_bytes() + b"\n")
    with pytest.raises(ContractError, match="parent file changed"):
        tx._verified_sources(contract, root=root, external_root=root)
