"""Identity-only manifests and one-shot confirmation sealing for v5."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256


SCHEMA_VERSION = 1
PARTITIONS = ("training", "development", "confirmation")
ROLES = ("background", "robust_candidate", "known_glitch", "injection")
EMPTY_ACCESS_LOG_SHA256 = hashlib.sha256(b"").hexdigest()
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _digest(value: Any, label: str) -> str:
    result = str(value).lower()
    if _SHA256.fullmatch(result) is None:
        raise ContractError(f"{label} must be a lowercase SHA256 digest")
    return result


def _reference(value: Mapping[str, Any], label: str) -> dict[str, str]:
    if set(value) != {"path", "sha256"}:
        raise ContractError(f"{label} must contain path and sha256")
    path = str(value["path"])
    if not path or Path(path).is_absolute() or "\\" in path:
        raise ContractError(f"{label}.path must be repository-relative POSIX text")
    return {"path": path, "sha256": _digest(value["sha256"], f"{label}.sha256")}


def gps_block_key(row: Mapping[str, Any], *, block_duration_s: int = 4096) -> str:
    window = WindowIdentity.from_dict(row["window"])
    return f"{window.detector}:{math.floor(window.gps_start / block_duration_s)}"


def validate_identity_row(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {"schema_version", "cohort_id", "role", "detector", "morphology", "partition", "partition_priority", "retention_target", "source", "stratum", "window"}
    if set(value) != required or value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("v5 identity row has missing or outcome-bearing fields")
    role = str(value["role"]); partition = str(value["partition"])
    if role not in ROLES or partition not in PARTITIONS:
        raise ContractError("invalid v5 role or partition")
    if partition == "training" and role != "background":
        raise ContractError("v5 training contains protected-role identities")
    if bool(value["retention_target"]) != (role != "background"):
        raise ContractError("v5 retention_target is inconsistent with role")
    window = WindowIdentity.from_dict(value["window"])
    if window.detector != str(value["detector"]):
        raise ContractError("v5 identity detector/window mismatch")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != {"kind", "run", "source_id"}:
        raise ContractError("v5 identity source is incomplete")
    if str(source["run"]).upper() != window.run:
        raise ContractError("v5 source/window run mismatch")
    stratum = value["stratum"]
    if not isinstance(stratum, dict):
        raise ContractError("v5 identity stratum must be a mapping")
    if role == "background" and set(stratum) != {"block_index", "window_index"}:
        raise ContractError("v5 background stratum is incomplete")
    if role == "robust_candidate" and set(stratum) != {"robustness_class", "taxonomy_family"}:
        raise ContractError("v5 ROBUST stratum is incomplete")
    if role == "known_glitch" and set(stratum) != {"gravityspy_label"}:
        raise ContractError("v5 known-glitch stratum is incomplete")
    if role == "injection" and set(stratum) != {"population", "system", "distance_mpc", "trial_index"}:
        raise ContractError("v5 injection stratum is incomplete")
    return {
        "schema_version": SCHEMA_VERSION,
        "cohort_id": str(value["cohort_id"]),
        "role": role,
        "detector": str(value["detector"]),
        "morphology": str(value["morphology"]),
        "partition": partition,
        "partition_priority": _digest(value["partition_priority"], "partition_priority"),
        "retention_target": bool(value["retention_target"]),
        "source": {name: str(source[name]) for name in ("kind", "run", "source_id")},
        "stratum": dict(stratum),
        "window": window.to_dict(),
    }


def build_identity_manifest(
    rows: Iterable[Mapping[str, Any]], *, protocol_reference: Mapping[str, Any],
    source_references: Sequence[Mapping[str, Any]], selection_code_reference: Mapping[str, Any],
    seed_derivation: Mapping[str, Any], prior_block_keys: Iterable[str],
) -> dict[str, Any]:
    normalized = sorted((validate_identity_row(row) for row in rows), key=lambda row: (row["partition"], row["role"], row["cohort_id"]))
    if not normalized:
        raise ContractError("v5 manifest cannot be empty")
    cohort_ids = [row["cohort_id"] for row in normalized]
    if len(cohort_ids) != len(set(cohort_ids)):
        raise ContractError("v5 manifest contains duplicate cohort identities")
    window_ids = [row["window"]["window_id"] for row in normalized]
    if len(window_ids) != len(set(window_ids)):
        raise ContractError("v5 manifest contains duplicate detector/window identities")
    blocks_by_partition = {name: set() for name in PARTITIONS}
    for row in normalized:
        block = gps_block_key(row)
        for other, blocks in blocks_by_partition.items():
            if other != row["partition"] and block in blocks:
                raise ContractError("v5 O4a detector/GPS block crosses partitions")
        blocks_by_partition[row["partition"]].add(block)
    prior = sorted(set(str(value) for value in prior_block_keys))
    if set().union(*blocks_by_partition.values()) & set(prior):
        raise ContractError("v5 manifest overlaps a prior O4a block")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "IDENTITY_ONLY_NOT_OPENED",
        "protocol_reference": _reference(protocol_reference, "protocol_reference"),
        "selection_code_reference": _reference(selection_code_reference, "selection_code_reference"),
        "source_references": [_reference(item, f"source_references[{index}]") for index, item in enumerate(source_references)],
        "seed_derivation": dict(seed_derivation),
        "prior_block_exclusions": {"count": len(prior), "digest": canonical_json_sha256(prior), "block_keys": prior},
        "outcome_fields_present": [],
        "teacher_scores_extracted": [],
        "student_outputs_extracted": [],
        "paired_costs_measured": [],
        "o4b_outcomes_used": [],
        "rows": normalized,
    }
    return {**body, "manifest_digest": canonical_json_sha256(body)}


def validate_identity_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(value); declared = body.pop("manifest_digest", None)
    if declared != canonical_json_sha256(body) or body.get("status") != "IDENTITY_ONLY_NOT_OPENED":
        raise ContractError("v5 identity manifest digest/status mismatch")
    for field in ("outcome_fields_present", "teacher_scores_extracted", "student_outputs_extracted", "paired_costs_measured", "o4b_outcomes_used"):
        if body.get(field) != []:
            raise ContractError(f"v5 identity boundary violated: {field}")
    if [validate_identity_row(row) for row in body["rows"]] != body["rows"]:
        raise ContractError("v5 manifest rows are not canonical")
    exclusions = body["prior_block_exclusions"]
    if exclusions["count"] != len(exclusions["block_keys"]) or exclusions["digest"] != canonical_json_sha256(exclusions["block_keys"]):
        raise ContractError("v5 prior-block exclusion contract mismatch")
    return dict(value)


def _confirmation_identity_digest(manifest: Mapping[str, Any]) -> str:
    rows = [{"cohort_id": row["cohort_id"], "window_id": row["window"]["window_id"], "source_id": row["source"]["source_id"]} for row in manifest["rows"] if row["partition"] == "confirmation"]
    if not rows:
        raise ContractError("v5 confirmation has no identities")
    return canonical_json_sha256(rows)


def build_confirmation_seal(
    manifest: Mapping[str, Any], *, freeze_commit: str,
    code_references: Mapping[str, Mapping[str, Any]],
    declared_storage_roots: Sequence[Mapping[str, str]],
    protected_endpoints: Sequence[str],
) -> dict[str, Any]:
    checked = validate_identity_manifest(manifest)
    commit = str(freeze_commit).lower()
    if _COMMIT.fullmatch(commit) is None:
        raise ContractError("v5 seal requires a full Git commit")
    required_code = {"split_builder", "protocol_validator", "seal_verifier", "preprocessing", "exact_dante_runner"}
    if set(code_references) != required_code:
        raise ContractError("v5 seal code references are incomplete")
    required_endpoints = {"protected_stratum_retention", "teacher_fidelity", "background_routing_decisions", "paired_prefilter_costs", "paired_avoidable_exact_path_costs", "block_bootstrap_net_saving"}
    if not required_endpoints <= set(protected_endpoints):
        raise ContractError("v5 seal does not protect the confirmation cost-benefit endpoint")
    roots = []
    for item in declared_storage_roots:
        if set(item) != {"root_id", "kind", "location"} or item["kind"] not in {"repository_relative", "environment_alias"} or "\\" in item["location"]:
            raise ContractError("invalid v5 storage root")
        roots.append(dict(item))
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "SEALED_NOT_OPENED",
        "freeze_commit": commit,
        "manifest_digest": checked["manifest_digest"],
        "confirmation_identity_digest": _confirmation_identity_digest(checked),
        "protocol_reference": checked["protocol_reference"],
        "code_references": {name: _reference(reference, f"code.{name}") for name, reference in sorted(code_references.items())},
        "declared_storage_roots": roots,
        "protected_endpoints": sorted(set(str(value) for value in protected_endpoints)),
        "initial_access_log_sha256": EMPTY_ACCESS_LOG_SHA256,
        "access_entries_at_freeze": 0,
        "claim_boundary": "declared_storage_access_ledger_and_protected_endpoint_scope",
    }
    return {**body, "seal_digest": canonical_json_sha256(body)}


def verify_unopened_seal(manifest: Mapping[str, Any], seal: Mapping[str, Any], *, access_log_bytes: bytes, observed_records: Iterable[Mapping[str, Any]] = ()) -> None:
    checked = validate_identity_manifest(manifest)
    body = dict(seal); declared = body.pop("seal_digest", None)
    if declared != canonical_json_sha256(body) or seal.get("status") != "SEALED_NOT_OPENED":
        raise ContractError("v5 confirmation seal digest/status mismatch")
    if seal.get("manifest_digest") != checked["manifest_digest"] or seal.get("confirmation_identity_digest") != _confirmation_identity_digest(checked):
        raise ContractError("v5 confirmation seal/identity mismatch")
    if access_log_bytes or hashlib.sha256(access_log_bytes).hexdigest() != EMPTY_ACCESS_LOG_SHA256:
        raise ContractError("v5 confirmation access ledger is not empty at freeze")
    confirmation = {row["cohort_id"] for row in checked["rows"] if row["partition"] == "confirmation"}
    if confirmation & {str(row.get("cohort_id")) for row in observed_records}:
        raise ContractError("v5 confirmation outcome record already exists")


def build_unlock_receipt(manifest: Mapping[str, Any], seal: Mapping[str, Any], development_result: Mapping[str, Any], *, access_log_bytes: bytes) -> dict[str, Any]:
    verify_unopened_seal(manifest, seal, access_log_bytes=access_log_bytes)
    required = {
        "status", "protocol_sha256", "manifest_digest", "model_digest",
        "model_code_digest", "threshold_digest", "teacher_contract_digest",
        "paired_cost_contract_digest", "injection_generator_digest",
        "replicate_selection_digest", "verifier_digest",
    }
    if set(development_result) != required or development_result["status"] != "READY_FOR_CONFIRMATION":
        raise ContractError("v5 development result cannot authorize confirmation")
    if development_result["protocol_sha256"] != seal["protocol_reference"]["sha256"] or development_result["manifest_digest"] != seal["manifest_digest"]:
        raise ContractError("v5 development result is bound to another freeze")
    for field in required - {"status"}:
        if field not in {"protocol_sha256", "manifest_digest"}:
            _digest(development_result[field], field)
    body = {"schema_version": SCHEMA_VERSION, "status": "CONFIRMATION_OPEN_ONCE", "seal_digest": seal["seal_digest"], "confirmation_identity_digest": seal["confirmation_identity_digest"], "protected_endpoints": seal["protected_endpoints"], "development_result": dict(development_result)}
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def append_access_record(path: str | Path, record: Mapping[str, Any]) -> dict[str, Any]:
    destination = Path(path); existing = []
    if destination.exists():
        existing = [json.loads(line) for line in destination.read_text(encoding="utf-8").splitlines() if line.strip()]
    previous = EMPTY_ACCESS_LOG_SHA256
    for index, entry in enumerate(existing):
        body = dict(entry); declared = body.pop("record_digest", None)
        if body.get("sequence") != index or body.get("previous_digest") != previous or declared != canonical_json_sha256(body):
            raise ContractError("v5 access ledger chain is broken")
        previous = declared
    body = {"schema_version": SCHEMA_VERSION, "sequence": len(existing), "previous_digest": previous, **dict(record)}
    entry = {**body, "record_digest": canonical_json_sha256(body)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(destination, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode()); os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return entry
