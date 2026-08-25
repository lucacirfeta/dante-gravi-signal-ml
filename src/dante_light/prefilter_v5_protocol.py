"""Strict validation and portable references for the DANTE-Light v5 freeze."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_ID = "dante-light-l4-prefilter-v5-learned-surrogate"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repository_reference(root: Path, path: Path) -> dict[str, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ContractError("v5 references must remain inside the repository") from exc
    digest = sha256_path(resolved)
    try:
        unchanged = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", relative], cwd=root, check=False
        ).returncode == 0
        tracked = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{relative}"], cwd=root, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        if unchanged and tracked:
            digest = hashlib.sha256(
                subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=root)
            ).hexdigest()
    except (OSError, subprocess.SubprocessError):
        pass
    return {"path": relative, "sha256": digest}


def derive_seed(protocol_id: str, purpose: str, parent_digests: Sequence[str]) -> int:
    parents = sorted(str(value).lower() for value in parent_digests)
    if not purpose or any(_SHA256.fullmatch(value) is None for value in parents):
        raise ContractError("v5 seed derivation requires a purpose and SHA256 parents")
    payload = {"protocol_id": protocol_id, "purpose": purpose, "parent_digests": parents}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big", signed=False)


def protocol_digest(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("protocol_digest", None)
    return canonical_json_sha256(body)


def _reference(root: Path, value: Mapping[str, Any], label: str) -> Path:
    if set(value) != {"path", "sha256"} or Path(str(value["path"])).is_absolute():
        raise ContractError(f"invalid repository reference: {label}")
    path = root / str(value["path"])
    candidates = {sha256_path(path)} if path.is_file() else set()
    try:
        candidates.add(hashlib.sha256(subprocess.check_output(
            ["git", "show", f"HEAD:{value['path']}"], cwd=root,
            stderr=subprocess.DEVNULL,
        )).hexdigest())
    except (OSError, subprocess.SubprocessError):
        pass
    if value["sha256"] not in candidates:
        raise ContractError(f"v5 repository reference mismatch: {label}")
    return path


def validate_protocol(value: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    payload = dict(value)
    if payload.get("schema_version") != 5 or payload.get("status") != "FROZEN_OUTCOME_BLIND":
        raise ContractError("v5 protocol is not a frozen schema-v5 contract")
    if payload.get("protocol_id") != PROTOCOL_ID or payload.get("protocol_digest") != protocol_digest(payload):
        raise ContractError("v5 protocol id or self-digest mismatch")
    design_path = _reference(root, payload["design_reference"], "design")
    design = json.loads(design_path.read_text(encoding="utf-8"))
    if payload.get("approved_design") != design:
        raise ContractError("v5 protocol does not embed the referenced approved design exactly")
    _reference(root, payload["power_artifact_reference"], "power artifact")
    for name, reference in payload["source_references"].items():
        _reference(root, reference, f"source.{name}")
    boundary = design["scientific_boundary"]
    if boundary["development_outcomes_allowed"] or boundary["confirmation_outcomes_allowed"] or boundary["o4b_outcomes_allowed"] or boundary["routing_enabled"]:
        raise ContractError("v5 outcome-blind boundary was opened")
    if design["waveforms"]["aligned_tidal_nsbh_stress"]["neutron_star_aligned_spin"] != 0.0:
        raise ContractError("IMRPhenomNSBH requires the frozen chi_NS=0 contract")
    if design["confirmation"]["endpoint"] != "retention_fidelity_and_paired_cost_benefit":
        raise ContractError("v5 confirmation endpoint omits the approved cost-benefit gate")
    endpoints = set(design["confirmation"]["protected_endpoints"])
    required = {"protected_stratum_retention", "teacher_fidelity", "background_routing_decisions", "paired_prefilter_costs", "paired_avoidable_exact_path_costs", "block_bootstrap_net_saving"}
    if not required <= endpoints:
        raise ContractError("v5 confirmation seal scope is incomplete")
    counts = design["partition_contract"]["blocks_per_detector"]
    if any(int(counts[name]) <= 0 for name in ("training", "development", "confirmation")):
        raise ContractError("v5 block counts must be positive")
    if int(design["students"]["replicate_count"]) != len(payload["training_replicate_seeds"]):
        raise ContractError("v5 replicate seed count mismatch")
    parents = payload["seed_derivation"]["parent_digests"]
    purposes = design["seed_derivation"]["purposes"]
    expected = {purpose: derive_seed(PROTOCOL_ID, purpose, parents) for purpose in purposes}
    if payload["seed_derivation"]["seeds"] != expected:
        raise ContractError("v5 derived seeds do not reproduce")
    if payload["training_replicate_seeds"] != [expected[f"training_replicate_{index}"] for index in range(design["students"]["replicate_count"])]:
        raise ContractError("v5 training replicate ordering changed")
    return payload


def load_protocol(path: str | Path, *, root: Path = ROOT) -> dict[str, Any]:
    return validate_protocol(json.loads(Path(path).read_text(encoding="utf-8")), root=root)
