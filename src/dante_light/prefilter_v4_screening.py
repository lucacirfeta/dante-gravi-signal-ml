"""Fail-closed development screening for the frozen DANTE-Light L4 v4 primary."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import numpy as np
from sklearn.model_selection import GroupKFold

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v2_screening import (
    REQUIRED_ROLES,
    _block_groups,
    _combined_reduction,
    _fit_model,
    _sample_weights,
    _score_model,
    _select_threshold,
    _serialized_model,
)
from src.dante_light.prefilter_v3_screening import _auc_diagnostics
from src.dante_light.prefilter_v4_protocol import (
    PHASE_FEATURES,
    PrefilterProtocolV4,
    repository_reference,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sklearn_seed(seed: int) -> int:
    """Map the frozen unsigned 64-bit seed into sklearn's uint32 domain."""

    return int(seed) % (int(np.iinfo(np.uint32).max) + 1)


def _portable_numbers(value: Any) -> Any:
    """Canonicalize serialized floats without changing raw gate evaluation."""

    if isinstance(value, float):
        if not np.isfinite(value):
            raise ContractError("v4 result contains a non-finite float")
        return float(format(value, ".15g"))
    if isinstance(value, dict):
        return {key: _portable_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable_numbers(item) for item in value]
    if isinstance(value, tuple):
        return [_portable_numbers(item) for item in value]
    return value


def _v4_auc_diagnostics(
    rows: list[dict[str, Any]],
    target: np.ndarray,
    scores: np.ndarray,
    protocol: PrefilterProtocolV4,
) -> dict[str, Any]:
    """Reuse the audited bootstrap with the v4 development block contract."""

    payload = dict(protocol.payload)
    uncertainty = dict(payload["uncertainty"])
    block_duration = int(payload["development"]["gps_block_duration_s"])
    uncertainty["gps_block_duration_s"] = block_duration
    payload["uncertainty"] = uncertainty
    result = _auc_diagnostics(
        rows,
        target,
        scores,
        SimpleNamespace(payload=payload),
        candidate="phase_primary",
    )
    result["gps_block_duration_s"] = block_duration
    return result


