"""Post-hoc diagnostics for a frozen, negative DANTE-Light L4 v2 screen."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v2_protocol import PrefilterProtocolV2
from src.dante_light.prefilter_v2_screening import (
    REQUIRED_ROLES,
    _block_groups,
    _combined_reduction,
    _feature_names,
    _fit_model,
    _load_ledger,
    _matrix,
    _positive_group,
    _sample_weights,
    _score_model,
    _select_threshold,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIAGNOSTIC_CONFIG = ROOT / "config" / "dante_light_prefilter_v2_diagnostics.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PrefilterV2DiagnosticConfig:
    path: Path
    payload: Mapping[str, Any]
    sha256: str

    @property
    def reference(self) -> dict[str, str]:
        return {
            "file_name": self.path.name,
            "sha256": self.sha256,
            "diagnostic_digest": str(self.payload["diagnostic_digest"]),
        }


def load_diagnostic_config(
    path: str | Path = DEFAULT_DIAGNOSTIC_CONFIG,
    *,
    protocol: PrefilterProtocolV2,
) -> PrefilterV2DiagnosticConfig:
    source = Path(path).resolve()
    try:
        raw = source.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v2 diagnostic config: {exc}") from exc
    if not isinstance(payload, dict):
        raise ContractError("v2 diagnostic config must be an object")
    body = dict(payload)
    if body.pop("diagnostic_digest", None) != canonical_json_sha256(body):
        raise ContractError("v2 diagnostic config digest mismatch")
    expected_fields = {
        "schema_version",
        "status",
        "parent_protocol",
        "uses_o4b_outcomes",
        "updates_frozen_screening",
        "eligible_for_pass_fail_gate",
        "auc",
        "regularization_sweep",
        "diagnostic_digest",
    }
    if set(payload) != expected_fields or payload["schema_version"] != 1:
        raise ContractError("v2 diagnostic config schema changed")
    if payload["status"] != "posthoc_diagnostic_only":
        raise ContractError("v2 diagnostic config status changed")
    if any(
        payload[field] is not False
        for field in (
            "uses_o4b_outcomes",
            "updates_frozen_screening",
            "eligible_for_pass_fail_gate",
        )
    ):
        raise ContractError("v2 diagnostic scientific boundary changed")
    expected_parent = {
        "path": "config/dante_light_prefilter_protocol_v2.json",
        "sha256": protocol.sha256,
        "protocol_digest": protocol.payload["protocol_digest"],
    }
    if payload["parent_protocol"] != expected_parent:
        raise ContractError("v2 diagnostic parent protocol changed")
    auc = payload.get("auc")
    if not isinstance(auc, dict) or auc.get("metric") != "unweighted_oof_roc_auc":
        raise ContractError("v2 diagnostic AUC definition changed")
    if auc.get("candidate_feature_sets") != protocol.payload["development"]["candidate_feature_sets"]:
        raise ContractError("v2 diagnostic candidate set changed")
    if any(
        auc.get(field) is not True
        for field in (
            "report_overall",
            "report_by_detector",
            "report_by_protected_stratum_against_same_detector_background",
        )
    ):
        raise ContractError("v2 diagnostic AUC reporting changed")
    sweep = payload.get("regularization_sweep")
    if not isinstance(sweep, dict) or sweep.get("candidate_feature_set") != "all":
        raise ContractError("v2 diagnostic regularization target changed")
    values = sweep.get("regularization_c_values")
    if not isinstance(values, list) or not values or any(float(value) <= 0.0 for value in values):
        raise ContractError("v2 diagnostic regularization grid is invalid")
    if len(values) != len(set(float(value) for value in values)):
        raise ContractError("v2 diagnostic regularization grid contains duplicates")
    if sweep.get("report_frozen_constrained_reduction_for_context") is not True:
        raise ContractError("v2 diagnostic context reporting changed")
    return PrefilterV2DiagnosticConfig(source, payload, hashlib.sha256(raw).hexdigest())


def _load_development(
    *,
    ledgers: Mapping[str, str | Path],
    expected_split_hashes: Mapping[str, str],
    protocol: PrefilterProtocolV2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    if set(ledgers) != REQUIRED_ROLES or set(expected_split_hashes) != REQUIRED_ROLES:
        raise ContractError("v2 diagnostics require exactly four development ledgers")
    feature_source = f"prefilter-v2:{protocol.payload['protocol_digest']}"
    source_records = []
    rows = []
    representations = set()
    for role, raw_path in sorted(ledgers.items()):
        path = Path(raw_path).resolve()
        ledger, role_rows = _load_ledger(path)
        split_hash = str(expected_split_hashes[role])
        if ledger.get("role") != role or ledger.get("feature_source") != feature_source:
            raise ContractError(f"v2 diagnostic ledger contract mismatch for {role}")
        if ledger.get("cohort_split_sha256_by_role") != {role: split_hash}:
            raise ContractError(f"v2 diagnostic split mismatch for {role}")
        representations.add(str(ledger["representation_sha256"]))
        source_records.append(
            {
                "role": role,
                "file_name": path.name,
                "sha256": _sha256(path),
                "rows_sha256": ledger["rows_sha256"],
                "role_split_sha256": split_hash,
            }
        )
        for row in role_rows:
            window = WindowIdentity.from_dict(row["window"])
            if row.get("partition") == "development":
                if window.run == "O4B":
                    raise ContractError("O4b row leaked into v2 diagnostics")
                if row.get("roles") != [role] or row.get("detector") != window.detector:
                    raise ContractError(f"v2 diagnostic annotation mismatch for {role}")
                rows.append(row)
    if len(representations) != 1:
        raise ContractError("v2 diagnostic ledgers use multiple representations")
    identities = [row["window"]["window_id"] for row in rows]
    if len(identities) != len(set(identities)):
        raise ContractError("v2 diagnostic development identities overlap")
    return rows, source_records, representations.pop()


def _oof_scores(
    rows: list[dict[str, Any]],
    *,
    names: tuple[str, ...],
    regularization_c: float,
    protocol: PrefilterProtocolV2,
) -> np.ndarray:
    rules = protocol.payload["development"]
    matrix = _matrix(rows, names)
    target = np.asarray([row.get("retention_target") is True for row in rows], dtype=int)
    weights = _sample_weights(rows)
    groups = _block_groups(rows, int(rules["gps_block_duration_s"]))
    scores = np.full(len(rows), np.nan, dtype=np.float64)
    splitter = GroupKFold(
        n_splits=int(rules["cross_validation_folds"]),
        shuffle=True,
        random_state=int(protocol.payload["cohort_split_seed"]),
    )
    for fold_index, (train, test) in enumerate(splitter.split(matrix, target, groups), 1):
        if len(np.unique(target[train])) != 2:
            raise ContractError(f"v2 diagnostic fold {fold_index} lacks a binary target")
        scaler, model = _fit_model(
            matrix[train],
            target[train],
            weights[train],
            regularization_c=float(regularization_c),
            maximum_iterations=int(rules["maximum_iterations"]),
            seed=int(protocol.payload["cohort_split_seed"]) + fold_index,
        )
        scores[test] = _score_model(scaler, model, matrix[test])
    if not np.all(np.isfinite(scores)):
        raise ContractError("v2 diagnostic OOF coverage is incomplete")
    return scores


def _auc_report(rows: list[dict[str, Any]], scores: np.ndarray) -> dict[str, Any]:
    target = np.asarray([row.get("retention_target") is True for row in rows], dtype=int)
    overall = float(roc_auc_score(target, scores))
    by_detector = {}
    for detector in sorted({str(row["detector"]) for row in rows}):
        indices = np.asarray([index for index, row in enumerate(rows) if row["detector"] == detector])
        by_detector[detector] = float(roc_auc_score(target[indices], scores[indices]))
    strata: dict[tuple[str, str, str], list[int]] = {}
    for index, row in enumerate(rows):
        if row.get("retention_target") is True:
            strata.setdefault(_positive_group(row), []).append(index)
    by_stratum = {}
    for (role, detector, morphology), positive_indices in sorted(strata.items()):
        background = [
            index
            for index, row in enumerate(rows)
            if row["detector"] == detector and row["roles"] == ["background"]
        ]
        indices = np.asarray([*background, *positive_indices])
        by_stratum[f"{role}/{detector}/{morphology}"] = {
            "positive_n": len(positive_indices),
            "background_n": len(background),
            "roc_auc": float(roc_auc_score(target[indices], scores[indices])),
        }
    return {"overall": overall, "by_detector": by_detector, "by_protected_stratum": by_stratum}


def _constrained_context(
    rows: list[dict[str, Any]],
    scores: np.ndarray,
    protocol: PrefilterProtocolV2,
) -> dict[str, Any]:
    rules = protocol.payload["development"]
    audit = protocol.payload["audit"]
    points = {
        detector: _select_threshold(
            rows,
            scores,
            detector=detector,
            rules=rules,
            audit_fraction=float(audit["fraction"]),
            audit_seed=int(audit["seed"]),
        )
        for detector in protocol.payload["required_detectors"]
    }
    retention_feasible = all(point is not None for point in points.values())
    reduction = _combined_reduction(points) if retention_feasible else None
    return {
        "retention_feasible": retention_feasible,
        "oof_effective_development_call_reduction": reduction,
        "meets_frozen_reduction_target": bool(
            retention_feasible
            and reduction >= float(rules["minimum_effective_reduction"])
        ),
    }


def diagnose_prefilter_v2(
    *,
    ledgers: Mapping[str, str | Path],
    expected_split_hashes: Mapping[str, str],
    frozen_screening_path: str | Path,
    protocol: PrefilterProtocolV2,
    diagnostic_config: PrefilterV2DiagnosticConfig,
) -> dict[str, Any]:
    """Compute post-hoc ranking diagnostics without updating the v2 gate."""

    rows, source_records, representation = _load_development(
        ledgers=ledgers,
        expected_split_hashes=expected_split_hashes,
        protocol=protocol,
    )
    screening_path = Path(frozen_screening_path).resolve()
    try:
        screening = json.loads(screening_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid frozen v2 screening artifact: {exc}") from exc
    body = dict(screening)
    if body.pop("artifact_digest", None) != canonical_json_sha256(body):
        raise ContractError("frozen v2 screening artifact digest mismatch")
    if (
        screening.get("status") != "NOT_READY"
        or screening.get("o4b_outcomes_used") != []
        or screening.get("routing_enabled") is not False
        or screening.get("protocol") != protocol.reference
        or screening.get("source_ledgers") != source_records
    ):
        raise ContractError("frozen v2 screening boundary or provenance changed")

    fixed_c = float(protocol.payload["development"]["regularization_c"])
    auc_candidates = []
    fixed_scores = {}
    for candidate in diagnostic_config.payload["auc"]["candidate_feature_sets"]:
        names = _feature_names(protocol, candidate)
        scores = _oof_scores(
            rows,
            names=names,
            regularization_c=fixed_c,
            protocol=protocol,
        )
        fixed_scores[candidate] = scores
        auc_candidates.append(
            {
                "feature_set": candidate,
                "regularization_c": fixed_c,
                "roc_auc": _auc_report(rows, scores),
                "frozen_constrained_context": _constrained_context(rows, scores, protocol),
            }
        )

    sweep = []
    all_names = _feature_names(protocol, "all")
    for raw_c in diagnostic_config.payload["regularization_sweep"]["regularization_c_values"]:
        value = float(raw_c)
        scores = fixed_scores["all"] if value == fixed_c else _oof_scores(
            rows,
            names=all_names,
            regularization_c=value,
            protocol=protocol,
        )
        sweep.append(
            {
                "regularization_c": value,
                "roc_auc": _auc_report(rows, scores),
                "frozen_constrained_context": _constrained_context(rows, scores, protocol),
            }
        )

    result = {
        "schema_version": 1,
        "status": "COMPLETE_DIAGNOSTIC_ONLY",
        "eligible_for_pass_fail_gate": False,
        "updates_frozen_screening": False,
        "routing_enabled": False,
        "o4b_outcomes_used": [],
        "protocol": protocol.reference,
        "diagnostic_config": diagnostic_config.reference,
        "frozen_screening": {
            "file_name": screening_path.name,
            "sha256": _sha256(screening_path),
            "artifact_digest": screening["artifact_digest"],
            "status": screening["status"],
        },
        "representation_sha256": representation,
        "cohort_split_sha256_by_role": dict(sorted(expected_split_hashes.items())),
        "source_ledgers": source_records,
        "development_n": len(rows),
        "auc_by_candidate": auc_candidates,
        "all_feature_regularization_sweep": sweep,
        "interpretation_boundary": (
            "Post-hoc descriptive ranking diagnostics only; values cannot revise the "
            "frozen v2 NOT_READY result or authorize O4b evaluation."
        ),
    }
    result["artifact_digest"] = canonical_json_sha256(result)
    return result


def write_diagnostic_result(result: Mapping[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination
