"""Exact frozen taxonomy replay on retained evidence, never history writes."""

from __future__ import annotations

from collections import Counter
from contextlib import ExitStack
import hashlib
import importlib
import json
from pathlib import Path

from . import o3a_decision_verification as decisions
from .o3a_locking import clean_native_parent
from .o3a_initial_verification import InitialEvidenceError, _Evidence, _existing


def _sources(root):
    from src.dante_light.o3a_raw_download import file_sha256

    result = decisions._sources(root)
    for name in (
        "src.dante_light.o3a_native_taxonomy",
        "src.dante_light.o4a_corrected_native_taxonomy",
    ):
        module = importlib.import_module(name)
        relative = name.replace(".", "/") + ".py"
        digest = file_sha256(Path(module.__file__))
        if file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError(f"executed helper source mismatch: {relative}")
        result[relative] = digest
    base = Path(__file__).resolve().parents[2]
    for relative in (
        "src/dante_workflow/o3a_taxonomy_verification.py",
        "scripts/verify_dante_o3a_taxonomy_evidence.py",
    ):
        result[relative] = file_sha256(base / relative)
    return result


def _candidate_rows(database_path, classified_rows, contract):
    """Original O4a reader's query/joins; approved immutable connection only."""
    import numpy as np
    from src.dante_light.contracts import ContractError

    with decisions.scores.parents.immutable_database(database_path) as connection:
        source_rows = connection.execute(
            "SELECT detector,gps_start,identity_digest,image_sha256,mil_vector "
            "FROM windows WHERE is_candidate=1 ORDER BY detector,gps_start"
        ).fetchall()
    gates = contract["gates"]
    vector_dim = int(gates["vector_dim"])
    vector_blob_bytes = int(gates["vector_blob_bytes"])
    if len(source_rows) != int(gates["exact_total_rows"]) or len(source_rows) != len(
        classified_rows
    ):
        raise ContractError("corrected native-taxonomy population changed")
    vectors = np.empty((len(source_rows), vector_dim), dtype=np.float32)
    output_bases, vector_hashes = [], []
    identities, observed_counts = set(), Counter()
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


def _taxonomy_gate(
    *,
    root,
    external_root,
    classification_external_root,
    threshold_external_root,
    parent_arguments,
    evidence,
    stack,
):
    from src.dante_light import o3a_native_taxonomy as tx
    from src.dante_light import o3a_native_classification as nc
    from src.dante_light.contracts import canonical_json_sha256

    contract = tx.load_contract(root=root)
    decisions._contract(evidence, root, "taxonomy_contract", tx.CONTRACT_REL, contract)
    directory = tx._run_dir(contract, external_root)
    stack.enter_context(decisions._persistent_lock(directory))
    evidence.read("taxonomy_lock", directory / "run.lock")
    saved = evidence.sealed(
        "taxonomy_summary",
        _existing(directory, contract["output"]["summary_filename"]),
        "artifact_digest",
    )
    classified, classification_dir = decisions._classification_gate(
        root=root,
        external_root=classification_external_root,
        threshold_external_root=threshold_external_root,
        parent_arguments=parent_arguments,
        evidence=evidence,
        stack=stack,
    )
    primary = decisions.scores._saved(evidence, "scan_summary")
    expected_primary = contract["parent_primary_scan"]
    expected_classification = contract["parent_native_classification"]
    compact = evidence.sealed(
        "taxonomy_classification_compact",
        _existing(root, nc.COMPACT_REL),
        "artifact_digest",
    )
    if (
        any(primary[k] != v for k, v in expected_primary.items())
        or any(compact[k] != v for k, v in expected_classification.items())
        or classified["artifact_digest"]
        != expected_classification["run_artifact_digest"]
        or evidence.inputs["classification_summary"]["sha256"]
        != expected_classification["summary_sha256"]
        or classified["output_sha256"] != expected_classification["output_sha256"]
        or classification_dir.name
        != "native_classification_" + expected_classification["run_key"]
    ):
        raise InitialEvidenceError("taxonomy verified parent changed")
    database = Path(evidence.inputs["scan_database"]["path"])
    if (
        database.name != expected_primary["database"]["filename"]
        or evidence.inputs["scan_database"]["sha256"]
        != expected_primary["database"]["sha256"]
    ):
        raise InitialEvidenceError("taxonomy database binding changed")
    classification_contract = nc.load_contract(root=root)
    decisions._contract(
        evidence,
        root,
        "classification_contract",
        nc.CONTRACT_REL,
        classification_contract,
    )
    rows = decisions.scores._rows(
        evidence,
        "taxonomy_classification_input",
        _existing(
            classification_dir, classification_contract["output"]["candidate_filename"]
        ),
        expected_classification["output_sha256"],
    )
    if canonical_json_sha256(rows) != expected_classification["output_row_digest"]:
        raise InitialEvidenceError("taxonomy classified row digest changed")
    bases, vectors, hashes = _candidate_rows(database, rows, contract)
    rows, metrics = tx.build_taxonomy_rows(bases, vectors, hashes, contract=contract)
    family_ids = [row["global_family_id"] for row in rows]
    singletons = [
        row["global_family_id"] for row in rows if row["morphology_family_size"] == 1
    ]
    if len(singletons) != len(set(singletons)):
        raise InitialEvidenceError("O3a taxonomy historical singleton IDs collide")
    payload = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    ).encode("utf-8")
    expected_sha = hashlib.sha256(payload).hexdigest()
    if (
        evidence.read(
            "taxonomy_output",
            _existing(directory, contract["output"]["taxonomy_filename"]),
            expected_sha,
        )
        != payload
    ):
        raise InitialEvidenceError("taxonomy output replay changed")
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_TAXONOMY",
        "contract_digest": contract["contract_digest"],
        "run_key": directory.name.removeprefix("native_taxonomy_"),
        "runtime_environment_digest": contract["runtime_environment_digest"],
        "parent_primary_scan_artifact_digest": expected_primary["artifact_digest"],
        "parent_native_classification_artifact_digest": expected_classification[
            "artifact_digest"
        ],
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
        "source_database_sha256": evidence.inputs["scan_database"]["sha256"],
        "source_classification_sha256": expected_classification["output_sha256"],
        "output_sha256": expected_sha,
        "output_row_digest": canonical_json_sha256(rows),
        "scientific_boundary": contract["scientific_boundary"],
    }
    if saved != {**body, "artifact_digest": canonical_json_sha256(body)}:
        raise InitialEvidenceError("taxonomy deterministic replay changed")
    decisions._compact(
        evidence,
        root,
        tx.COMPACT_REL,
        "taxonomy_compact",
        saved,
        directory,
        "PASS_VERIFIED_O3A_NATIVE_TAXONOMY",
    )
    return saved, directory


