"""Replay the frozen O4a morphology-family method on O3a candidates."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.dante_light import o3a_native_classification as nc
from src.dante_light import o3a_native_thresholds as nt
from src.dante_light import o3a_primary_scan as ps
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_calibration_cohort import _atomic_json, _atomic_jsonl
from src.dante_light.o3a_native_contract import ROOT, RUNTIME_REL, load_runtime_contract
from src.dante_light.o3a_native_rescore import DEFAULT_EXTERNAL_ROOT
from src.dante_light.o3a_raw_download import file_sha256
from src.dante_light.o4a_corrected_native_taxonomy import (
    build_taxonomy_rows,
    _load_primary_mil_rows,
)

CONTRACT_REL = "config/dante_o3a_native_taxonomy_v1.json"
COMPACT_REL = "artifacts/dante_light/o3a_native_v1/native_taxonomy.json"
O4A_METHOD_REL = "config/dante_o4a_corrected_native_taxonomy_v1.json"
O4A_RECEIPT_REL = "artifacts/dante_light/o4a_v1_parity/corrected_native_taxonomy.json"
PRIMARY_RECEIPT_REL = "artifacts/dante_light/o3a_native_v1/primary_scan.json"
SOURCE_PATHS = (
    "src/dante_light/o3a_native_taxonomy.py",
    "scripts/run_dante_o3a_native_taxonomy.py",
    "tests/test_dante_o3a_native_taxonomy.py",
    "src/dante_light/o4a_corrected_native_taxonomy.py",
)


def build_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Bind verified parent metadata, before opening O3a morphology outcomes."""
    primary_contract = ps.load_scan_contract(root=root)
    class_contract = nc.load_contract(root=root)
    primary = nt._read_json(root / PRIMARY_RECEIPT_REL)
    classified = nt._read_json(root / nc.COMPACT_REL)
    nt._sealed(primary, "artifact_digest")
    nt._sealed(classified, "artifact_digest")
    o4a_method = nt._read_json(root / O4A_METHOD_REL)
    o4a_receipt = nt._read_json(root / O4A_RECEIPT_REL)
    nt._sealed(o4a_method, "contract_digest")
    nt._sealed(o4a_receipt, "artifact_digest")
    if (
        primary.get("status") != "PASS_COMPLETE_O3A_PRIMARY_SCAN"
        or primary.get("contract_digest") != primary_contract["contract_digest"]
        or classified.get("status") != "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION"
        or classified.get("contract_digest") != class_contract["contract_digest"]
        or primary.get("candidate_counts")
        != class_contract["population"]["rows_by_detector"]
        or classified.get("row_total") != primary.get("candidate_total")
        or set(classified["counts_by_detector_and_class"])
        != set(primary["candidate_counts"])
        or any(
            sum(classified["counts_by_detector_and_class"][detector].values()) != count
            for detector, count in primary["candidate_counts"].items()
        )
    ):
        raise ContractError("O3a taxonomy parents or populations changed")
    old = o4a_method["taxonomy"]
    if (
        o4a_receipt.get("status") != "PASS_VERIFIED_NATIVE_TAXONOMY_V1"
        or o4a_receipt.get("taxonomy") != old
        or o4a_receipt.get("contract_digest") != o4a_method["contract_digest"]
        or old.get("representation") != "corrected_primary_scan_mil_v1"
        or old.get("population") != "all_corrected_primary_candidates"
        or o4a_receipt["family_metrics"]["max_family_size"]
        > o4a_receipt["output"]["row_total"]
    ):
        raise ContractError("O4a taxonomy parity precedent changed")
    method = {
        **old,
        "representation": "o3a_primary_scan_mil_v1",
        "population": "all_frozen_o3a_primary_candidates",
    }
    runtime = load_runtime_contract(root=root)
    refs = (
        ps.CONTRACT_REL,
        nc.CONTRACT_REL,
        PRIMARY_RECEIPT_REL,
        nc.COMPACT_REL,
        O4A_METHOD_REL,
        O4A_RECEIPT_REL,
        RUNTIME_REL,
    )
    body = {
        "schema_version": 1,
        "status": "FROZEN_O3A_NATIVE_TAXONOMY_V1",
        "run": "O3A",
        "taxonomy": method,
        "parent_primary_scan": {
            key: primary[key]
            for key in (
                "artifact_digest",
                "contract_digest",
                "run_key",
                "database",
                "candidate_counts",
                "candidate_total",
            )
        },
        "parent_native_classification": {
            key: classified[key]
            for key in (
                "artifact_digest",
                "contract_digest",
                "run_key",
                "run_artifact_digest",
                "summary_sha256",
                "output_sha256",
                "output_row_digest",
                "row_total",
                "counts_by_detector_and_class",
            )
        },
        "o4a_method_precedent": {
            "contract_digest": o4a_method["contract_digest"],
            "receipt_digest": o4a_receipt["artifact_digest"],
        },
        "pre_registered_expectation": {
            "prediction": "SINGLE_LINKAGE_CHAINING_DOMINANT_FAMILY_EXPECTED",
            "o4a_largest_family": o4a_receipt["family_metrics"]["max_family_size"],
            "o4a_total": o4a_receipt["output"]["row_total"],
            "acceptance_cutoff": None,
            "discrepancy_policy": "REPORT_WITHOUT_RETUNING_METHOD",
        },
        "gates": {
            "exact_rows_by_detector": primary["candidate_counts"],
            "exact_total_rows": primary["candidate_total"],
            "vector_dim": method["vector_dim"],
            "vector_blob_bytes": method["vector_dim"] * 4,
            "exact_detector_gps_join": True,
            "exact_identity_digest_join": True,
            "exact_image_sha256_join": True,
            "zero_duplicate_detector_gps": True,
            "zero_missing_or_invalid_mil_vectors": True,
            "zero_prior_taxonomy_use": True,
            "primary_scores_not_used_for_taxonomy": True,
            "parent_verifier_reads_primary_scores_for_integrity": True,
            "full_replay_verification": True,
        },
        "scientific_boundary": {
            "o4a_scientific_rows_imported": False,
            "candidate_population_changed": False,
            "native_scores_or_classes_changed": False,
            "morphology_representation_recomputed": False,
            "native_index_used_for_morphology": False,
            "taxonomy_is_not_physical_coincidence": True,
            "coincidence_performed": False,
            "pem_performed": False,
            "multiscale_used": False,
            "global_significance_claim": False,
        },
        "runtime_environment_digest": runtime["runtime_environment"][
            "environment_digest"
        ],
        "references": {p: file_sha256(root / p) for p in refs},
        "implementation_sources": {p: file_sha256(root / p) for p in SOURCE_PATHS},
        "output": {
            "summary_filename": "native_taxonomy_summary.json",
            "taxonomy_filename": "native_taxonomy.jsonl",
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def freeze_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def load_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = nt._read_json(root / CONTRACT_REL)
    if value != build_contract(root=root):
        raise ContractError("O3a taxonomy frozen contract or source changed")
    return value


def _run_dir(contract: Mapping[str, Any], external_root: Path) -> Path:
    key = canonical_json_sha256(
        {
            "stage": "o3a_native_taxonomy_v1",
            "contract_digest": contract["contract_digest"],
            "primary_scan_artifact_digest": contract["parent_primary_scan"][
                "artifact_digest"
            ],
            "native_classification_artifact_digest": contract[
                "parent_native_classification"
            ]["artifact_digest"],
            "runtime_environment_digest": contract["runtime_environment_digest"],
        }
    )
    return external_root.resolve() / f"native_taxonomy_{key}"


def _verified_sources(
    contract: Mapping[str, Any], *, root: Path, external_root: Path
) -> tuple[Path, list[dict[str, Any]]]:
    primary, primary_dir = ps.verify_primary_scan(
        root=root, external_root=external_root
    )
    classification_contract = nc.load_contract(root=root)
    classification_dir = nc._run_dir(classification_contract, external_root)
    if (classification_dir / "failure.json").is_file():
        raise ContractError("O3a taxonomy classification parent has failure evidence")
    classification_summary_path = (
        classification_dir / classification_contract["output"]["summary_filename"]
    )
    classified = nt._read_json(classification_summary_path)
    nt._sealed(classified, "artifact_digest")
    classification_receipt = nt._read_json(root / nc.COMPACT_REL)
    nt._sealed(classification_receipt, "artifact_digest")
    expected_primary = contract["parent_primary_scan"]
    expected_classification = contract["parent_native_classification"]
    if (
        primary["artifact_digest"] != expected_primary["artifact_digest"]
        or primary["database"] != expected_primary["database"]
        or primary["candidate_counts"] != expected_primary["candidate_counts"]
        or classification_receipt["artifact_digest"]
        != expected_classification["artifact_digest"]
        or classification_dir.name
        != f"native_classification_{expected_classification['run_key']}"
        or classification_receipt["status"] != "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION"
        or classification_receipt["run_artifact_digest"]
        != expected_classification["run_artifact_digest"]
        or classified["status"] != "PASS_COMPLETE_O3A_NATIVE_CLASSIFICATION"
        or classified["run_key"] != expected_classification["run_key"]
        or classified["artifact_digest"]
        != expected_classification["run_artifact_digest"]
        or file_sha256(classification_summary_path)
        != expected_classification["summary_sha256"]
        or classification_receipt["summary_sha256"]
        != expected_classification["summary_sha256"]
        or classified["output_sha256"] != expected_classification["output_sha256"]
        or classified["output_row_digest"]
        != expected_classification["output_row_digest"]
        or classified["row_total"] != expected_classification["row_total"]
        or classified["counts_by_detector_and_class"]
        != expected_classification["counts_by_detector_and_class"]
    ):
        raise ContractError("O3a taxonomy verified parent changed")
    database_path = primary_dir / expected_primary["database"]["filename"]
    classification_path = (
        classification_dir / classification_contract["output"]["candidate_filename"]
    )
    if (
        file_sha256(database_path) != expected_primary["database"]["sha256"]
        or file_sha256(classification_path) != expected_classification["output_sha256"]
    ):
        raise ContractError("O3a taxonomy parent file changed")
    rows = [
        json.loads(line)
        for line in classification_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if canonical_json_sha256(rows) != expected_classification["output_row_digest"]:
        raise ContractError("O3a taxonomy classified row digest changed")
    return database_path, rows


def _candidate_rows(
    database_path: Path,
    classified_rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
):
    # The O4a loader reads only identity/image fields and MIL vectors, not scores.
    return _load_primary_mil_rows(
        database_path, classified_rows=classified_rows, contract=contract
    )


def _rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            (
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def execute(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    verify: bool = False,
) -> tuple[dict[str, Any], Path]:
    contract = load_contract(root=root)
    directory = _run_dir(contract, external_root)
    with nt._lock(directory):
        failure = directory / "failure.json"
        summary_path = directory / contract["output"]["summary_filename"]
        output_path = directory / contract["output"]["taxonomy_filename"]
        if failure.exists():
            raise ContractError("O3a taxonomy failure requires review")
        if verify and (not summary_path.exists() or not output_path.exists()):
            raise ContractError("O3a taxonomy evidence missing")
        try:
            database_path, classified_rows = _verified_sources(
                contract, root=root, external_root=external_root
            )
            bases, vectors, vector_hashes = _candidate_rows(
                database_path, classified_rows, contract
            )
            rows, metrics = build_taxonomy_rows(
                bases, vectors, vector_hashes, contract=contract
            )
            family_ids = [row["global_family_id"] for row in rows]
            singleton_ids = [
                row["global_family_id"]
                for row in rows
                if row["morphology_family_size"] == 1
            ]
            if len(singleton_ids) != len(set(singleton_ids)):
                raise ContractError("O3a taxonomy historical singleton IDs collide")
            expected_sha = _rows_sha256(rows)
            if output_path.exists():
                if file_sha256(output_path) != expected_sha:
                    raise ContractError("O3a taxonomy output replay changed")
            else:
                _atomic_jsonl(output_path, rows)
            if file_sha256(output_path) != expected_sha:
                raise ContractError("O3a taxonomy output write changed")
            body = {
                "schema_version": 1,
                "status": "PASS_COMPLETE_O3A_NATIVE_TAXONOMY",
                "contract_digest": contract["contract_digest"],
                "run_key": directory.name.removeprefix("native_taxonomy_"),
                "runtime_environment_digest": contract["runtime_environment_digest"],
                "parent_primary_scan_artifact_digest": contract["parent_primary_scan"][
                    "artifact_digest"
                ],
                "parent_native_classification_artifact_digest": contract[
                    "parent_native_classification"
                ]["artifact_digest"],
                "taxonomy": contract["taxonomy"],
                "pre_registered_expectation": contract["pre_registered_expectation"],
                "row_total": len(rows),
                "counts_by_detector": dict(
                    sorted(Counter(r["detector"] for r in rows).items())
                ),
                "counts_by_native_class": dict(
                    sorted(Counter(r["native_class"] for r in rows).items())
                ),
                "family_metrics": metrics,
                "largest_family_fraction": metrics["max_family_size"] / len(rows),
                "family_id_count": len(set(family_ids)),
                "source_database_sha256": file_sha256(database_path),
                "source_classification_sha256": contract[
                    "parent_native_classification"
                ]["output_sha256"],
                "output_sha256": expected_sha,
                "output_row_digest": canonical_json_sha256(rows),
                "scientific_boundary": contract["scientific_boundary"],
            }
            summary = {**body, "artifact_digest": canonical_json_sha256(body)}
            if summary_path.exists() and nt._read_json(summary_path) != summary:
                raise ContractError("O3a taxonomy summary replay changed")
            _atomic_json(summary_path, summary)
            if verify:
                compact = {
                    **body,
                    "status": "PASS_VERIFIED_O3A_NATIVE_TAXONOMY",
                    "external_run_dir_wsl": str(directory),
                    "run_artifact_digest": summary["artifact_digest"],
                    "summary_sha256": file_sha256(summary_path),
                }
                _atomic_json(
                    root / COMPACT_REL,
                    {**compact, "artifact_digest": canonical_json_sha256(compact)},
                )
            return summary, directory
        except BaseException as exc:
            body = {
                "status": "FAILED_O3A_NATIVE_TAXONOMY",
                "contract_digest": contract["contract_digest"],
                "run_key": directory.name.removeprefix("native_taxonomy_"),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            _atomic_json(
                failure, {**body, "artifact_digest": canonical_json_sha256(body)}
            )
            raise
