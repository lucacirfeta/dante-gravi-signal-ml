"""Read-only local readiness audit for a future O3a-native reconstruction.

This module deliberately cannot freeze scientific choices.  It validates the
unresolved author-decision gate and reports local storage/reference state
without fetching DQ segments, selecting windows, or reading strain outcomes.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GATE = ROOT / "config/dante_o3a_native_v1_decision_gate.json"
REFERENCE_ARTIFACTS = ROOT / "config/reference_artifacts.json"

O3A_BOUNDS = [1238166018, 1253977218]
DETECTORS = ["H1", "L1"]
RECOMMENDATIONS = {
    "scope": "O3A_ONLY_COMPLETE_NATIVE_RECONSTRUCTION",
    "dq_semantics": "CBC_CAT1",
    "run_dependent_artifacts": "FRESH_O3A_ONLY",
    "multiscale": "DIAGNOSTIC_ONLY_DEFERRED",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_decision_gate(path: str | Path = DEFAULT_GATE) -> dict[str, Any]:
    """Load the checked-in unresolved gate and reject accidental promotion."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ContractError(f"cannot read O3a decision gate {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("O3a decision gate must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ContractError("unsupported O3a decision-gate schema")
    if payload.get("status") != "AUTHOR_DECISION_REQUIRED":
        raise ContractError("O3a gate is not the unresolved author-decision record")
    if payload.get("run") != "O3A":
        raise ContractError("O3a decision gate run mismatch")
    if payload.get("official_run_bounds_gps") != O3A_BOUNDS:
        raise ContractError("O3a official bounds changed")
    if payload.get("detectors") != DETECTORS:
        raise ContractError("O3a detector scope changed")
    if payload.get("outcome_data_accessed") is not False:
        raise ContractError("O3a decision gate is not outcome-blind")
    if payload.get("execution_allowed") is not False:
        raise ContractError("unresolved O3a gate cannot authorize execution")
    if payload.get("recommendations") != RECOMMENDATIONS:
        raise ContractError("O3a recommendations changed without review")
    decisions = payload.get("author_decisions")
    if not isinstance(decisions, dict) or set(decisions) != set(RECOMMENDATIONS):
        raise ContractError("O3a author-decision fields are incomplete")
    if any(value is not None for value in decisions.values()):
        raise ContractError(
            "author decisions must remain unresolved in the read-only gate"
        )
    storage = payload.get("storage")
    if not isinstance(storage, dict):
        raise ContractError("O3a storage recommendation is missing")
    if storage.get("primary_scan_raw_cache") != 0:
        raise ContractError("O3a primary scan must not retain a raw mirror")
    return payload


def _git(root: Path, *arguments: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *arguments],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _storage_state(cache_root: str | Path) -> dict[str, Any]:
    raw_text = str(cache_root)
    if os.name != "nt" and len(raw_text) >= 2 and raw_text[1] == ":":
        return {
            "configured_root": raw_text,
            "available_on_host": False,
            "reason": "windows_path_unavailable_on_this_host",
        }
    path = Path(cache_root).expanduser().resolve()
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    if not probe.exists():
        return {
            "configured_root": str(path),
            "available_on_host": False,
            "reason": "no_existing_parent_for_capacity_probe",
        }
    usage = shutil.disk_usage(probe)
    raw_files = []
    if path.is_dir():
        raw_files = [
            item
            for item in path.rglob("*")
            if item.is_file() and item.suffix.lower() in {".hdf5", ".h5", ".gwf"}
        ]
    return {
        "configured_root": str(path),
        "available_on_host": True,
        "root_exists": path.is_dir(),
        "capacity_probe_path": str(probe),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "raw_file_count": len(raw_files),
        "raw_bytes": sum(item.stat().st_size for item in raw_files),
    }


def _reference_state(root: Path) -> dict[str, Any]:
    payload = json.loads((root / REFERENCE_ARTIFACTS.relative_to(ROOT)).read_text())
    indices: dict[str, Any] = {}
    for name, record in payload["reference_indices"].items():
        path = root / record["path"]
        present = path.is_file()
        observed = _sha256_file(path) if present else None
        indices[name] = {
            "path": record["path"],
            "present": present,
            "expected_sha256": record["sha256"],
            "observed_sha256": observed,
            "verified": present and observed == record["sha256"],
        }
    return {
        "bundle_url": payload["reference_bundle"]["url"],
        "bundle_sha256": payload["reference_bundle"]["sha256"],
        "indices": indices,
    }


def audit_local_readiness(
    *,
    root: str | Path = ROOT,
    gate_path: str | Path = DEFAULT_GATE,
    cache_root: str | Path | None = None,
) -> dict[str, Any]:
    """Report local prerequisites without data/outcome access or mutation."""
    root_path = Path(root).resolve()
    gate = load_decision_gate(gate_path)
    selected_cache = cache_root or gate["storage"]["windows_cache_root"]
    tracked_status = _git(root_path, "status", "--porcelain", "--untracked-files=no")
    body = {
        "schema_version": 1,
        "status": "AUTHOR_DECISION_REQUIRED",
        "run": "O3A",
        "official_run_bounds_gps": O3A_BOUNDS,
        "detectors": DETECTORS,
        "read_only": True,
        "network_accessed": False,
        "dq_segments_accessed": False,
        "strain_or_outcomes_accessed": False,
        "execution_authorized": False,
        "unresolved_author_decisions": sorted(RECOMMENDATIONS),
        "gate_sha256": _sha256_file(Path(gate_path)),
        "git": {
            "commit": _git(root_path, "rev-parse", "HEAD"),
            "branch": _git(root_path, "branch", "--show-current"),
            "tracked_clean": tracked_status == "",
        },
        "storage": _storage_state(selected_cache),
        "references": _reference_state(root_path),
    }
    return {**body, "audit_sha256": canonical_json_sha256(body)}
