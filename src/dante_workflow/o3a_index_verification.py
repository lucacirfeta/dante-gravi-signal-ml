"""Read retained O3a INDEX evidence through immutable explicit parent gates."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
from pathlib import Path

from . import o3a_native_verification as parents
from .o3a_locking import clean_native_parent, hold_native_lock
from .o3a_retained_runtime import load_runtime
from .o3a_initial_verification import (
    InitialEvidenceError,
    _Evidence,
    _existing,
    _json,
)


def _sources(root):
    from src.dante_light import o3a_native_index, o4a_corrected_native_index
    from src.dante_light.o3a_raw_download import file_sha256

    result = parents._sources(root)
    for module in (o3a_native_index, o4a_corrected_native_index):
        relative = module.__name__.replace(".", "/") + ".py"
        digest = file_sha256(Path(module.__file__))
        if file_sha256(_existing(root, relative)) != digest:
            raise InitialEvidenceError(f"executed helper source mismatch: {relative}")
        result[relative] = digest
    base = Path(__file__).resolve().parents[2]
    for relative in (
        "src/dante_workflow/o3a_index_verification.py",
        "scripts/verify_dante_o3a_index_evidence.py",
    ):
        result[relative] = file_sha256(base / relative)
    return result


def _index_gate(
    *, root, external_root, cohort_external_root, primary_external_root, evidence, stack
):
    import numpy as np
    from src.dante_light import o3a_native_index as index
    from src.dante_light.contracts import canonical_json_sha256

    contract = index.load_index_contract(root=root)
    parents._loaded(evidence, root, "index_contract", index.CONTRACT_REL, contract)
    runtime = load_runtime(evidence, index.load_runtime_contract, root=root)
    parents._loaded(evidence, root, "runtime_contract", index.RUNTIME_REL, runtime)
    cohort, cohort_dir = parents._cohort_gate(
        root=root,
        external_root=cohort_external_root,
        primary_external_root=primary_external_root,
        evidence=evidence,
        stack=stack,
    )
    if (
        cohort["artifact_digest"]
        != contract["parents"]["frozen_native_cohort"]["artifact_digest"]
    ):
        raise InitialEvidenceError("O3a native-index parent cohort changed")
    key = index._run_key(contract, runtime)
    directory = external_root / f"native_index_{key}"
    hold_native_lock(directory, evidence=evidence, stack=stack, name="index")
    preflight = evidence.sealed(
        "index_preflight", _existing(directory, "preflight.json"), "preflight_digest"
    )
    if preflight != index._load_preflight(
        run_dir=directory, contract=contract, run_key=key
    ):
        raise InitialEvidenceError("loaded index preflight differs from file")
    summary = evidence.sealed(
        "index_summary",
        _existing(directory, "native_index_summary.json"),
        "artifact_digest",
    )
    gates = contract["gates"]
    if (
        summary.get("status") != "PASS_BUILT_O3A_NATIVE_INDEX"
        or summary.get("run_key") != key
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("cohort_artifact_digest") != cohort["artifact_digest"]
        or summary.get("runtime_environment_digest")
        != runtime["runtime_environment"]["environment_digest"]
        or summary.get("counts_by_detector") != gates["exact_cohort_counts_by_detector"]
        or summary.get("cohort_row_total") != int(gates["exact_cohort_rows"])
        or summary.get("index", {}).get("token_total")
        != int(gates["exact_patch_token_total"])
    ):
        raise InitialEvidenceError("O3a native-index summary changed")
    index_path = _existing(directory, summary["index"]["filename"])
    parents._pin(evidence, "index_npz", index_path, summary["index"]["sha256"])
    replay_path = _existing(directory, summary["replay_ledger"]["filename"])
    replay_rows = [
        _json(line)
        for line in evidence.read(
            "index_replay", replay_path, summary["replay_ledger"]["sha256"]
        ).splitlines()
        if line.strip()
    ]
    if index_path.stat().st_size != summary["index"]["size_bytes"]:
        raise InitialEvidenceError("O3a native-index output file size changed")
    cohort_path = _existing(cohort_dir, cohort["ledger"]["filename"])
    evidence.read("index_cohort_ledger", cohort_path, cohort["ledger"]["sha256"])
    cohort_rows = index._cohort_rows(cohort_dir, cohort)
    if (
        len(replay_rows) != len(cohort_rows)
        or canonical_json_sha256(replay_rows) != summary["replay_ledger"]["row_digest"]
    ):
        raise InitialEvidenceError("O3a native-index replay ledger changed")
    for position, (row, replay) in enumerate(
        zip(cohort_rows, replay_rows, strict=True)
    ):
        token_path, manifest_path = index._shard_paths(directory, position)
        token_path = _existing(directory, token_path.relative_to(directory).as_posix())
        manifest_path = _existing(
            directory, manifest_path.relative_to(directory).as_posix()
        )
        manifest = evidence.sealed(
            f"index_manifest:{position}", manifest_path, "shard_digest"
        )
        parents._pin(
            evidence,
            f"index_token:{position}",
            token_path,
            manifest["token_file_sha256"],
        )
        shard = index._read_shard(
            run_dir=directory, position=position, row=row, contract=contract
        )
        if shard is None or shard[1] != manifest:
            raise InitialEvidenceError(
                "O3a native-index token shard missing or changed"
            )
        if replay != {
            "position": position,
            **manifest["replay"],
            "patch_tokens_sha256": manifest["patch_tokens_sha256"],
        }:
            raise InitialEvidenceError("O3a native-index replay/shard mismatch")
    with np.load(index_path, allow_pickle=False) as data:
        if set(data.files) != {"embeddings", "labels", "raw_embeddings_sample", "meta"}:
            raise InitialEvidenceError("O3a native-index NPZ schema changed")
        centroids = np.asarray(data["embeddings"])
        labels = np.asarray(data["labels"])
        raw_sample = np.asarray(data["raw_embeddings_sample"])
        meta = json.loads(str(data["meta"].item()))
    if (
        list(centroids.shape) != gates["exact_centroid_shape"]
        or list(raw_sample.shape) != gates["exact_raw_sample_shape"]
        or centroids.dtype != np.float32
        or raw_sample.dtype != np.float32
        or labels.shape != (len(centroids),)
        or set(labels.tolist()) != {"BG_O3a"}
        or meta.get("run") != "O3a"
        or meta.get("K") != len(centroids)
        or meta.get("cohort_artifact_digest") != cohort["artifact_digest"]
        or meta.get("contract_digest") != contract["contract_digest"]
        or meta.get("detector_identity_inferred") is not False
        or hashlib.sha256(centroids.tobytes()).hexdigest()
        != summary["index"]["centroid_bytes_sha256"]
        or hashlib.sha256(raw_sample.tobytes()).hexdigest()
        != summary["index"]["raw_sample_bytes_sha256"]
    ):
        raise InitialEvidenceError("O3a native-index NPZ provenance changed")
    maximum_error = float(gates["maximum_l2_norm_error"])
    if (
        not np.isfinite(centroids).all()
        or not np.isfinite(raw_sample).all()
        or float(np.max(np.abs(np.linalg.norm(centroids, axis=1) - 1))) > maximum_error
        or float(np.max(np.abs(np.linalg.norm(raw_sample, axis=1) - 1))) > maximum_error
    ):
        raise InitialEvidenceError("O3a native-index normalization gate failed")
    return summary, directory


def verify_index_evidence(
    *,
    root: Path,
    external_root: Path,
    cohort_external_root: Path,
    primary_external_root: Path,
):
    from src.dante_light.contracts import canonical_json_sha256

    root = root.resolve()
    evidence, sources = _Evidence(), _sources(root)
    with ExitStack() as stack:
        summary, directory = _index_gate(
            root=root,
            external_root=external_root.resolve(),
            cohort_external_root=cohort_external_root.resolve(),
            primary_external_root=primary_external_root.resolve(),
            evidence=evidence,
            stack=stack,
        )
        evidence.unchanged()
        for reference in evidence.inputs.values():
            if reference["path"].endswith(".sqlite"):
                parents._no_journals(Path(reference["path"]))
        for name in ("scan_summary", "cohort_summary", "index_summary"):
            if name in evidence.inputs:
                clean_native_parent(
                    Path(evidence.inputs[name]["path"]).parent, stack=stack
                )
        clean_native_parent(directory, stack=stack)
        if _sources(root) != sources:
            raise InitialEvidenceError("helper sources changed during verification")
        body = {
            "schema_version": 1,
            "status": "PASS_O3A_READ_ONLY_INDEX_STORED_VALIDATION_ONLY",
            "verification_policy_id": "o3a-native-index-evidence-read-only-v1",
            "verification_level": "EXISTING_FROZEN_INDEX_GATE_VALIDATION",
            "observing_run": "O3a",
            "stage": "index",
            "run_dir": str(directory),
            "legacy_artifact_digest": summary["artifact_digest"],
            "historical_evidence_mutated": False,
            "raw_score_replay_executed": False,
            "encoder_executed": False,
            "preprocessing_replay_executed": False,
            "clustering_refit_executed": False,
            "threshold_fit_executed": False,
            "source_fetch_executed": False,
            "full_workflow_verified": False,
            "stored_patch_tokens_checked": True,
            "stored_npz_numerically_checked": True,
            "inputs": evidence.inputs,
            "source_bindings": sources,
        }
        return {**body, "receipt_digest": canonical_json_sha256(body)}
