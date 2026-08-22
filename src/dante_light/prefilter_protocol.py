"""Versioned scientific protocol for DANTE-Light L4 prefilter evaluation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL_PATH = ROOT / "config" / "dante_light_prefilter_protocol_v1.json"
SCHEMA_VERSION = 1
CONTROL_ROLES = ("robust_candidate", "known_glitch", "injection")


@dataclass(frozen=True)
class PrefilterProtocol:
    path: Path
    payload: Mapping[str, Any]
    sha256: str

    @property
    def reference(self) -> dict[str, str]:
        return {
            "file_name": self.path.name,
            "sha256": self.sha256,
            "protocol_id": str(self.payload["protocol_id"]),
            "protocol_digest": str(self.payload["protocol_digest"]),
        }


def _fraction(value: Any, label: str, *, positive: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ContractError(f"{label} must be a finite fraction")
    if positive and result <= 0.0:
        raise ContractError(f"{label} must be positive")
    return result


def _positive_int(value: Any, label: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{label} must be an integer >= {minimum}")
    return value


def _role_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(CONTROL_ROLES):
        raise ContractError(f"{label} must define exactly {list(CONTROL_ROLES)}")
    return value


def validate_prefilter_protocol(payload: Mapping[str, Any]) -> None:
    required_fields = {
        "schema_version",
        "status",
        "protocol_id",
        "cohort_split_seed",
        "required_detectors",
        "required_morphologies_by_role",
        "audit",
        "tuning",
        "evaluation",
        "protocol_digest",
    }
    if set(payload) != required_fields:
        raise ContractError("prefilter protocol fields are incomplete or unexpected")
    body = dict(payload)
    declared = body.pop("protocol_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("prefilter protocol digest mismatch")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported prefilter protocol schema")
    if payload.get("status") != "frozen" or not payload.get("protocol_id"):
        raise ContractError("prefilter protocol must be frozen and identified")
    _positive_int(payload["cohort_split_seed"], "cohort_split_seed", minimum=0)

    detectors = payload.get("required_detectors")
    if not isinstance(detectors, list) or not detectors or len(detectors) != len(set(detectors)):
        raise ContractError("required_detectors must be a non-empty unique list")
    if any(detector not in {"H1", "L1"} for detector in detectors):
        raise ContractError("prefilter protocol supports only H1/L1")

    morphologies = payload.get("required_morphologies_by_role")
    if not isinstance(morphologies, dict) or set(morphologies) != {"known_glitch", "injection"}:
        raise ContractError("known-glitch and injection morphology grids are required")
    for role, values in morphologies.items():
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise ContractError(f"{role} morphologies must be non-empty and unique")

    audit = payload.get("audit")
    if not isinstance(audit, dict) or set(audit) != {"fraction", "seed"}:
        raise ContractError("audit protocol requires fraction and seed")
    _fraction(audit["fraction"], "audit.fraction", positive=True)
    _positive_int(audit["seed"], "audit.seed", minimum=0)

    tuning = payload.get("tuning")
    required_tuning = {
        "grid_cells",
        "minimum_development_retention",
        "minimum_effective_reduction",
        "minimum_background_per_detector",
        "minimum_group_n_by_role",
    }
    if not isinstance(tuning, dict) or set(tuning) != required_tuning:
        raise ContractError("tuning protocol fields are incomplete")
    _positive_int(tuning["grid_cells"], "tuning.grid_cells", minimum=2)
    _fraction(tuning["minimum_development_retention"], "tuning.minimum_development_retention")
    _fraction(tuning["minimum_effective_reduction"], "tuning.minimum_effective_reduction")
    _positive_int(tuning["minimum_background_per_detector"], "tuning.minimum_background_per_detector")
    for role, value in _role_mapping(
        tuning["minimum_group_n_by_role"], "tuning.minimum_group_n_by_role"
    ).items():
        _positive_int(value, f"tuning.minimum_group_n_by_role.{role}")

    evaluation = payload.get("evaluation")
    required_evaluation = {
        "minimum_compute_reduction",
        "minimum_exact_escalates",
        "wilson_confidence",
        "minimum_retention_by_role",
        "minimum_wilson_lower_by_role",
        "minimum_group_n_by_role",
    }
    if not isinstance(evaluation, dict) or set(evaluation) != required_evaluation:
        raise ContractError("evaluation protocol fields are incomplete")
    _fraction(evaluation["minimum_compute_reduction"], "evaluation.minimum_compute_reduction")
    _positive_int(evaluation["minimum_exact_escalates"], "evaluation.minimum_exact_escalates")
    _fraction(evaluation["wilson_confidence"], "evaluation.wilson_confidence", positive=True)
    for field in ("minimum_retention_by_role", "minimum_wilson_lower_by_role"):
        for role, value in _role_mapping(evaluation[field], f"evaluation.{field}").items():
            _fraction(value, f"evaluation.{field}.{role}")
    for role, value in _role_mapping(
        evaluation["minimum_group_n_by_role"], "evaluation.minimum_group_n_by_role"
    ).items():
        _positive_int(value, f"evaluation.minimum_group_n_by_role.{role}")


def load_prefilter_protocol(
    path: str | Path = DEFAULT_PROTOCOL_PATH,
) -> PrefilterProtocol:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid prefilter protocol {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("prefilter protocol root must be an object")
    validate_prefilter_protocol(payload)
    return PrefilterProtocol(
        path=source,
        payload=payload,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
