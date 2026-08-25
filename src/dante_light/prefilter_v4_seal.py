"""Outcome-blind identity manifests and confirmation sealing for L4 v4.

The functions in this module are infrastructure only. They deliberately cannot
freeze sample sizes or open protected data. A confirmation partition requires a
hash-bound development receipt; O4b is outside this contract.
"""

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
ROLES = ("background", "robust_candidate", "known_glitch", "injection")
PARTITIONS = ("development", "confirmation")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ROOT_FIELDS = {
    "schema_version",
    "cohort_id",
    "role",
    "detector",
    "morphology",
    "partition",
    "partition_priority",
    "retention_target",
    "source",
    "stratum",
    "window",
}
_SOURCE_FIELDS = {"kind", "run", "source_id"}
EMPTY_ACCESS_LOG_SHA256 = hashlib.sha256(b"").hexdigest()


def _digest(value: Any, label: str) -> str:
    result = str(value).lower()
    if _SHA256.fullmatch(result) is None:
        raise ContractError(f"{label} must be a lowercase SHA256 digest")
    return result


def _reference(value: Mapping[str, Any], label: str) -> dict[str, str]:
    if set(value) != {"path", "sha256"}:
        raise ContractError(f"{label} must contain only path and sha256")
    path = str(value["path"])
    if not path or Path(path).is_absolute() or "\\" in path:
        raise ContractError(f"{label}.path must be repository-relative POSIX text")
    return {"path": path, "sha256": _digest(value["sha256"], f"{label}.sha256")}