def _load_development_ledger(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
        body = dict(ledger)
        if body.pop("ledger_digest", None) != canonical_json_sha256(body):
            raise ContractError(f"v4 feature ledger digest mismatch: {path}")
        rows_path = path.parent / str(ledger["rows_path"])
        if ledger.get("schema_version") != 4 or ledger.get("status") != "complete":
            raise ContractError(f"v4 development ledger is incomplete: {path}")
        if ledger.get("selection_limit") is not None:
            raise ContractError(f"v4 development ledger is limited: {path}")
        if ledger.get("selection_partitions") != ["development"]:
            raise ContractError(f"v4 ledger is not sealed to development: {path}")
        if ledger.get("confirmation_rows_accessed") != [] or ledger.get("o4b_rows_accessed") != []:
            raise ContractError(f"v4 protected partition access is recorded: {path}")
        if ledger.get("outcome_fields_used_for_feature_extraction") != []:
            raise ContractError(f"v4 feature extraction used outcome fields: {path}")
        if _sha256(rows_path) != ledger["rows_sha256"]:
            raise ContractError(f"v4 feature row SHA256 mismatch: {path}")
        rows = [
            json.loads(line)
            for line in rows_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v4 feature ledger {path}: {exc}") from exc
    if len(rows) != int(ledger["row_count"]):
        raise ContractError(f"v4 feature row count mismatch: {path}")
    if any(row.get("schema_version") != 4 for row in rows):
        raise ContractError(f"v4 feature row schema mismatch: {path}")
    if any(row.get("partition") != "development" for row in rows):
        raise ContractError(f"reserved confirmation row exposed to v4 development: {path}")
    return ledger, rows


def _matrix(rows: list[dict[str, Any]]) -> np.ndarray:
    matrix = np.empty((len(rows), len(PHASE_FEATURES)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        try:
            values = row["features"]["values"]
            if set(values) != set(PHASE_FEATURES):
                raise ContractError("v4 feature row schema mismatch")
            matrix[row_index] = [float(values[name]) for name in PHASE_FEATURES]
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("v4 feature row does not match the frozen schema") from exc
    if not np.all(np.isfinite(matrix)):
        raise ContractError("v4 feature matrix contains non-finite values")
    return matrix


def _expected_development_counts(protocol: PrefilterProtocolV4) -> Counter[tuple[str, str, str]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    contract = protocol.payload["cohort_contract"]["counts_per_detector_stratum"]
    for detector in protocol.payload["required_detectors"]:
        counts[("background", detector, "clean_background")] = int(contract["background"]["development"])
        for morphology in protocol.payload["required_morphologies_by_role"]["known_glitch"]:
            counts[("known_glitch", detector, morphology)] = int(contract["known_glitch"]["development"])
        for morphology in protocol.payload["required_morphologies_by_role"]["injection"]:
            counts[("injection", detector, morphology)] = int(contract["injection"]["development"])
    return counts


def screen_prefilter_v4(
    *,
    ledgers: Mapping[str, str | Path],
    protocol: PrefilterProtocolV4,
) -> dict[str, Any]:
    """Evaluate only the predeclared v4 primary on the development partition."""

    if set(ledgers) != REQUIRED_ROLES:
        raise ContractError("v4 screening requires exactly four frozen role ledgers")
    root = protocol.path.resolve().parents[1]
    protocol_reference = repository_reference(root, protocol.path)
    phase_reference = repository_reference(
        root, root / "src/dante_light/prefilter_v4_phase.py"
    )
    verifier_reference = repository_reference(
        root, root / "scripts/verify_dante_light_prefilter_v4_development.py"
    )
    source_records: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    manifest_digests: set[str] = set()
    feature_contracts: set[str] = set()
    protocol_references: list[dict[str, str]] = []
    for role, raw_path in sorted(ledgers.items()):
        path = Path(raw_path).resolve()
        ledger, rows = _load_development_ledger(path)
        if (
            ledger.get("role") != role
            or ledger.get("scientific_mode") != "v4_frozen_development_only_feature_extraction"
            or ledger.get("row_count") != ledger.get("expected_full_row_count")
        ):
            raise ContractError(f"v4 feature ledger contract mismatch for {role}")
        manifest_digests.add(str(ledger["manifest_digest"]))
        feature_contracts.add(str(ledger["feature_contract_sha256"]))
        protocol_references.append(dict(ledger["protocol"]))
        source_records.append(
            {
                "role": role,
                "file_name": path.name,
                "sha256": _sha256(path),
                "rows_sha256": ledger["rows_sha256"],
                "row_count": int(ledger["row_count"]),
                "selection_partitions": ["development"],
            }
        )
        for row in rows:
            window = WindowIdentity.from_dict(row["window"])
            if (
                row.get("detector") != window.detector
                or row.get("roles") != [role]
                or row.get("manifest_digest") != ledger["manifest_digest"]
                or row.get("feature_contract_sha256") != ledger["feature_contract_sha256"]
                or window.run == "O4B"
            ):
                raise ContractError(f"v4 feature row annotation mismatch in {role}")
            all_rows.append(row)
    if len(manifest_digests) != 1 or len(feature_contracts) != 1:
        raise ContractError("v4 ledgers do not share one frozen manifest/feature contract")
    if any(reference != protocol_references[0] for reference in protocol_references):
        raise ContractError("v4 ledgers do not share one protocol reference")
    if protocol_references[0] != protocol_reference:
        raise ContractError("v4 ledger protocol hash does not match the loaded protocol")
    expected_feature_contract = canonical_json_sha256(protocol.payload["feature_extraction"])
    if feature_contracts != {expected_feature_contract}:
        raise ContractError("v4 ledgers do not match the frozen feature contract")
    identities = [row["window"]["window_id"] for row in all_rows]
    if len(identities) != len(set(identities)):
        raise ContractError("v4 development ledgers overlap in window identity")
    observed_counts = Counter(
        (str(row["roles"][0]), str(row["detector"]), str(row["morphology"]))
        for row in all_rows
    )
    expected_counts = _expected_development_counts(protocol)
    robust_n = int(
        protocol.payload["cohort_contract"]["counts_per_detector_stratum"]
        ["robust_candidate"]["development"]
    )
    robust_morphologies = {
        detector: {
            morphology
            for role, row_detector, morphology in observed_counts
            if role == "robust_candidate" and row_detector == detector
        }
        for detector in protocol.payload["required_detectors"]
    }
    if any(len(values) != 1 for values in robust_morphologies.values()):
        raise ContractError("v4 robust development population has an unexpected morphology split")
    for detector, morphologies in robust_morphologies.items():
        expected_counts[("robust_candidate", detector, next(iter(morphologies)))] = robust_n
    if observed_counts != expected_counts:
        raise ContractError("v4 development per-stratum counts differ from the frozen contract")

    timings = np.asarray(
        [float(row["timings"]["feature_extraction_s"]) for row in all_rows],
        dtype=np.float64,
    )
    if not np.all(np.isfinite(timings)) or np.any(timings < 0.0):
        raise ContractError("v4 feature timing evidence is invalid")
    matrix = _matrix(all_rows)
    target = np.asarray([row.get("retention_target") is True for row in all_rows], dtype=int)
    weights = _sample_weights(all_rows)
    rules = protocol.payload["development"]
    groups = _block_groups(all_rows, int(rules["gps_block_duration_s"]))
    folds = int(rules["cross_validation_folds"])
    if len(set(groups)) < folds:
        raise ContractError("insufficient detector/GPS blocks for v4 cross-validation")
    seed = int(protocol.payload["audit"]["seed"])
    sklearn_seed = _sklearn_seed(seed)
    splitter = GroupKFold(n_splits=folds, shuffle=True, random_state=sklearn_seed)
    oof_scores = np.full(len(all_rows), np.nan, dtype=np.float64)
    fold_records: list[dict[str, int]] = []
    for fold_index, (train, test) in enumerate(splitter.split(matrix, target, groups), 1):
        if len(np.unique(target[train])) != 2:
            raise ContractError(f"v4 fold {fold_index} lacks a binary training target")
        scaler, model = _fit_model(
            matrix[train],
            target[train],
            weights[train],
            regularization_c=float(rules["regularization_c"]),
            maximum_iterations=int(rules["maximum_iterations"]),
            seed=_sklearn_seed(seed + fold_index),
        )
        oof_scores[test] = _score_model(scaler, model, matrix[test])
        fold_records.append(
            {
                "fold": fold_index,
                "train_n": int(len(train)),
                "validation_n": int(len(test)),
                "validation_block_n": int(len(set(groups[test]))),
            }
        )
    if not np.all(np.isfinite(oof_scores)):
        raise ContractError("v4 OOF prediction coverage is incomplete")
    audit = protocol.payload["audit"]
    detectors = tuple(protocol.payload["required_detectors"])
    oof_points = {
        detector: _select_threshold(
            all_rows,
            oof_scores,
            detector=detector,
            rules=rules,
            audit_fraction=float(audit["fraction"]),
            audit_seed=seed,
        )
        for detector in detectors
    }
    valid = all(point is not None for point in oof_points.values())
    oof_reduction = _combined_reduction(oof_points) if valid else None
    criteria_met = bool(
        valid
        and oof_reduction is not None
        and oof_reduction >= float(rules["minimum_effective_reduction"])
    )
    candidate = {
        "feature_set": "phase_primary",
        "feature_names": list(PHASE_FEATURES),
        "is_predeclared_primary": True,
        "eligible_for_selection": True,
        "development_criteria": "MET" if criteria_met else "NOT_MET",
        "oof_development_background_call_reduction": oof_reduction,
        "detectors": oof_points,
        "folds": fold_records,
        "auc_diagnostics": _v4_auc_diagnostics(
            all_rows, target, oof_scores, protocol
        ),
    }

    status = "V4_NOT_READY"
    selected: dict[str, Any] | None = None
    development_result: dict[str, Any] | None = None
    if criteria_met:
        final_models: dict[str, Any] = {}
        final_points: dict[str, Any] = {}
        for detector in detectors:
            indices = np.asarray(
                [index for index, row in enumerate(all_rows) if row["detector"] == detector],
                dtype=int,
            )
            detector_rows = [all_rows[index] for index in indices]
            scaler, model = _fit_model(
                matrix[indices],
                target[indices],
                _sample_weights(detector_rows),
                regularization_c=float(rules["regularization_c"]),
                maximum_iterations=int(rules["maximum_iterations"]),
                seed=sklearn_seed,
            )
            detector_scores = np.full(len(all_rows), np.nan, dtype=np.float64)
            detector_scores[indices] = _score_model(scaler, model, matrix[indices])
            point = _select_threshold(
                all_rows,
                detector_scores,
                detector=detector,
                rules=rules,
                audit_fraction=float(audit["fraction"]),
                audit_seed=seed,
            )
            if point is None:
                raise ContractError(f"v4 full-development calibration failed for {detector}")
            final_points[detector] = point
            final_models[detector] = _serialized_model(
                scaler, model, PHASE_FEATURES, point["threshold"]
            )
        final_reduction = _combined_reduction(final_points)
        if final_reduction >= float(rules["minimum_effective_reduction"]):
            status = "READY_FOR_CONFIRMATION"
            portable_models = _portable_numbers(final_models)
            portable_points = _portable_numbers(final_points)
            selected = {
                "feature_set": "phase_primary",
                "selection_basis": "predeclared_primary_only",
                "calibration_method": rules["final_calibration_method"],
                "oof_development_background_call_reduction": oof_reduction,
                "full_development_calibration_call_reduction": final_reduction,
                "detectors": portable_points,
                "models": portable_models,
            }
            development_result = {
                "status": status,
                "protocol_sha256": protocol_references[0]["sha256"],
                "manifest_digest": next(iter(manifest_digests)),
                "phase_extractor_sha256": phase_reference["sha256"],
                "model_digest": canonical_json_sha256(portable_models),
                "threshold_digest": canonical_json_sha256(portable_points),
                "verifier_digest": verifier_reference["sha256"],
            }

    result: dict[str, Any] = {
        "schema_version": 4,
        "status": status,
        "scientific_mode": "frozen_v4_development_only_before_one_shot_confirmation",
        "development_interpretation": "development_only_not_confirmatory",
        "routing_enabled": False,
        "o4b_outcomes_used": [],
        "confirmation_values_used": [],
        "can_authorize_operational_pass": False,
        "protocol": protocol_references[0],
        "manifest_digest": next(iter(manifest_digests)),
        "feature_contract_sha256": next(iter(feature_contracts)),
        "source_ledgers": source_records,
        "screening": {
            "cross_validation_method": rules["cross_validation_method"],
            "gps_block_duration_s": int(rules["gps_block_duration_s"]),
            "frozen_seed_uint64": seed,
            "sklearn_random_state_seed_uint32": sklearn_seed,
            "sklearn_seed_mapping": "uint64_modulo_2_pow_32",
            "folds": folds,
            "model": rules["model"],
            "class_weighting": rules["class_weighting"],
            "primary_feature_set": "phase_primary",
            "feature_subset_selection_allowed": False,
            "development_call_reduction_target": float(rules["minimum_effective_reduction"]),
            "candidate": candidate,
        },
        "feature_cost": {
            "development_n": int(timings.size),
            "feature_extraction_mean_s": float(np.mean(timings)),
            "feature_extraction_median_s": float(np.median(timings)),
            "feature_extraction_p95_s": float(np.quantile(timings, 0.95)),
            "feature_extraction_max_s": float(np.max(timings)),
            "excludes_data_read_and_whitening": True,
        },
        "selected_operating_point": selected,
        "unlock_authorization_material": development_result,
        "scientific_boundary": {
            "nsbh_injection_limitation": protocol.payload["scientific_boundary"]["nsbh_injection_limitation"],
            "does_not_establish": list(protocol.payload["scientific_boundary"]["does_not_establish"]),
        },
        "next_stage": (
            "await_explicit_authorization_before_creating_unlock_receipt_or_opening_confirmation"
            if status == "READY_FOR_CONFIRMATION"
            else "stop_without_opening_confirmation_or_o4b_and_do_not_retune_on_same_cohort"
        ),
        "portable_float_serialization": {
            "significant_digits": 15,
            "applied_after_unrounded_gate_evaluation": True,
        },
    }
    result = _portable_numbers(result)
    result["artifact_digest"] = canonical_json_sha256(result)
    return result


def write_screening_result(result: Mapping[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return destination


def load_screening_result(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    try:
        result = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v4 screening artifact {source}: {exc}") from exc
    body = dict(result)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v4 screening artifact digest mismatch")
    if (
        result.get("schema_version") != 4
        or result.get("status") not in {"V4_NOT_READY", "READY_FOR_CONFIRMATION"}
        or result.get("routing_enabled") is not False
        or result.get("o4b_outcomes_used") != []
        or result.get("confirmation_values_used") != []
        or result.get("can_authorize_operational_pass") is not False
    ):
        raise ContractError("v4 screening scientific boundary is invalid")
    return result


def verify_screening_result(
    saved_path: str | Path,
    *,
    ledgers: Mapping[str, str | Path],
    protocol: PrefilterProtocolV4,
) -> dict[str, Any]:
    saved = load_screening_result(saved_path)
    recomputed = screen_prefilter_v4(ledgers=ledgers, protocol=protocol)
    if saved != recomputed:
        raise ContractError("v4 screening artifact does not match exact recomputation")
    return {
        "status": "PASS",
        "scientific_status": saved["status"],
        "artifact_digest": saved["artifact_digest"],
        "routing_enabled": False,
        "o4b_outcomes_used": [],
        "confirmation_values_used": [],
    }
