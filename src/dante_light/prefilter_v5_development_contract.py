"""Outcome-blind development contract for the frozen DANTE-Light v5 students."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import (
    PROTOCOL_ID,
    ROOT,
    derive_seed,
    load_protocol,
    repository_reference,
    sha256_path,
)


SCHEMA_VERSION = 1
DEFAULT_DESIGN = ROOT / "config/dante_light_prefilter_v5_development_design.json"
DEFAULT_PROTOCOL = ROOT / "config/dante_light_prefilter_protocol_v5.json"
DEFAULT_SPLIT_HEADER = ROOT / "config/dante_light_prefilter_splits_v5.json"
DEFAULT_SEAL = ROOT / "config/dante_light_prefilter_v5_confirmation_seal.json"
DEFAULT_TRAINING = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/student_training_summary_v5.json"
)
DEFAULT_OUTPUT = ROOT / "config/dante_light_prefilter_v5_development_contract.json"


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v5 development JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"v5 development JSON is not a mapping: {path}")
    return value


def _validate_design(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status")
        != "APPROVED_OUTCOME_BLIND_DEVELOPMENT_FREEZE_INPUT"
    ):
        raise ContractError("v5 development design status/schema mismatch")
    scope = value["scope"]
    if (
        scope.get("allowed_partition") != "development"
        or scope.get("confirmation_access_allowed") is not False
        or scope.get("o4b_access_allowed") is not False
        or scope.get("routing_enabled") is not False
        or scope.get("evaluate_all_frozen_arms") is not True
        or scope.get("evaluate_all_frozen_replicates") is not True
    ):
        raise ContractError("v5 development scope was widened")
    audit = value["audit_stream"]
    if (
        float(audit.get("fraction", -1.0)) != 0.05
        or audit.get("cost_included") is not True
        or audit.get("seed_purpose") != "development_audit_stream"
    ):
        raise ContractError("v5 development audit stream differs from approval")
    threshold = value["threshold_selection"]
    if (
        threshold.get("routing_rule")
        != "call_exact_if_student_score_gte_threshold_or_audit_selected"
        or threshold.get("candidate_thresholds")
        != "all_unique_observed_development_scores_plus_positive_infinity"
        or threshold.get("detector_specific") is not True
        or threshold.get("no_cross_morphology_aggregation") is not True
    ):
        raise ContractError("v5 threshold-selection rule is not exhaustive/frozen")
    replicates = value["replicates"]
    if (
        replicates.get("promotion_basis") != "worst_replicate_all_gates"
        or replicates.get("favorable_seed_selection_allowed") is not False
    ):
        raise ContractError("v5 replicate rule permits favorable-seed selection")
    return dict(value)


def build_development_contract(
    *,
    root: Path = ROOT,
    design_path: Path = DEFAULT_DESIGN,
    protocol_path: Path = DEFAULT_PROTOCOL,
    split_header_path: Path = DEFAULT_SPLIT_HEADER,
    seal_path: Path = DEFAULT_SEAL,
    training_path: Path = DEFAULT_TRAINING,
    code_paths: Mapping[str, Path],
) -> dict[str, Any]:
    """Freeze development mechanics without opening a development row."""

    design = _validate_design(_load(design_path))
    protocol = load_protocol(protocol_path, root=root)
    split = _load(split_header_path)
    seal = _load(seal_path)
    training = _load(training_path)
    training_body = dict(training)
    training_digest = training_body.pop("artifact_digest", None)
    if training_digest != canonical_json_sha256(training_body):
        raise ContractError("v5 training summary digest mismatch before development freeze")
    if training.get("status") != "TRAINING_COMPLETE_PENDING_DEVELOPMENT":
        raise ContractError("v5 training matrix is not complete")
    if (
        training.get("development_rows_accessed") != []
        or training.get("confirmation_rows_accessed") != []
        or training.get("o4b_rows_accessed") != []
    ):
        raise ContractError("v5 training summary already exposes protected outcomes")
    if seal.get("status") != "SEALED_NOT_OPENED" or seal.get("access_entries_at_freeze") != 0:
        raise ContractError("v5 confirmation seal is not unopened")
    split_entries = split["entries_reference"]
    entries_path = root / str(split_entries["path"])
    if sha256_path(entries_path) != split_entries["sha256"]:
        raise ContractError("v5 split entries changed before development freeze")
    required_code = {
        "development_contract",
        "development_evaluator",
        "development_waveforms",
        "development_screening",
        "development_cli",
        "development_verifier",
        "injection_reconstruction",
        "student_architectures",
        "student_training",
        "teacher",
    }
    if set(code_paths) != required_code:
        raise ContractError("v5 development code reference set is incomplete")
    code_references = {
        name: repository_reference(root, path)
        for name, path in sorted(code_paths.items())
    }
    references = {
        "design": repository_reference(root, design_path),
        "protocol": repository_reference(root, protocol_path),
        "split_header": repository_reference(root, split_header_path),
        "split_entries": repository_reference(root, entries_path),
        "confirmation_seal": repository_reference(root, seal_path),
        "injection_trials": repository_reference(
            root, root / "config/dante_light_prefilter_v5_injection_trials.jsonl"
        ),
        "training_summary": repository_reference(root, training_path),
        "training_contract": repository_reference(
            root, root / "config/dante_light_prefilter_v5_training_contract.json"
        ),
        "teacher_contract": repository_reference(
            root, root / "config/dante_light_prefilter_v5_teacher_contract.json"
        ),
        "reference_manifest": repository_reference(
            root, root / "config/reference_artifacts.json"
        ),
    }
    parent_digests = sorted(
        {
            protocol["protocol_digest"],
            str(training_digest),
            str(split["manifest_digest"]),
            str(seal["seal_digest"]),
            references["design"]["sha256"],
        }
    )
    audit_seed = derive_seed(
        PROTOCOL_ID,
        str(design["audit_stream"]["seed_purpose"]),
        parent_digests,
    )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_BEFORE_DEVELOPMENT_ACCESS",
        "protocol_id": PROTOCOL_ID,
        "approved_design": design,
        "source_references": references,
        "code_references": code_references,
        "parent_digests": parent_digests,
        "audit_seed_uint64": audit_seed,
        "bootstrap_seed_uint64": int(protocol["seed_derivation"]["seeds"]["bootstrap"]),
        "training_run_key": training["run_key"],
        "training_artifact_digest": training_digest,
        "training_replicate_count": len(training["replicate_summaries"]),
        "development_access_at_freeze": [],
        "confirmation_access_at_freeze": [],
        "o4b_access_at_freeze": [],
    }
    return {**body, "development_contract_digest": canonical_json_sha256(body)}


def validate_development_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    body = dict(value)
    declared = body.pop("development_contract_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v5 development contract self-digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_BEFORE_DEVELOPMENT_ACCESS"
        or value.get("protocol_id") != PROTOCOL_ID
    ):
        raise ContractError("v5 development contract status/schema mismatch")
    _validate_design(value["approved_design"])
    if (
        value.get("development_access_at_freeze") != []
        or value.get("confirmation_access_at_freeze") != []
        or value.get("o4b_access_at_freeze") != []
    ):
        raise ContractError("v5 development contract was not frozen outcome-blind")
    for group in ("source_references", "code_references"):
        for label, reference in value[group].items():
            path = root / str(reference["path"])
            if (
                not path.is_file()
                or repository_reference(root, path)["sha256"] != reference["sha256"]
            ):
                raise ContractError(f"v5 development reference mismatch: {group}.{label}")
    protocol = load_protocol(
        root / value["source_references"]["protocol"]["path"], root=root
    )
    expected_seed = derive_seed(
        PROTOCOL_ID,
        str(value["approved_design"]["audit_stream"]["seed_purpose"]),
        value["parent_digests"],
    )
    if int(value["audit_seed_uint64"]) != expected_seed:
        raise ContractError("v5 development audit seed does not reproduce")
    if int(value["bootstrap_seed_uint64"]) != int(
        protocol["seed_derivation"]["seeds"]["bootstrap"]
    ):
        raise ContractError("v5 development bootstrap seed changed")
    return dict(value)


def load_development_contract(
    path: Path = DEFAULT_OUTPUT, *, root: Path = ROOT
) -> dict[str, Any]:
    return validate_development_contract(_load(path), root=root)


def write_contract(value: Mapping[str, Any], path: Path = DEFAULT_OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path
