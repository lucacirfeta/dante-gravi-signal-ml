"""Fail-closed held-out evaluation for a frozen DANTE-Light L4 v2 model."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_evaluation import wilson_interval
from src.dante_light.prefilter_v2 import PrefilterFeaturesV2, feature_names_by_family
from src.dante_light.prefilter_v2_protocol import load_prefilter_v2_protocol


SCHEMA_VERSION = 2
ALLOWED_ROLES = {"shadow", "robust_candidate", "known_glitch", "injection"}
CONTROL_ROLES = {"robust_candidate", "known_glitch", "injection"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError(f"JSON artifact is not an object: {path}")
    return payload


def _rows(path: Path) -> list[dict[str, Any]]:
    try:
        values = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v2 evaluation rows {path}: {exc}") from exc
    if not values or not all(isinstance(value, dict) for value in values):
        raise ContractError("v2 evaluation rows must be non-empty JSON objects")
    return values


def _local_member(parent: Path, relative: Any, label: str) -> Path:
    candidate = Path(str(relative))
    if candidate.is_absolute():
        raise ContractError(f"{label} must be relative to its manifest")
    root = parent.resolve()
    resolved = (root / candidate).resolve()
    if resolved != root and root not in resolved.parents:
        raise ContractError(f"{label} escapes its manifest directory")
    return resolved


def _validate_digest(payload: Mapping[str, Any], field: str, label: str) -> None:
    body = dict(payload)
    declared = body.pop(field, None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"{label} digest mismatch")


def _audit_selected(seed: int, fraction: float, window_id: str) -> bool:
    digest = hashlib.sha256(f"{seed}:{window_id}".encode("ascii")).digest()
    uniform = int.from_bytes(digest[:8], "big") / float(2**64)
    return uniform < fraction


def _score_model(model: Mapping[str, Any], values: Mapping[str, Any]) -> float:
    try:
        names = tuple(str(name) for name in model["feature_names"])
        mean = np.asarray(model["scaler_mean"], dtype=np.float64)
        scale = np.asarray(model["scaler_scale"], dtype=np.float64)
        coefficient = np.asarray(model["coefficient"], dtype=np.float64)
        intercept = float(model["intercept"])
        vector = np.asarray([float(values[name]) for name in names], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("invalid serialized v2 prefilter model") from exc
    arrays = (mean, scale, coefficient, vector)
    if not names or any(array.shape != (len(names),) for array in arrays):
        raise ContractError("serialized v2 model dimensions differ")
    if any(not np.all(np.isfinite(array)) for array in arrays) or not math.isfinite(intercept):
        raise ContractError("serialized v2 model contains non-finite values")
    if np.any(scale <= 0.0):
        raise ContractError("serialized v2 scaler has non-positive scale")
    logit = float(np.dot(coefficient, (vector - mean) / scale) + intercept)
    if logit >= 0.0:
        return float(1.0 / (1.0 + math.exp(-logit)))
    exponential = math.exp(logit)
    return float(exponential / (1.0 + exponential))


def _matches(row: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    for key, expected in filters.items():
        if key == "role":
            if expected not in row["roles"]:
                return False
        elif row.get(key) != expected:
            return False
    return True


def _required_groups(protocol: Any) -> list[dict[str, Any]]:
    evaluation = protocol.payload["evaluation"]
    detectors = protocol.payload["required_detectors"]
    morphologies = protocol.payload["required_morphologies_by_role"]
    rules = []
    for detector in detectors:
        role = "robust_candidate"
        rules.append(
            {
                "name": f"{role}_{detector}",
                "filters": {"role": role, "detector": detector, "retention_target": True},
                "minimum_n": int(evaluation["minimum_group_n_by_role"][role]),
                "minimum_retention": float(evaluation["minimum_retention_by_role"][role]),
                "minimum_wilson_lower": float(evaluation["minimum_wilson_lower_by_role"][role]),
            }
        )
    for role in ("known_glitch", "injection"):
        for detector in detectors:
            for morphology in morphologies[role]:
                rules.append(
                    {
                        "name": f"{role}_{detector}_{morphology}",
                        "filters": {
                            "role": role,
                            "detector": detector,
                            "morphology": morphology,
                            "retention_target": True,
                        },
                        "minimum_n": int(evaluation["minimum_group_n_by_role"][role]),
                        "minimum_retention": float(evaluation["minimum_retention_by_role"][role]),
                        "minimum_wilson_lower": float(evaluation["minimum_wilson_lower_by_role"][role]),
                    }
                )
    return rules


def _validate_contract(contract: Mapping[str, Any], protocol: Any, parent: Path) -> None:
    _validate_digest(contract, "contract_digest", "v2 evaluation contract")
    if contract.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported v2 evaluation contract schema")
    if contract.get("status") != "locked_before_evaluation":
        raise ContractError("v2 evaluation contract was not locked")
    expected_source = f"prefilter-v2:{protocol.payload['protocol_digest']}"
    if contract.get("feature_source") != expected_source:
        raise ContractError("v2 evaluation feature source changed")
    protocol_reference = contract.get("protocol_artifact", {})
    expected_protocol = {
        "path": protocol.path.name,
        "sha256": protocol.sha256,
        "protocol_id": protocol.payload["protocol_id"],
        "protocol_digest": protocol.payload["protocol_digest"],
    }
    if protocol_reference != expected_protocol:
        raise ContractError("v2 evaluation protocol binding changed")
    evaluation = protocol.payload["evaluation"]
    expected_scalars = {
        "minimum_compute_reduction": float(evaluation["minimum_compute_reduction"]),
        "minimum_exact_escalates": int(evaluation["minimum_exact_escalates"]),
        "wilson_confidence": float(evaluation["wilson_confidence"]),
        "audit_fraction": float(protocol.payload["audit"]["fraction"]),
        "audit_seed": int(protocol.payload["audit"]["seed"]),
    }
    if any(contract.get(key) != value for key, value in expected_scalars.items()):
        raise ContractError("v2 evaluation gates differ from the frozen protocol")
    detectors = protocol.payload["required_detectors"]
    if contract.get("required_detectors") != detectors:
        raise ContractError("v2 evaluation detector set changed")
    if set(contract.get("models_by_detector", {})) != set(detectors):
        raise ContractError("v2 evaluation detector models are incomplete")
    if set(contract.get("evaluation_start_gps_by_detector", {})) != set(detectors):
        raise ContractError("v2 evaluation start GPS is incomplete")
    if contract.get("required_morphologies_by_role") != protocol.payload["required_morphologies_by_role"]:
        raise ContractError("v2 evaluation morphology grid changed")
    split_hashes = contract.get("cohort_split_sha256_by_role")
    if not isinstance(split_hashes, dict) or set(split_hashes) != ALLOWED_ROLES:
        raise ContractError("v2 evaluation split bindings are incomplete")
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in split_hashes.values()
    ):
        raise ContractError("v2 evaluation split digest is invalid")
    if contract.get("required_groups") != _required_groups(protocol):
        raise ContractError("v2 evaluation retention groups are incomplete")
    screening_record = contract.get("screening_artifact")
    if not isinstance(screening_record, dict) or set(screening_record) != {"path", "sha256"}:
        raise ContractError("v2 evaluation screening binding is incomplete")
    screening_path = _local_member(parent, screening_record["path"], "v2 screening path")
    if _sha256(screening_path) != screening_record["sha256"]:
        raise ContractError("v2 screening artifact SHA256 mismatch")
    screening = _json(screening_path)
    _validate_digest(screening, "artifact_digest", "v2 screening artifact")
    if (
        screening.get("status") != "PASS"
        or screening.get("protocol") != protocol.reference
        or screening.get("routing_enabled") is not False
        or screening.get("o4b_outcomes_used") != []
    ):
        raise ContractError("v2 screening artifact is not an outcome-blind PASS")
    selected = screening.get("selected_operating_point")
    if not isinstance(selected, dict) or contract.get("models_by_detector") != selected.get("models"):
        raise ContractError("v2 evaluation models differ from frozen screening")
    expected_feature_names = {
        name
        for names in feature_names_by_family(protocol.payload["feature_extraction"]).values()
        for name in names
    }
    model_names = []
    for detector in detectors:
        model = contract["models_by_detector"][detector]
        names = model.get("feature_names") if isinstance(model, dict) else None
        if not isinstance(names, list) or not names or len(names) != len(set(names)):
            raise ContractError(f"v2 model feature names are invalid for {detector}")
        if not set(names).issubset(expected_feature_names):
            raise ContractError(f"v2 model feature names changed for {detector}")
        model_names.append(names)
    if any(names != model_names[0] for names in model_names[1:]):
        raise ContractError("v2 detector models use different feature sets")


def evaluate_prefilter_v2(
    *, contract_path: str | Path, ledger_path: str | Path
) -> dict[str, Any]:
    """Evaluate O4b and frozen controls without changing production routing."""

    contract_path = Path(contract_path).resolve()
    ledger_path = Path(ledger_path).resolve()
    contract = _json(contract_path)
    ledger = _json(ledger_path)
    protocol_record = contract.get("protocol_artifact", {})
    protocol_path = _local_member(
        contract_path.parent, protocol_record.get("path"), "v2 protocol path"
    )
    protocol = load_prefilter_v2_protocol(protocol_path)
    _validate_contract(contract, protocol, contract_path.parent)
    _validate_digest(ledger, "ledger_digest", "v2 evaluation ledger")
    if ledger.get("schema_version") != SCHEMA_VERSION or ledger.get("status") != "complete":
        raise ContractError("v2 evaluation ledger is incomplete")
    if ledger.get("feature_source") != contract["feature_source"]:
        raise ContractError("v2 evaluation ledger feature source changed")
    if ledger.get("outcome_fields_used_for_threshold_selection") != []:
        raise ContractError("O4b outcomes entered v2 threshold selection")
    if ledger.get("protocol_artifact") != contract["protocol_artifact"]:
        raise ContractError("v2 evaluation ledger protocol binding changed")
    if ledger.get("screening_artifact") != contract.get("screening_artifact"):
        raise ContractError("v2 evaluation ledger screening binding changed")
    if ledger.get("representation_sha256") != contract.get("representation_sha256"):
        raise ContractError("v2 evaluation representation changed")
    if ledger.get("cohort_split_sha256_by_role") != contract.get("cohort_split_sha256_by_role"):
        raise ContractError("v2 evaluation split bindings changed")
    rows_path = _local_member(ledger_path.parent, ledger.get("rows_path"), "v2 rows path")
    if _sha256(rows_path) != ledger.get("rows_sha256"):
        raise ContractError("v2 evaluation row SHA256 mismatch")
    rows = _rows(rows_path)
    if len(rows) != int(ledger.get("row_count", -1)):
        raise ContractError("v2 evaluation row count mismatch")

    expected_names = {
        name
        for names in feature_names_by_family(protocol.payload["feature_extraction"]).values()
        for name in names
    }
    starts = {
        detector: float(value)
        for detector, value in contract["evaluation_start_gps_by_detector"].items()
    }
    seen: set[str] = set()
    evaluated: list[dict[str, Any]] = []
    for row in rows:
        window = WindowIdentity.from_dict(row["window"])
        if window.window_id in seen:
            raise ContractError(f"duplicate v2 evaluation identity: {window.window_id}")
        seen.add(window.window_id)
        roles = row.get("roles")
        if not isinstance(roles, list) or not roles or any(role not in ALLOWED_ROLES for role in roles):
            raise ContractError(f"invalid v2 roles for {window.window_id}")
        if row.get("partition") != "evaluation" or row.get("detector") != window.detector:
            raise ContractError(f"invalid v2 evaluation annotation for {window.window_id}")
        if not isinstance(row.get("retention_target"), bool):
            raise ContractError(f"invalid v2 retention target for {window.window_id}")
        if row.get("representation_sha256") != contract["representation_sha256"]:
            raise ContractError(f"v2 representation mismatch for {window.window_id}")
        strain_digest = str(row.get("strain_sha256", ""))
        if len(strain_digest) != 64 or any(
            character not in "0123456789abcdef" for character in strain_digest
        ):
            raise ContractError(f"invalid v2 strain digest for {window.window_id}")
        if row.get("split_artifact_sha256_by_role") != {
            role: contract["cohort_split_sha256_by_role"][role] for role in roles
        }:
            raise ContractError(f"v2 split mismatch for {window.window_id}")
        if "shadow" in roles and (
            window.run != "O4B" or window.gps_start < starts[window.detector]
        ):
            raise ContractError(f"v2 shadow row is outside the frozen O4b epoch: {window.window_id}")
        exact = row.get("exact_disposition")
        if exact not in ({"ESCALATE", "NOT_ESCALATED"} if "shadow" in roles else {"NOT_APPLICABLE"}):
            raise ContractError(f"invalid v2 exact disposition for {window.window_id}")
        features = PrefilterFeaturesV2(**row["features"])
        if set(features.values) != expected_names:
            raise ContractError(f"v2 feature schema changed for {window.window_id}")
        model = contract["models_by_detector"][window.detector]
        score = _score_model(model, features.values)
        threshold = float(model["probability_threshold"])
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ContractError("invalid v2 probability threshold")
        selected = score >= threshold
        audited = (not selected) and _audit_selected(
            int(contract["audit_seed"]), float(contract["audit_fraction"]), window.window_id
        )
        evaluated.append({**row, "window": window, "score": score, "selected": selected, "audited": audited})

    group_results = []
    gates = []
    for rule in contract["required_groups"]:
        members = [row for row in evaluated if _matches(row, rule["filters"])]
        retained = sum(bool(row["selected"]) for row in members)
        n = len(members)
        lower, upper = (
            wilson_interval(retained, n, confidence=float(contract["wilson_confidence"]))
            if n
            else (0.0, 0.0)
        )
        retention = retained / n if n else 0.0
        passed = (
            n >= int(rule["minimum_n"])
            and retention >= float(rule["minimum_retention"])
            and lower >= float(rule["minimum_wilson_lower"])
        )
        group_results.append(
            {
                "name": rule["name"],
                "filters": rule["filters"],
                "n": n,
                "retained": retained,
                "retention": float(retention),
                "wilson_interval": {
                    "confidence": float(contract["wilson_confidence"]),
                    "bounds": [float(lower), float(upper)],
                },
                "status": "PASS" if passed else "FAIL",
            }
        )
        gates.append({"name": f"retention:{rule['name']}", "status": "PASS" if passed else "FAIL"})

    shadow = [row for row in evaluated if "shadow" in row["roles"]]
    if not shadow:
        raise ContractError("v2 evaluation contains no O4b shadow rows")
    calls = sum(bool(row["selected"] or row["audited"]) for row in shadow)
    reduction = 1.0 - calls / len(shadow)
    gates.append(
        {
            "name": "effective_compute_reduction",
            "status": "PASS" if reduction >= float(contract["minimum_compute_reduction"]) else "FAIL",
        }
    )
    exact_positives = [row for row in shadow if row["exact_disposition"] == "ESCALATE"]
    missed = [row for row in exact_positives if not row["selected"]]
    exact_pass = len(exact_positives) >= int(contract["minimum_exact_escalates"]) and not missed
    gates.append({"name": "exact_escalate_retention", "status": "PASS" if exact_pass else "FAIL"})
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if all(gate["status"] == "PASS" for gate in gates) else "NOT_READY",
        "scientific_mode": "research_only_prefilter_v2_heldout_evaluation",
        "routing_enabled": False,
        "contract": {"path": contract_path.as_posix(), "sha256": _sha256(contract_path)},
        "feature_ledger": {
            "path": ledger_path.as_posix(),
            "sha256": _sha256(ledger_path),
            "rows_path": rows_path.as_posix(),
            "rows_sha256": _sha256(rows_path),
        },
        "coverage": {
            "windows": len(evaluated),
            "shadow_windows": len(shadow),
            "would_call_dino": int(calls),
            "effective_compute_reduction": float(reduction),
            "exact_escalates": len(exact_positives),
            "missed_exact_escalates": len(missed),
            "audited_missed_exact_escalates": sum(bool(row["audited"]) for row in missed),
        },
        "retention_groups": group_results,
        "gates": gates,
    }
    result["result_digest"] = canonical_json_sha256(result)
    return result


def write_result_v2(result: Mapping[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
