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


def _portable_reference_matches(
    root: Path, reference: Mapping[str, Any], label: str
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

    working = path.read_bytes()
    candidates = {hashlib.sha256(working).hexdigest()}
    try:
        blob = subprocess.check_output(
            ["git", "show", f"HEAD:{relative.as_posix()}"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        blob = None
    if blob is not None:
        normalized_working = working.replace(b"\r\n", b"\n")
        normalized_blob = blob.replace(b"\r\n", b"\n")
        if normalized_working == normalized_blob:
            candidates.add(hashlib.sha256(blob).hexdigest())
            if b"\x00" not in blob:
                crlf = normalized_blob.replace(b"\n", b"\r\n")
                candidates.add(hashlib.sha256(crlf).hexdigest())
    if str(reference["sha256"]) not in candidates:
        raise ContractError(f"v7 verification reference hash mismatch: {label}")
    return path


def load_training_authorization_for_verification(
    path: Path, *, root: Path
) -> dict[str, Any]:
    """Validate the frozen receipt without altering its execution semantics."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("authorization_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v7 training authorization digest mismatch")
    if payload.get("status") != "AUTHORIZED_TRAINING_ONLY":
        raise ContractError("v7 training is not explicitly authorized")

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
    for name, reference in payload.get("source_references", {}).items():
        _portable_reference_matches(root, reference, name)
    return payload