def _validate_stratum(role: str, value: Any, morphology: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError("identity stratum must be a mapping")
    if role == "background":
        if value:
            raise ContractError("background identity stratum must be empty")
    elif role == "robust_candidate":
        if value != {"robustness_class": "ROBUST"}:
            raise ContractError("ROBUST identity must expose class membership only")
    elif role == "known_glitch":
        if set(value) != {"gravityspy_label"} or not str(value["gravityspy_label"]):
            raise ContractError("known-glitch identity lacks its categorical label")
    elif role == "injection":
        if set(value) != {"system", "distance_mpc", "trial_index"}:
            raise ContractError("injection identity stratum is incomplete")
        if str(value["system"]) != morphology:
            raise ContractError("injection system/morphology mismatch")
        distance = float(value["distance_mpc"])
        trial = value["trial_index"]
        if not math.isfinite(distance) or distance <= 0.0:
            raise ContractError("injection distance must be finite and positive")
        if isinstance(trial, bool) or int(trial) != trial or trial < 0:
            raise ContractError("injection trial_index must be non-negative")
    return dict(value)


def validate_identity_row(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a strict metadata-only cohort row and return its normalized copy."""

    if set(value) != _ROOT_FIELDS:
        raise ContractError("v4 identity row contains missing or outcome-bearing fields")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported v4 identity-row schema")
    role = str(value["role"])
    partition = str(value["partition"])
    if role not in ROLES or partition not in PARTITIONS:
        raise ContractError("invalid v4 identity role or partition")
    cohort_id = str(value["cohort_id"])
    morphology = str(value["morphology"])
    if not cohort_id or not morphology:
        raise ContractError("v4 identity row lacks a cohort_id or morphology")
    priority = _digest(value["partition_priority"], "partition_priority")
    detector = str(value["detector"])
    window = WindowIdentity.from_dict(value["window"])
    if detector != window.detector:
        raise ContractError("identity detector/window mismatch")
    source = value["source"]
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ContractError("identity source must contain kind, run, and source_id")
    if not all(str(source[field]) for field in _SOURCE_FIELDS):
        raise ContractError("identity source fields must be non-empty")
    if str(source["run"]).upper() != window.run:
        raise ContractError("identity source/window observing-run mismatch")
    target = bool(value["retention_target"])
    if target != (role != "background"):
        raise ContractError("retention_target is inconsistent with cohort role")
    return {
        "schema_version": SCHEMA_VERSION,
        "cohort_id": cohort_id,
        "role": role,
        "detector": detector,
        "morphology": morphology,
        "partition": partition,
        "partition_priority": priority,
        "retention_target": target,
        "source": {field: str(source[field]) for field in sorted(_SOURCE_FIELDS)},
        "stratum": _validate_stratum(role, value["stratum"], morphology),
        "window": window.to_dict(),
    }


def gps_block_key(row: Mapping[str, Any], *, block_duration_s: int = 4096) -> str:
    window = WindowIdentity.from_dict(row["window"])
    if block_duration_s <= 0:
        raise ContractError("GPS block duration must be positive")
    return f"{window.detector}:{math.floor(window.gps_start / block_duration_s)}"


def _validate_row_set(
    rows: Sequence[Mapping[str, Any]], *, prior_block_keys: set[str]
) -> None:
    cohort_ids = [str(row["cohort_id"]) for row in rows]
    window_ids = [str(row["window"]["window_id"]) for row in rows]
    if len(cohort_ids) != len(set(cohort_ids)) or len(window_ids) != len(set(window_ids)):
        raise ContractError("v4 identity manifest contains duplicate identities")
    partition_blocks: dict[str, set[str]] = {partition: set() for partition in PARTITIONS}
    for row in rows:
        block = gps_block_key(row)
        if block in prior_block_keys:
            raise ContractError("v4 identity row overlaps a prior detector/GPS block")
        other = "confirmation" if row["partition"] == "development" else "development"
        if block in partition_blocks[other]:
            raise ContractError("v4 development and confirmation share a detector/GPS block")
        partition_blocks[str(row["partition"])].add(block)


def build_identity_manifest(
    rows: Iterable[Mapping[str, Any]],
    *,
    protocol_reference: Mapping[str, Any],
    source_references: Sequence[Mapping[str, Any]],
    selection_code_reference: Mapping[str, Any],
    seed_derivation: Mapping[str, Any],
    prior_block_keys: Iterable[str],
) -> dict[str, Any]:
    """Build an in-memory identity-only manifest; no final cohort is written here."""

    normalized = [validate_identity_row(row) for row in rows]
    normalized.sort(key=lambda row: (row["role"], row["cohort_id"]))
    if not normalized:
        raise ContractError("v4 identity manifest cannot be empty")
    prior = {str(value) for value in prior_block_keys}
    _validate_row_set(normalized, prior_block_keys=prior)
    if set(seed_derivation) != {"method", "protocol_id", "purposes", "parent_digests"}:
        raise ContractError("seed derivation contract is incomplete")
    if seed_derivation["method"] != "sha256_canonical_json_first_64_bits_big_endian":
        raise ContractError("v4 seeds must use the proposed deterministic derivation")
    references = [
        _reference(reference, f"source_references[{index}]")
        for index, reference in enumerate(source_references)
    ]
    if not references:
        raise ContractError("v4 identity manifest requires frozen source references")
    sorted_prior = sorted(prior)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "IDENTITY_ONLY_NOT_OPENED",
        "protocol_reference": _reference(protocol_reference, "protocol_reference"),
        "selection_code_reference": _reference(
            selection_code_reference, "selection_code_reference"
        ),
        "source_references": references,
        "seed_derivation": dict(seed_derivation),
        "prior_block_exclusions": {
            "count": len(prior),
            "digest": canonical_json_sha256(sorted_prior),
            "block_keys": sorted_prior,
        },
        "outcome_fields_present": [],
        "phase_features_extracted": [],
        "o4b_outcomes_used": [],
        "rows": normalized,
    }
    return {**body, "manifest_digest": canonical_json_sha256(body)}


def validate_identity_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(value)
    declared = body.pop("manifest_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v4 identity manifest digest mismatch")
    if body.get("status") != "IDENTITY_ONLY_NOT_OPENED":
        raise ContractError("v4 identity manifest is not sealed identity-only metadata")
    for field in ("outcome_fields_present", "phase_features_extracted", "o4b_outcomes_used"):
        if body.get(field) != []:
            raise ContractError(f"v4 identity manifest boundary violated: {field}")
    normalized = [validate_identity_row(row) for row in body["rows"]]
    if normalized != body["rows"]:
        raise ContractError("v4 identity manifest rows are not canonical")
    exclusions = body.get("prior_block_exclusions")
    if not isinstance(exclusions, dict) or set(exclusions) != {"count", "digest", "block_keys"}:
        raise ContractError("v4 prior-block exclusions are incomplete")
    block_keys = exclusions["block_keys"]
    if not isinstance(block_keys, list) or block_keys != sorted(set(str(key) for key in block_keys)):
        raise ContractError("v4 prior-block exclusion keys are not canonical")
    if exclusions["count"] != len(block_keys):
        raise ContractError("v4 prior-block exclusion count mismatch")
    if exclusions["digest"] != canonical_json_sha256(block_keys):
        raise ContractError("v4 prior-block exclusion digest mismatch")
    _validate_row_set(normalized, prior_block_keys=set(block_keys))
    return dict(value)


def _confirmation_identity_digest(manifest: Mapping[str, Any]) -> str:
    rows = [
        {
            "cohort_id": row["cohort_id"],
            "window_id": row["window"]["window_id"],
            "source_id": row["source"]["source_id"],
        }
        for row in manifest["rows"]
        if row["partition"] == "confirmation"
    ]
    if not rows:
        raise ContractError("confirmation seal requires confirmation identities")
    return canonical_json_sha256(rows)


def build_confirmation_seal(
    manifest: Mapping[str, Any],
    *,
    freeze_commit: str,
    code_references: Mapping[str, Mapping[str, Any]],
    declared_storage_roots: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    checked = validate_identity_manifest(manifest)
    commit = str(freeze_commit).lower()
    if _COMMIT.fullmatch(commit) is None:
        raise ContractError("confirmation seal requires a full Git commit")
    required_code = {
        "split_builder",
        "phase_extractor",
        "production_extractor",
        "preprocessing",
        "development_ledger",
        "development_screening",
        "development_verifier",
        "seal_verifier",
    }
    if set(code_references) != required_code:
        raise ContractError("confirmation seal code references are incomplete")
    roots: list[dict[str, str]] = []
    root_ids: set[str] = set()
    for index, root in enumerate(declared_storage_roots):
        if set(root) != {"root_id", "kind", "location"}:
            raise ContractError(f"declared storage root {index} is incomplete")
        kind = str(root["kind"])
        location = str(root["location"])
        root_id = str(root["root_id"])
        if kind not in {"repository_relative", "environment_alias"}:
            raise ContractError("storage root kind is not portable")
        if not root_id or root_id in root_ids or not location or "\\" in location:
            raise ContractError("declared storage root is invalid or duplicated")
        if kind == "repository_relative" and Path(location).is_absolute():
            raise ContractError("repository storage root must be relative")
        root_ids.add(root_id)
        roots.append({"root_id": root_id, "kind": kind, "location": location})
    if not roots:
        raise ContractError("confirmation seal requires declared storage roots")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "SEALED_NOT_OPENED",
        "freeze_commit": commit,
        "manifest_digest": checked["manifest_digest"],
        "confirmation_identity_digest": _confirmation_identity_digest(checked),
        "protocol_reference": checked["protocol_reference"],
        "code_references": {
            name: _reference(reference, f"code_references.{name}")
            for name, reference in sorted(code_references.items())
        },
        "declared_storage_roots": roots,
        "initial_access_log_sha256": EMPTY_ACCESS_LOG_SHA256,
        "access_entries_at_freeze": 0,
        "claim_boundary": "declared_storage_and_access_ledger_only",
    }
    return {**body, "seal_digest": canonical_json_sha256(body)}


def verify_unopened_seal(
    manifest: Mapping[str, Any],
    seal: Mapping[str, Any],
    *,
    access_log_bytes: bytes,
    observed_outcome_records: Iterable[Mapping[str, Any]] = (),
) -> None:
    checked = validate_identity_manifest(manifest)
    body = dict(seal)
    declared = body.pop("seal_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("confirmation seal digest mismatch")
    if seal.get("status") != "SEALED_NOT_OPENED":
        raise ContractError("confirmation is not in the unopened state")
    if seal.get("manifest_digest") != checked["manifest_digest"]:
        raise ContractError("confirmation seal/manifest mismatch")
    if seal.get("confirmation_identity_digest") != _confirmation_identity_digest(checked):
        raise ContractError("confirmation identity digest mismatch")
    if access_log_bytes or hashlib.sha256(access_log_bytes).hexdigest() != EMPTY_ACCESS_LOG_SHA256:
        raise ContractError("confirmation access log is not empty at freeze")
    confirmation_ids = {
        row["cohort_id"] for row in checked["rows"] if row["partition"] == "confirmation"
    }
    leaked = confirmation_ids.intersection(
        str(record.get("cohort_id")) for record in observed_outcome_records
    )
    if leaked:
        raise ContractError(f"confirmation outcome records already exist: {sorted(leaked)}")


def build_unlock_receipt(
    manifest: Mapping[str, Any],
    seal: Mapping[str, Any],
    development_result: Mapping[str, Any],
    *,
    access_log_bytes: bytes,
) -> dict[str, Any]:
    verify_unopened_seal(manifest, seal, access_log_bytes=access_log_bytes)
    required = {
        "status",
        "protocol_sha256",
        "manifest_digest",
        "phase_extractor_sha256",
        "model_digest",
        "threshold_digest",
        "verifier_digest",
    }
    if set(development_result) != required:
        raise ContractError("development result cannot authorize confirmation")
    if development_result["status"] != "READY_FOR_CONFIRMATION":
        raise ContractError("development did not authorize confirmation")
    expected = {
        "protocol_sha256": seal["protocol_reference"]["sha256"],
        "manifest_digest": seal["manifest_digest"],
        "phase_extractor_sha256": seal["code_references"]["phase_extractor"]["sha256"],
    }
    for field, value in expected.items():
        if development_result[field] != value:
            raise ContractError(f"development/seal mismatch: {field}")
    for field in ("model_digest", "threshold_digest", "verifier_digest"):
        _digest(development_result[field], field)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "CONFIRMATION_OPEN_ONCE",
        "seal_digest": seal["seal_digest"],
        "confirmation_identity_digest": seal["confirmation_identity_digest"],
        "development_result": dict(development_result),
    }
    return {**body, "receipt_digest": canonical_json_sha256(body)}


def require_partition_authorized(
    partition: str,
    *,
    seal: Mapping[str, Any] | None = None,
    unlock_receipt: Mapping[str, Any] | None = None,
) -> None:
    """Fail closed unless the requested v4 partition is authorized."""

    if partition == "development":
        return
    if partition != "confirmation":
        raise ContractError("v4 infrastructure cannot authorize O4b or unknown partitions")
    if seal is None or unlock_receipt is None:
        raise ContractError("confirmation requires a hash-bound unlock receipt")
    body = dict(unlock_receipt)
    declared = body.pop("receipt_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("confirmation unlock receipt digest mismatch")
    if unlock_receipt.get("status") != "CONFIRMATION_OPEN_ONCE":
        raise ContractError("confirmation unlock receipt has the wrong state")
    if unlock_receipt.get("seal_digest") != seal.get("seal_digest"):
        raise ContractError("confirmation unlock receipt is bound to another seal")


def append_access_record(path: str | Path, record: Mapping[str, Any]) -> dict[str, Any]:
    """Append one hash-chained access record without rewriting existing entries."""

    destination = Path(path)
    existing: list[dict[str, Any]] = []
    if destination.exists():
        for line in destination.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.append(json.loads(line))
    previous = EMPTY_ACCESS_LOG_SHA256
    for index, entry in enumerate(existing):
        body = dict(entry)
        declared = body.pop("record_digest", None)
        if body.get("sequence") != index or body.get("previous_digest") != previous:
            raise ContractError("confirmation access log chain is broken")
        if declared != canonical_json_sha256(body):
            raise ContractError("confirmation access log digest mismatch")
        previous = declared
    body = {
        "schema_version": SCHEMA_VERSION,
        "sequence": len(existing),
        "previous_digest": previous,
        **dict(record),
    }
    if "record_digest" in record:
        raise ContractError("access record cannot provide its own digest")
    entry = {**body, "record_digest": canonical_json_sha256(body)}
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(destination, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return entry


def claim_confirmation_open_once(
    path: str | Path,
    *,
    seal: Mapping[str, Any],
    unlock_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the receipt and atomically claim the one-shot open transition."""

    require_partition_authorized(
        "confirmation", seal=seal, unlock_receipt=unlock_receipt
    )
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    claim_path = destination.with_suffix(destination.suffix + ".open.claim")
    claim = {
        "seal_digest": seal["seal_digest"],
        "receipt_digest": unlock_receipt["receipt_digest"],
    }
    encoded_claim = (json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    try:
        descriptor = os.open(claim_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ContractError("confirmation extraction was already opened") from exc
    try:
        os.write(descriptor, encoded_claim)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return append_access_record(
        destination,
        {
            "action": "CONFIRMATION_EXTRACTION_STARTED",
            "seal_digest": seal["seal_digest"],
            "receipt_digest": unlock_receipt["receipt_digest"],
        },
    )
