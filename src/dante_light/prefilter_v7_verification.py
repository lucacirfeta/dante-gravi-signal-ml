"""Portable verification helpers for completed DANTE-Light v7 evidence.

The original training authorization predates the canonical Git-blob helper
and records checkout-byte hashes.  This module verifies those immutable
receipts across LF/CRLF checkouts without changing the execution contract or
the hashes recorded at run time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v7_training_freeze import load_training_freeze


DEFAULT_REFERENCE_BRIDGE = (
    Path(__file__).resolve().parents[2]
    / "config/dante_light_prefilter_v7_reference_bridge.json"
)


def _portable_reference_matches(
    root: Path,
    reference: Mapping[str, Any],
    label: str,
    *,
    bridge_entry: Mapping[str, Any],
    basis_commit: str,
) -> Path:
    if set(reference) != {"path", "sha256"}:
        raise ContractError(f"v7 verification reference is malformed: {label}")
    relative_text = str(reference["path"])
    relative = Path(relative_text)
    if relative.is_absolute() or ".." in relative.parts or "\\" in relative_text:
        raise ContractError(f"v7 verification reference is not portable: {label}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError(f"v7 verification reference is absent: {label}")

    if (
        bridge_entry.get("path") != relative.as_posix()
        or bridge_entry.get("legacy_checkout_sha256") != reference["sha256"]
    ):
        raise ContractError(f"v7 verification bridge/reference mismatch: {label}")
    working = path.read_bytes()
    try:
        blob = subprocess.check_output(
            ["git", "show", f"{basis_commit}:{relative.as_posix()}"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"v7 verification basis blob is absent: {label}") from exc
    normalized_working = working.replace(b"\r\n", b"\n")
    normalized_blob = blob.replace(b"\r\n", b"\n")
    if (
        hashlib.sha256(blob).hexdigest() != bridge_entry.get("basis_blob_sha256")
        or hashlib.sha256(normalized_blob).hexdigest()
        != bridge_entry.get("normalized_lf_sha256")
        or hashlib.sha256(normalized_working).hexdigest()
        != bridge_entry.get("normalized_lf_sha256")
    ):
        raise ContractError(f"v7 verification reference hash mismatch: {label}")
    return path


def load_training_authorization_for_verification(
    path: Path,
    *,
    root: Path,
    bridge_path: Path | None = None,
) -> dict[str, Any]:
    """Validate the frozen receipt without altering its execution semantics."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("authorization_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v7 training authorization digest mismatch")
    if payload.get("status") != "AUTHORIZED_TRAINING_ONLY":
        raise ContractError("v7 training is not explicitly authorized")

    resolved_bridge = bridge_path or (
        root / "config/dante_light_prefilter_v7_reference_bridge.json"
    )
    bridge = json.loads(resolved_bridge.read_text(encoding="utf-8"))
    bridge_body = dict(bridge)
    bridge_digest = bridge_body.pop("bridge_digest", None)
    if bridge_digest != canonical_json_sha256(bridge_body):
        raise ContractError("v7 verification bridge digest mismatch")
    if (
        bridge.get("status") != "RETROSPECTIVE_LINE_ENDING_EQUIVALENCE_BRIDGE"
        or bridge.get("scope") != "verification_only_no_execution_or_artifact_mutation"
        or bridge.get("authorization_digest") != payload["authorization_digest"]
    ):
        raise ContractError("v7 verification bridge scope mismatch")

    contract = load_training_freeze(root=root)
    if payload.get("training_contract_digest") != contract["training_contract_digest"]:
        raise ContractError("v7 training authorization binds a different contract")
    if (
        payload.get("identity_assignment_digest")
        != contract["internal_split"]["assignment_digest"]
    ):
        raise ContractError("v7 training authorization binds a different split")
    if payload.get("allowed") != {
        "partition": "training",
        "teacher_scoring": True,
        "student_fit": True,
        "ensemble_members": 5,
    }:
        raise ContractError("v7 training authorization scope changed")
    if payload.get("forbidden") != {
        "threshold_search": [],
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
        "routing": False,
        "member_selection": False,
        "second_stage_distillation": False,
    }:
        raise ContractError("v7 protected-partition boundary widened")
    references = payload.get("source_references", {})
    if set(bridge.get("entries", {})) != set(references):
        raise ContractError("v7 verification bridge entry set mismatch")
    for name, reference in references.items():
        _portable_reference_matches(
            root,
            reference,
            name,
            bridge_entry=bridge["entries"][name],
            basis_commit=str(bridge["basis_commit"]),
        )
    return payload