def verify_taxonomy_evidence(
    *,
    root,
    external_root,
    classification_external_root,
    threshold_external_root,
    rescore_external_root,
    calibration_external_root,
    index_external_root,
    cohort_external_root,
    primary_external_root,
):
    from src.dante_light.contracts import canonical_json_sha256

    decisions._fcntl()
    root = root.resolve()
    sources_before, evidence = _sources(root), _Evidence()
    parent_arguments = {
        "external_root": rescore_external_root.resolve(),
        "calibration_external_root": calibration_external_root.resolve(),
        "index_external_root": index_external_root.resolve(),
        "cohort_external_root": cohort_external_root.resolve(),
        "primary_external_root": primary_external_root.resolve(),
    }
    with ExitStack() as stack:
        summary, directory = _taxonomy_gate(
            root=root,
            external_root=external_root.resolve(),
            classification_external_root=classification_external_root.resolve(),
            threshold_external_root=threshold_external_root.resolve(),
            parent_arguments=parent_arguments,
            evidence=evidence,
            stack=stack,
        )
        evidence.unchanged()
        for name in (
            "scan_summary",
            "cohort_summary",
            "index_summary",
            "calibration_summary",
            "rescore_summary",
        ):
            if name in evidence.inputs:
                clean_native_parent(
                    Path(evidence.inputs[name]["path"]).parent, stack=stack
                )
        for reference in evidence.inputs.values():
            if reference["path"].endswith(".sqlite"):
                decisions.scores.parents._no_journals(Path(reference["path"]))
        if _sources(root) != sources_before:
            raise InitialEvidenceError("helper sources changed during verification")
        body = {
            "schema_version": 1,
            "status": "PASS_O3A_READ_ONLY_TAXONOMY_DETERMINISTIC_REPLAY_ONLY",
            "verification_policy_id": "o3a-native-taxonomy-evidence-read-only-v1",
            "verification_level": "EXISTING_FROZEN_GATE_RECONSTRUCTION",
            "observing_run": "O3a",
            "stage": "taxonomy",
            "run_dir": str(directory),
            "legacy_artifact_digest": summary["artifact_digest"],
            "historical_evidence_mutated": False,
            "raw_score_replay_executed": False,
            "encoder_executed": False,
            "preprocessing_replay_executed": False,
            "source_fetch_executed": False,
            "full_workflow_verified": False,
            "threshold_bootstrap_replay_executed": True,
            "classification_replay_executed": True,
            "taxonomy_replay_executed": True,
            "global_upstream_quiescence_verified": False,
            "persistent_lock_policy": "EXISTING_READ_ONLY_NONBLOCKING_EXCLUSIVE_FLOCK",
            "inputs": evidence.inputs,
            "source_bindings": sources_before,
        }
        result = {**body, "receipt_digest": canonical_json_sha256(body)}
    return result
