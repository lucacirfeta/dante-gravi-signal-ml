"""Build the corrected O4a morphology taxonomy with the frozen v1 MIL view."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from scipy.cluster import hierarchy
from scipy.spatial.distance import squareform
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore import _atomic_json, _atomic_jsonl
from src.dante_light.o4a_corrected_native_rescore_v2 import _load_jsonl
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.prefilter_v5_protocol import sha256_path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_taxonomy_v1.json")
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_native_taxonomy_v1"
)
SCHEMA_VERSION = 1


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def validate_native_taxonomy_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("corrected native-taxonomy contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("corrected native-taxonomy schema changed")

    taxonomy = value.get("taxonomy", {})
    required_method = {
        "representation": "corrected_primary_scan_mil_v1",
        "population": "all_corrected_primary_candidates",
        "vector_dtype": "float32_little_endian",
        "normalization": "l2_per_vector",
        "similarity": "cosine_similarity",
        "linkage": "single",
        "flat_cluster_criterion": "distance",
        "family_naming": "scipy_label_order_multi_member_then_historical_singleton_gps",
        "family_template": "Family_{ordinal:02d}",
        "singleton_template": "Singleton_{gps_integer}",
    }
    if any(taxonomy.get(key) != expected for key, expected in required_method.items()):
        raise ContractError("corrected native-taxonomy method changed")
    vector_dim = int(taxonomy.get("vector_dim", -1))
    similarity_threshold = float(taxonomy.get("similarity_threshold", np.nan))
    distance_threshold = float(taxonomy.get("distance_threshold", np.nan))
    if (
        vector_dim <= 0
        or not np.isfinite([similarity_threshold, distance_threshold]).all()
        or not 0.0 < similarity_threshold < 1.0
        or distance_threshold != 1.0 - similarity_threshold
    ):
        raise ContractError("corrected native-taxonomy numerical method changed")

    boundary = value.get("scientific_boundary")
    if boundary != {
        "candidate_population_changed": False,
        "native_scores_or_classes_changed": False,
        "morphology_representation_recomputed": False,
        "morphology_representation_source": "corrected primary scan MIL vectors",
        "native_index_used_for_morphology": False,
        "historical_v1_family_definition_preserved": True,
        "taxonomy_is_not_physical_coincidence": True,
        "coincidence_performed_in_this_stage": False,
        "pem_performed_in_this_stage": False,
        "historical_artifacts_immutable": True,
    }:
        raise ContractError("corrected native-taxonomy boundary changed")

    references = value.get("references", {})
    for reference in references.values():
        path = (root / str(reference["path"])).resolve()
        if not path.is_file() or sha256_path(path) != reference["sha256"]:
            raise ContractError(f"corrected native-taxonomy reference changed: {path}")

    scan_artifact = _read_json(root / str(references["primary_scan"]["path"]))
    classification_artifact = _read_json(
        root / str(references["native_classification"]["path"])
    )
    if value.get("parent_primary_scan") != {
        "compact_artifact_digest": scan_artifact.get("artifact_digest"),
        "run_key": scan_artifact.get("run_key"),
        "database_filename": scan_artifact.get("database", {}).get("filename"),
        "database_sha256": scan_artifact.get("database", {}).get("sha256"),
        "candidate_counts": scan_artifact.get("candidate_counts"),
        "candidate_total": scan_artifact.get("candidate_total"),
    }:
        raise ContractError("corrected native-taxonomy primary parent changed")
    if value.get("parent_native_classification") != {
        "compact_artifact_digest": classification_artifact.get("artifact_digest"),
        "run_artifact_digest": classification_artifact.get("external_artifact_digest"),
        "contract_digest": classification_artifact.get("contract_digest"),
        "run_key": classification_artifact.get("external_run", {}).get("run_key"),
        "summary_sha256": classification_artifact.get("external_run", {}).get(
            "summary_sha256"
        ),
        "output_filename": classification_artifact.get("output", {}).get("filename"),
        "output_sha256": classification_artifact.get("output", {}).get("sha256"),
        "output_row_digest": classification_artifact.get("output", {}).get(
            "row_digest"
        ),
        "counts_by_detector_and_class": classification_artifact.get(
            "counts_by_detector_and_class"
        ),
    }:
        raise ContractError("corrected native-taxonomy classification parent changed")

    gates = value.get("gates", {})
    expected_counts = {
        detector: int(count)
        for detector, count in scan_artifact["candidate_counts"].items()
    }
    if (
        gates.get("exact_rows_by_detector") != expected_counts
        or int(gates.get("exact_total_rows", -1)) != sum(expected_counts.values())
        or int(gates.get("vector_dim", -1)) != vector_dim
        or int(gates.get("vector_blob_bytes", -1))
        != vector_dim * np.dtype("<f4").itemsize
        or any(
            gates.get(name) is not True
            for name in (
                "fail_closed",
                "exact_detector_gps_join",
                "exact_identity_digest_join",
                "exact_image_sha256_join",
                "zero_duplicate_detector_gps",
                "zero_missing_or_invalid_mil_vectors",
                "zero_prior_taxonomy_use",
                "primary_scores_unread",
                "full_replay_verification",
            )
        )
    ):
        raise ContractError("corrected native-taxonomy gates changed")
    return {"contract_digest": digest, **value}


def load_native_taxonomy_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_native_taxonomy_contract(_read_json(root / CONTRACT_REL), root=root)


def cluster_primary_mil_vectors(
    vectors: np.ndarray,
    *,
    distance_threshold: float,
    linkage_method: str,
    criterion: str,
) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if (
        matrix.ndim != 2
        or matrix.shape[0] < 2
        or not np.isfinite(matrix).all()
        or np.any(np.linalg.norm(matrix, axis=1) == 0.0)
    ):
        raise ContractError("corrected native-taxonomy MIL matrix is invalid")
    normalized = normalize(matrix, norm="l2", axis=1)
    similarity = cosine_similarity(normalized)
    distance = 1.0 - similarity
    distance = np.clip((distance + distance.T) / 2.0, 0.0, None)
    np.fill_diagonal(distance, 0.0)
    condensed = squareform(distance)
    linkage_matrix = hierarchy.linkage(condensed, method=linkage_method)
    labels = hierarchy.fcluster(
        linkage_matrix,
        t=float(distance_threshold),
        criterion=criterion,
    )
    return np.asarray(labels, dtype=np.int64)


def assign_historical_family_ids(
    labels: Sequence[int], identities: Sequence[tuple[str, float]]
) -> tuple[list[str], list[int]]:
    if len(labels) != len(identities):
        raise ContractError("corrected native-taxonomy labels changed length")
    counts = Counter(int(label) for label in labels)
    family_map: dict[int, str] = {}
    family_ordinal = 1
    for label in sorted(counts):
        if counts[label] > 1:
            family_map[label] = f"Family_{family_ordinal:02d}"
            family_ordinal += 1
        else:
            family_map[label] = "Singleton"
    family_ids: list[str] = []
    family_sizes: list[int] = []
    for label, (_detector, gps_start) in zip(labels, identities, strict=True):
        numeric_label = int(label)
        family_id = family_map[numeric_label]
        if family_id == "Singleton":
            family_id = f"Singleton_{int(gps_start)}"
        family_ids.append(family_id)
        family_sizes.append(int(counts[numeric_label]))
    return family_ids, family_sizes


def _primary_database_path(
    contract: Mapping[str, Any], primary_external_root: Path
) -> Path:
    parent = contract["parent_primary_scan"]
    return (
        primary_external_root
        / f"primary_scan_{parent['run_key']}"
        / str(parent["database_filename"])
    )


def _classification_paths(
    contract: Mapping[str, Any], classification_external_root: Path
) -> tuple[Path, Path]:
    parent = contract["parent_native_classification"]
    run_dir = (
        classification_external_root / f"native_classification_{parent['run_key']}"
    )
    return run_dir / "native_classification_summary.json", run_dir / str(
        parent["output_filename"]
    )


def _verified_sources(
    *,
    contract: Mapping[str, Any],
    primary_external_root: Path,
    classification_external_root: Path,
) -> tuple[Path, Path, list[dict[str, Any]]]:
    database_path = _primary_database_path(contract, primary_external_root)
    classification_summary_path, classification_path = _classification_paths(
        contract, classification_external_root
    )
    parent_scan = contract["parent_primary_scan"]
    parent_classification = contract["parent_native_classification"]
    if (
        not database_path.is_file()
        or sha256_file(database_path) != parent_scan["database_sha256"]
        or not classification_summary_path.is_file()
        or sha256_file(classification_summary_path)
        != parent_classification["summary_sha256"]
        or not classification_path.is_file()
        or sha256_file(classification_path) != parent_classification["output_sha256"]
    ):
        raise ContractError("corrected native-taxonomy parent file changed")
    classification_summary = _read_json(classification_summary_path)
    if (
        classification_summary.get("artifact_digest")
        != parent_classification["run_artifact_digest"]
        or classification_summary.get("contract_digest")
        != parent_classification["contract_digest"]
    ):
        raise ContractError("corrected native-taxonomy classification summary changed")
    classified_rows = _load_jsonl(classification_path)
    if (
        canonical_json_sha256(classified_rows)
        != parent_classification["output_row_digest"]
    ):
        raise ContractError("corrected native-taxonomy classified rows changed")
    return database_path, classification_path, classified_rows


def _load_primary_mil_rows(
    database_path: Path,
    *,
    classified_rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], np.ndarray, list[str]]:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    try:
        source_rows = connection.execute(
            "SELECT detector,gps_start,identity_digest,image_sha256,mil_vector "
            "FROM windows WHERE is_candidate=1 ORDER BY detector,gps_start"
        ).fetchall()
    finally:
        connection.close()

    gates = contract["gates"]
    vector_dim = int(gates["vector_dim"])
    vector_blob_bytes = int(gates["vector_blob_bytes"])
    if len(source_rows) != int(gates["exact_total_rows"]) or len(source_rows) != len(
        classified_rows
    ):
        raise ContractError("corrected native-taxonomy population changed")
    vectors = np.empty((len(source_rows), vector_dim), dtype=np.float32)
    output_bases: list[dict[str, Any]] = []
    vector_hashes: list[str] = []
    identities: set[tuple[str, float]] = set()
    observed_counts: Counter[str] = Counter()
    forbidden = {"global_family_id", "taxonomy", "taxonomy_family"}
    for index, (source, classified) in enumerate(
        zip(source_rows, classified_rows, strict=True)
    ):
        detector, gps_start, identity_digest, image_sha256, mil_blob = source
        detector = str(detector)
        gps = float(gps_start)
        identity = (detector, gps)
        blob = bytes(mil_blob) if mil_blob is not None else b""
        if (
            identity in identities
            or forbidden & set(classified)
            or str(classified.get("detector")) != detector
            or float(classified.get("gps_start", np.nan)) != gps
            or str(classified.get("identity_digest")) != str(identity_digest)
            or str(classified.get("image_sha256")) != str(image_sha256)
            or len(blob) != vector_blob_bytes
        ):
            raise ContractError("corrected native-taxonomy source join changed")
        vector = np.frombuffer(blob, dtype="<f4")
        if (
            vector.shape != (vector_dim,)
            or not np.isfinite(vector).all()
            or float(np.linalg.norm(vector)) == 0.0
        ):
            raise ContractError("corrected native-taxonomy MIL vector changed")
        vectors[index] = vector
        identities.add(identity)
        observed_counts[detector] += 1
        output_bases.append(dict(classified))
        vector_hashes.append(hashlib.sha256(blob).hexdigest())
    if dict(sorted(observed_counts.items())) != gates["exact_rows_by_detector"]:
        raise ContractError("corrected native-taxonomy detector counts changed")
    return output_bases, vectors, vector_hashes


def build_taxonomy_rows(
    classified_rows: Sequence[Mapping[str, Any]],
    vectors: np.ndarray,
    vector_hashes: Sequence[str],
    *,
    contract: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    taxonomy = contract["taxonomy"]
    labels = cluster_primary_mil_vectors(
        vectors,
        distance_threshold=float(taxonomy["distance_threshold"]),
        linkage_method=str(taxonomy["linkage"]),
        criterion=str(taxonomy["flat_cluster_criterion"]),
    )
    identities = [
        (str(row["detector"]), float(row["gps_start"])) for row in classified_rows
    ]
    family_ids, family_sizes = assign_historical_family_ids(labels, identities)
    rows = []
    for source, vector_sha256, label, family_id, family_size in zip(
        classified_rows,
        vector_hashes,
        labels,
        family_ids,
        family_sizes,
        strict=True,
    ):
        rows.append(
            {
                **dict(source),
                "taxonomy_representation": taxonomy["representation"],
                "primary_mil_vector_sha256": vector_sha256,
                "morphology_cluster_label": int(label),
                "global_family_id": family_id,
                "morphology_family_size": int(family_size),
            }
        )
    cluster_sizes = Counter(int(value) for value in labels)
    multi_member_sizes = sorted(
        (int(size) for size in cluster_sizes.values() if size > 1), reverse=True
    )
    metrics = {
        "cluster_count": len(cluster_sizes),
        "multi_member_family_count": len(multi_member_sizes),
        "multi_member_row_count": int(sum(multi_member_sizes)),
        "singleton_row_count": int(sum(size == 1 for size in cluster_sizes.values())),
        "max_family_size": int(max(cluster_sizes.values())),
        "multi_member_size_digest": canonical_json_sha256(multi_member_sizes),
    }
    return rows, metrics


def _run_key(contract: Mapping[str, Any], *, runtime: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "stage": "native_taxonomy_v1",
            "contract_digest": contract["contract_digest"],
            "primary_scan_artifact_digest": contract["parent_primary_scan"][
                "compact_artifact_digest"
            ],
            "native_classification_artifact_digest": contract[
                "parent_native_classification"
            ]["run_artifact_digest"],
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
        }
    )


def run_native_taxonomy(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    classification_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_taxonomy_contract(root)
    runtime = load_canonical_runtime_contract(
        root=root, require_current=True, device=device
    )
    run_key = _run_key(contract, runtime=runtime)
    run_dir = external_root.resolve() / f"native_taxonomy_{run_key}"
    failure_path = run_dir / "failure.json"
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    output_path = run_dir / str(contract["output"]["taxonomy_filename"])
    if failure_path.is_file():
        raise ContractError("corrected native-taxonomy failure artifact is present")
    if summary_path.is_file():
        return verify_native_taxonomy(
            root=root,
            primary_external_root=primary_external_root,
            classification_external_root=classification_external_root,
            external_root=external_root,
            device=device,
        )
    try:
        database_path, classification_path, classified_rows = _verified_sources(
            contract=contract,
            primary_external_root=primary_external_root.resolve(),
            classification_external_root=classification_external_root.resolve(),
        )
        bases, vectors, vector_hashes = _load_primary_mil_rows(
            database_path,
            classified_rows=classified_rows,
            contract=contract,
        )
        rows, metrics = build_taxonomy_rows(
            bases, vectors, vector_hashes, contract=contract
        )
        _atomic_jsonl(output_path, rows)
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_COMPLETE_NATIVE_TAXONOMY_V1",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "runtime_environment_digest": runtime["runtime_environment"][
                "environment_digest"
            ],
            "taxonomy": contract["taxonomy"],
            "scientific_boundary": contract["scientific_boundary"],
            "row_total": len(rows),
            "counts_by_detector": dict(
                sorted(Counter(row["detector"] for row in rows).items())
            ),
            "counts_by_native_class": dict(
                sorted(Counter(row["native_class"] for row in rows).items())
            ),
            "family_metrics": metrics,
            "sources": {
                "primary_database": {
                    "filename": database_path.name,
                    "sha256": sha256_file(database_path),
                },
                "native_classification": {
                    "filename": classification_path.name,
                    "sha256": sha256_file(classification_path),
                    "row_digest": canonical_json_sha256(classified_rows),
                },
            },
            "output": {
                "filename": output_path.name,
                "sha256": sha256_file(output_path),
                "row_digest": canonical_json_sha256(rows),
                "size_bytes": output_path.stat().st_size,
            },
            "gates": {
                "duplicate_detector_gps": 0,
                "missing_or_invalid_mil_vectors": 0,
                "join_mismatches": 0,
                "primary_scores_read": False,
                "prior_taxonomy_read": False,
                "physical_coincidence_performed": False,
            },
        }
        summary = {**body, "artifact_digest": canonical_json_sha256(body)}
        _atomic_json(summary_path, summary)
        return summary, run_dir
    except BaseException as exc:
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_NATIVE_TAXONOMY_V1",
            "contract_digest": contract["contract_digest"],
            "run_key": run_key,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        raise


def verify_native_taxonomy(
    *,
    root: Path = ROOT,
    primary_external_root: Path,
    classification_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_taxonomy_contract(root)
    runtime = load_canonical_runtime_contract(
        root=root, require_current=True, device=device
    )
    run_key = _run_key(contract, runtime=runtime)
    run_dir = external_root.resolve() / f"native_taxonomy_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("corrected native-taxonomy failure artifact is present")
    summary_path = run_dir / str(contract["output"]["summary_filename"])
    output_path = run_dir / str(contract["output"]["taxonomy_filename"])
    if not summary_path.is_file() or not output_path.is_file():
        raise ContractError("corrected native-taxonomy output is missing")
    summary = _read_json(summary_path)
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if (
        digest != canonical_json_sha256(body)
        or summary.get("status") != "PASS_COMPLETE_NATIVE_TAXONOMY_V1"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key") != run_key
        or summary.get("taxonomy") != contract["taxonomy"]
        or summary.get("scientific_boundary") != contract["scientific_boundary"]
    ):
        raise ContractError("corrected native-taxonomy summary changed")
    database_path, classification_path, classified_rows = _verified_sources(
        contract=contract,
        primary_external_root=primary_external_root.resolve(),
        classification_external_root=classification_external_root.resolve(),
    )
    bases, vectors, vector_hashes = _load_primary_mil_rows(
        database_path,
        classified_rows=classified_rows,
        contract=contract,
    )
    expected_rows, expected_metrics = build_taxonomy_rows(
        bases, vectors, vector_hashes, contract=contract
    )
    observed_rows = _load_jsonl(output_path)
    expected_gates = {
        "duplicate_detector_gps": 0,
        "missing_or_invalid_mil_vectors": 0,
        "join_mismatches": 0,
        "primary_scores_read": False,
        "prior_taxonomy_read": False,
        "physical_coincidence_performed": False,
    }
    if (
        observed_rows != expected_rows
        or summary.get("row_total") != len(expected_rows)
        or summary.get("family_metrics") != expected_metrics
        or summary.get("output", {}).get("sha256") != sha256_file(output_path)
        or summary.get("output", {}).get("row_digest")
        != canonical_json_sha256(observed_rows)
        or summary.get("gates") != expected_gates
        or summary.get("sources", {}).get("primary_database", {}).get("sha256")
        != sha256_file(database_path)
        or summary.get("sources", {}).get("native_classification", {}).get("sha256")
        != sha256_file(classification_path)
    ):
        raise ContractError("corrected native-taxonomy replay changed")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "assign_historical_family_ids",
    "build_taxonomy_rows",
    "cluster_primary_mil_vectors",
    "load_native_taxonomy_contract",
    "run_native_taxonomy",
    "validate_native_taxonomy_contract",
    "verify_native_taxonomy",
]
