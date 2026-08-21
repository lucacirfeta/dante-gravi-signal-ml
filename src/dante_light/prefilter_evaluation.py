"""Fail-closed evaluation of a research-only DANTE-Light prefilter.

This module measures a frozen prefilter contract against feature rows produced
from the canonical whitened strain.  It deliberately does not promote a
prefilter or alter :mod:`src.dante_light.runner` selection.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter import ExcessEnergyFeatures, PrefilterContract


SCHEMA_VERSION = 1
FEATURE_SOURCE = "canonical_whitened_subwindow_v1"
ALLOWED_ROLES = {"shadow", "robust_candidate", "known_glitch", "injection"}
REQUIRED_SCIENTIFIC_ROLES = {"robust_candidate", "known_glitch", "injection"}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite_fraction(value: Any, name: str) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ContractError(f"{name} must be a finite fraction")
    return result


def wilson_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Return a two-sided Wilson score interval without a SciPy dependency."""

    if n <= 0 or not 0 <= k <= n:
        raise ContractError("Wilson interval requires 0 <= k <= n and n > 0")
    confidence = _finite_fraction(confidence, "confidence")
    if confidence <= 0.0:
        raise ContractError("confidence must be positive")
    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    p = k / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"JSON root must be an object: {path}")
    return payload


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractError(f"cannot read feature rows {path}: {exc}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid JSON at {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise ContractError(f"feature row must be an object at {path}:{line_number}")
        rows.append(row)
    if not rows:
        raise ContractError("feature ledger contains no rows")
    return rows


def _local_member(parent: Path, relative: Any, label: str) -> Path:
    candidate = Path(str(relative))
    if candidate.is_absolute():
        raise ContractError(f"{label} must be relative to its manifest")
    root = parent.resolve()
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ContractError(f"{label} escapes its manifest directory")
    return resolved


def _require_sha256(value: Any, label: str) -> str:
    digest = str(value).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ContractError(f"{label} must be a lowercase SHA256")
    return digest


def _validate_contract(payload: Mapping[str, Any]) -> None:
    body = dict(payload)
    declared_digest = body.pop("contract_digest", None)
    if declared_digest != canonical_json_sha256(body):
        raise ContractError("evaluation contract digest mismatch")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported prefilter evaluation contract schema")
    if payload.get("status") != "locked_before_evaluation":
        raise ContractError("evaluation contract was not locked before evaluation")
    if payload.get("feature_source") != FEATURE_SOURCE:
        raise ContractError("evaluation requires canonical whitened feature source")
    if not payload.get("contract_id"):
        raise ContractError("evaluation contract requires contract_id")
    if _finite_fraction(payload["minimum_compute_reduction"], "minimum_compute_reduction") < 0.5:
        raise ContractError("L4 requires at least 50% effective compute reduction")
    if int(payload.get("minimum_exact_escalates", 0)) < 18:
        raise ContractError("L4 requires at least 18 exact escalates")
    _require_sha256(payload.get("representation_sha256"), "representation_sha256")
    audit_fraction = _finite_fraction(payload["audit_fraction"], "audit_fraction")
    if audit_fraction <= 0.0:
        raise ContractError("L4 requires a non-zero rejected-window audit")
    cutoffs = payload.get("evaluation_start_gps_by_detector")
    if not isinstance(cutoffs, dict) or not cutoffs:
        raise ContractError("evaluation start GPS is required per detector")
    for detector, value in cutoffs.items():
        WindowIdentity(run="TEST", detector=detector, gps_start=float(value))
    detectors = payload.get("required_detectors")
    if not isinstance(detectors, list) or set(detectors) != set(cutoffs):
        raise ContractError("required_detectors must match evaluation GPS detectors")
    morphologies = payload.get("required_morphologies_by_role")
    if not isinstance(morphologies, dict) or set(morphologies) != {"known_glitch", "injection"}:
        raise ContractError("known-glitch and injection morphology grids are required")
    for role, values in morphologies.items():
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise ContractError(f"{role} morphologies must be non-empty and unique")
    split_hashes = payload.get("cohort_split_sha256_by_role")
    if not isinstance(split_hashes, dict) or set(split_hashes) != ALLOWED_ROLES:
        raise ContractError("every evaluation role requires a frozen split artifact")
    for role, digest in split_hashes.items():
        _require_sha256(digest, f"split artifact for {role}")
    rules = payload.get("required_groups")
    if not isinstance(rules, list) or not rules:
        raise ContractError("at least one required retention group is needed")
    names: set[str] = set()
    covered_roles: set[str] = set()
    for rule in rules:
        name = str(rule.get("name", ""))
        if not name or name in names:
            raise ContractError("required group names must be non-empty and unique")
        names.add(name)
        if int(rule.get("minimum_n", 0)) < 18:
            raise ContractError(f"group {name} minimum_n must be at least 18")
        if _finite_fraction(rule["minimum_retention"], f"{name}.minimum_retention") < 0.9:
            raise ContractError(f"group {name} minimum retention must be at least 0.9")
        if _finite_fraction(rule["minimum_wilson_lower"], f"{name}.minimum_wilson_lower") < 0.8:
            raise ContractError(f"group {name} Wilson lower bound must be at least 0.8")
        filters = rule.get("filters")
        if not isinstance(filters, dict) or not filters:
            raise ContractError(f"group {name} requires explicit filters")
        if filters.get("role") in REQUIRED_SCIENTIFIC_ROLES:
            covered_roles.add(filters["role"])
    missing_roles = REQUIRED_SCIENTIFIC_ROLES - covered_roles
    if missing_roles:
        raise ContractError(f"required scientific roles are not gated: {sorted(missing_roles)}")
    filters = [rule["filters"] for rule in rules]
    required_filters = [
        {"role": "robust_candidate", "detector": detector, "retention_target": True}
        for detector in detectors
    ]
    required_filters.extend(
        {
            "role": role,
            "detector": detector,
            "morphology": morphology,
            "retention_target": True,
        }
        for role, values in morphologies.items()
        for detector in detectors
        for morphology in values
    )
    missing_filters = [expected for expected in required_filters if expected not in filters]
    if missing_filters:
        raise ContractError(f"detector/morphology retention gates are missing: {missing_filters}")


def _validate_ledger(
    payload: Mapping[str, Any], rows_path: Path, tuning_path: Path, contract: Mapping[str, Any]
) -> None:
    body = dict(payload)
    declared_digest = body.pop("ledger_digest", None)
    if declared_digest != canonical_json_sha256(body):
        raise ContractError("feature-ledger digest mismatch")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported feature-ledger schema")
    if payload.get("status") != "complete":
        raise ContractError("feature ledger is incomplete")
    if payload.get("feature_source") != FEATURE_SOURCE:
        raise ContractError("feature ledger does not use canonical whitened features")
    if payload.get("outcome_fields_used_for_threshold_selection") != []:
        raise ContractError("evaluation outcomes were used for threshold selection")
    if payload.get("rows_sha256") != _sha256_file(rows_path):
        raise ContractError("feature row SHA256 mismatch")
    if int(payload.get("row_count", -1)) <= 0:
        raise ContractError("feature ledger row count must be positive")
    if payload.get("representation_sha256") != contract.get("representation_sha256"):
        raise ContractError("feature ledger representation is not bound to the contract")
    if payload.get("cohort_split_sha256_by_role") != contract.get("cohort_split_sha256_by_role"):
        raise ContractError("feature ledger cohort splits are not bound to the contract")
    tuning = payload.get("threshold_tuning_artifact")
    expected = contract.get("threshold_tuning_artifact")
    if tuning != expected or not isinstance(tuning, dict):
        raise ContractError("threshold-tuning artifact is not bound to the contract")
    digest = _require_sha256(tuning.get("sha256"), "threshold-tuning artifact")
    if not tuning_path.is_file() or _sha256_file(tuning_path) != digest:
        raise ContractError("threshold-tuning artifact SHA256 mismatch")


def _row_features(row: Mapping[str, Any]) -> ExcessEnergyFeatures:
    try:
        return ExcessEnergyFeatures(**row["features"])
    except (KeyError, TypeError) as exc:
        raise ContractError("invalid prefilter feature row") from exc


def _matches(row: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    for key, expected in filters.items():
        if key == "role":
            if expected not in row["roles"]:
                return False
        elif row.get(key) != expected:
            return False
    return True


def evaluate_prefilter(
    *, contract_path: str | Path, ledger_path: str | Path
) -> dict[str, Any]:
    """Evaluate a locked contract; return PASS only when every gate passes."""

    contract_path = Path(contract_path)
    ledger_path = Path(ledger_path)
    contract = _load_json(contract_path)
    ledger = _load_json(ledger_path)
    _validate_contract(contract)
    rows_path = _local_member(ledger_path.parent, ledger["rows_path"], "rows_path")
    tuning = ledger.get("threshold_tuning_artifact", {})
    tuning_path = _local_member(ledger_path.parent, tuning.get("path"), "threshold tuning path")
    _validate_ledger(ledger, rows_path, tuning_path, contract)
    rows = _load_rows(rows_path)
    if len(rows) != int(ledger["row_count"]):
        raise ContractError("feature ledger row count mismatch")

    prefilter = PrefilterContract(
        contract_id=str(contract["contract_id"]),
        status="research_only",
        crest_threshold=float(contract["crest_threshold"]),
        band_fraction_threshold=float(contract["band_fraction_threshold"]),
        audit_fraction=float(contract["audit_fraction"]),
        seed=int(contract["audit_seed"]),
    )
    starts = {key: float(value) for key, value in contract["evaluation_start_gps_by_detector"].items()}
    seen: set[str] = set()
    evaluated: list[dict[str, Any]] = []
    for row in rows:
        window = WindowIdentity.from_dict(row["window"])
        if window.window_id in seen:
            raise ContractError(f"duplicate feature identity: {window.window_id}")
        seen.add(window.window_id)
        roles = row.get("roles")
        if not isinstance(roles, list) or not roles or any(role not in ALLOWED_ROLES for role in roles):
            raise ContractError(f"invalid roles for {window.window_id}")
        if row.get("partition") != "evaluation":
            raise ContractError(f"row is not in a frozen evaluation partition: {window.window_id}")
        row_splits = row.get("split_artifact_sha256_by_role")
        if not isinstance(row_splits, dict) or set(row_splits) != set(roles):
            raise ContractError(f"row split bindings do not match roles: {window.window_id}")
        for role in roles:
            if row_splits[role] != contract["cohort_split_sha256_by_role"][role]:
                raise ContractError(f"row split artifact mismatch for {window.window_id}:{role}")
        if "shadow" in roles and (
            window.detector not in starts or window.gps_start < starts[window.detector]
        ):
            raise ContractError(f"shadow row is not in the locked later epoch: {window.window_id}")
        exact = row.get("exact_disposition")
        allowed_exact = (
            {"ESCALATE", "NOT_ESCALATED"}
            if "shadow" in roles
            else {"NOT_APPLICABLE"}
        )
        if exact not in allowed_exact:
            raise ContractError(f"invalid exact disposition for {window.window_id}")
        if not isinstance(row.get("retention_target"), bool):
            raise ContractError(f"retention_target is not boolean for {window.window_id}")
        if row.get("representation_sha256") != contract["representation_sha256"]:
            raise ContractError(f"representation mismatch for {window.window_id}")
        if row.get("detector") != window.detector:
            raise ContractError(f"detector annotation mismatch for {window.window_id}")
        _require_sha256(row.get("strain_sha256"), f"strain_sha256 for {window.window_id}")
        selected = prefilter.would_escalate(_row_features(row))
        audited = (not selected) and prefilter.audit_selected(window)
        evaluated.append({**row, "window": window, "selected": selected, "audited": audited})

    group_results: list[dict[str, Any]] = []
    gates: list[dict[str, Any]] = []
    for rule in contract["required_groups"]:
        members = [row for row in evaluated if _matches(row, rule["filters"])]
        retained = sum(bool(row["selected"]) for row in members)
        n = len(members)
        lower, upper = wilson_interval(retained, n) if n else (0.0, 0.0)
        rate = retained / n if n else 0.0
        passed = (
            n >= int(rule["minimum_n"])
            and rate >= float(rule["minimum_retention"])
            and lower >= float(rule["minimum_wilson_lower"])
        )
        result = {
            "name": rule["name"],
            "filters": rule["filters"],
            "n": n,
            "retained": retained,
            "retention": rate,
            "wilson_ci95": [lower, upper],
            "status": "PASS" if passed else "FAIL",
        }
        group_results.append(result)
        gates.append({"name": f"retention:{rule['name']}", "status": result["status"]})

    shadow_rows = [row for row in evaluated if "shadow" in row["roles"]]
    if not shadow_rows:
        raise ContractError("evaluation ledger contains no later shadow rows")
    calls = sum(row["selected"] or row["audited"] for row in shadow_rows)
    reduction = 1.0 - calls / len(shadow_rows)
    reduction_pass = reduction >= float(contract["minimum_compute_reduction"])
    gates.append({"name": "effective_compute_reduction", "status": "PASS" if reduction_pass else "FAIL"})
    exact_positives = [
        row
        for row in evaluated
        if "shadow" in row["roles"] and row["exact_disposition"] == "ESCALATE"
    ]
    missed = [row for row in exact_positives if not row["selected"]]
    audited_misses = sum(row["audited"] for row in missed)
    exact_gate = len(exact_positives) >= int(contract["minimum_exact_escalates"]) and not missed
    gates.append({"name": "exact_escalate_retention", "status": "PASS" if exact_gate else "FAIL"})
    final_status = "PASS" if all(gate["status"] == "PASS" for gate in gates) else "NOT_READY"
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": final_status,
        "scientific_mode": "research_only_prefilter_evaluation",
        "routing_enabled": False,
        "contract": {
            "path": contract_path.as_posix(),
            "sha256": _sha256_file(contract_path),
            "contract_digest": canonical_json_sha256(contract),
        },
        "feature_ledger": {
            "path": ledger_path.as_posix(),
            "sha256": _sha256_file(ledger_path),
            "rows_path": rows_path.as_posix(),
            "rows_sha256": _sha256_file(rows_path),
        },
        "coverage": {
            "windows": len(evaluated),
            "shadow_windows": len(shadow_rows),
            "would_call_dino": calls,
            "effective_compute_reduction": reduction,
            "exact_escalates": len(exact_positives),
            "missed_exact_escalates": len(missed),
            "audited_missed_exact_escalates": audited_misses,
        },
        "retention_groups": group_results,
        "gates": gates,
    }
    result["result_digest"] = canonical_json_sha256(result)
    return result


def write_result(result: Mapping[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return destination
