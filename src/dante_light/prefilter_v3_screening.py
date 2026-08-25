"""Fail-closed development screening for the frozen DANTE-Light L4 v3 A+B design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_v2_screening import (
    REQUIRED_ROLES,
    _block_groups,
    _combined_reduction,
    _fit_model,
    _positive_group,
    _sample_weights,
    _score_model,
    _select_threshold,
    _serialized_model,
)
from src.dante_light.prefilter_v3 import feature_names_by_family
from src.dante_light.prefilter_v3_protocol import PrefilterProtocolV3


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_development_ledger(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
        body = dict(ledger)
        if body.pop("ledger_digest", None) != canonical_json_sha256(body):
            raise ContractError(f"v3 feature ledger digest mismatch: {path}")
        rows_path = path.parent / str(ledger["rows_path"])
        if ledger.get("status") != "complete" or ledger.get("schema_version") != 3:
            raise ContractError(f"v3 development feature ledger is not complete: {path}")
        if ledger.get("selection_limit") is not None:
            raise ContractError(f"v3 development ledger is limited: {path}")
        if ledger.get("selection_partitions") != ["development"]:
            raise ContractError(f"v3 ledger is not sealed to development: {path}")
        if ledger.get("outcome_fields_used_for_feature_extraction") != []:
            raise ContractError(f"v3 feature extraction used outcome fields: {path}")
        if _sha256(rows_path) != ledger["rows_sha256"]:
            raise ContractError(f"v3 feature row SHA256 mismatch: {path}")
        rows = [
            json.loads(line)
            for line in rows_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v3 feature ledger {path}: {exc}") from exc
    if len(rows) != int(ledger["row_count"]):
        raise ContractError(f"v3 feature row count mismatch: {path}")
    if any(row.get("schema_version") != 3 for row in rows):
        raise ContractError(f"v3 feature row schema mismatch: {path}")
    if any(row.get("partition") != "development" for row in rows):
        raise ContractError(f"reserved confirmation row exposed to v3 development: {path}")
    return ledger, rows


def _feature_names(protocol: PrefilterProtocolV3, candidate: str) -> tuple[str, ...]:
    families = feature_names_by_family(protocol.payload["feature_extraction"])
    if candidate == "signed_plus_ridge":
        return (*families["signed_ordering"], *families["ridge_consistency"])
    try:
        return families[candidate]
    except KeyError as exc:
        raise ContractError(f"unknown v3 feature candidate: {candidate}") from exc


def _matrix(rows: list[dict[str, Any]], names: tuple[str, ...]) -> np.ndarray:
    matrix = np.empty((len(rows), len(names)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        try:
            values = row["features"]["values"]
            matrix[row_index] = [float(values[name]) for name in names]
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("v3 feature row does not match frozen feature schema") from exc
    if not np.all(np.isfinite(matrix)):
        raise ContractError("v3 feature matrix contains non-finite values")
    return matrix


def _bootstrap_seed(base_seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{base_seed}:{label}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _block_bootstrap_auc(
    target: np.ndarray,
    scores: np.ndarray,
    blocks: np.ndarray,
    *,
    n_resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, Any]:
    if len(np.unique(target)) != 2:
        raise ContractError("block-bootstrap AUC requires a binary target")
    unique_blocks = np.unique(blocks)
    if unique_blocks.size < 2:
        raise ContractError("block-bootstrap AUC requires at least two detector/GPS blocks")
    indices_by_block = {block: np.flatnonzero(blocks == block) for block in unique_blocks}
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(n_resamples):
        sampled = rng.choice(unique_blocks, size=unique_blocks.size, replace=True)
        indices = np.concatenate([indices_by_block[block] for block in sampled])
        if len(np.unique(target[indices])) != 2:
            continue
        values.append(float(roc_auc_score(target[indices], scores[indices])))
    minimum_success = max(1, int(np.ceil(0.9 * n_resamples)))
    if len(values) < minimum_success:
        raise ContractError(
            f"block-bootstrap AUC produced too few binary resamples: {len(values)}/{n_resamples}"
        )
    alpha = (1.0 - confidence) / 2.0
    return {
        "auc": float(roc_auc_score(target, scores)),
        "confidence_interval": [
            float(np.quantile(values, alpha)),
            float(np.quantile(values, 1.0 - alpha)),
        ],
        "method": "detector_gps_block_bootstrap",
        "block_n": int(unique_blocks.size),
        "requested_resamples": int(n_resamples),
        "successful_resamples": int(len(values)),
        "eligible_for_gate": False,
    }


def _auc_diagnostics(
    rows: list[dict[str, Any]],
    target: np.ndarray,
    scores: np.ndarray,
    protocol: PrefilterProtocolV3,
    *,
    candidate: str,
) -> dict[str, Any]:
    uncertainty = protocol.payload["uncertainty"]
    block_duration = int(uncertainty["gps_block_duration_s"])
    blocks = _block_groups(rows, block_duration)
    n_resamples = int(uncertainty["n_resamples"])
    confidence = float(uncertainty["confidence"])
    base_seed = int(uncertainty["seed"])
    overall = _block_bootstrap_auc(
        target,
        scores,
        blocks,
        n_resamples=n_resamples,
        confidence=confidence,
        seed=_bootstrap_seed(base_seed, f"{candidate}:overall"),
    )
    strata = []
    positive_groups = sorted(
        {_positive_group(row) for row in rows if row.get("retention_target") is True}
    )
    for role, detector, morphology in positive_groups:
        indices = np.asarray(
            [
                index
                for index, row in enumerate(rows)
                if row["detector"] == detector
                and (
                    row["roles"] == ["background"]
                    or (
                        row["roles"] == [role]
                        and row["morphology"] == morphology
                        and row.get("retention_target") is True
                    )
                )
            ],
            dtype=int,
        )
        subset_target = target[indices]
        subset_scores = scores[indices]
        subset_blocks = blocks[indices]
        record = _block_bootstrap_auc(
            subset_target,
            subset_scores,
            subset_blocks,
            n_resamples=n_resamples,
            confidence=confidence,
            seed=_bootstrap_seed(base_seed, f"{candidate}:{role}:{detector}:{morphology}"),
        )
        record.update(
            {
                "role": role,
                "detector": detector,
                "morphology": morphology,
                "background_n": int(np.sum(subset_target == 0)),
                "positive_n": int(np.sum(subset_target == 1)),
            }
        )
        strata.append(record)
    return {
        "interpretation": "exploratory_hypothesis_generating_not_confirmatory",
        "overall": overall,
        "by_protected_stratum": strata,
    }


def screen_prefilter_v3(
    *,
    ledgers: Mapping[str, str | Path],
    protocol: PrefilterProtocolV3,
) -> dict[str, Any]:
    """Screen only frozen A+B for readiness to open the reserved positive cohort."""

    if set(ledgers) != REQUIRED_ROLES:
        raise ContractError("v3 screening requires exactly four frozen role ledgers")
    expected_hashes = dict(protocol.payload["parent_v2"]["split"]["role_split_sha256"])
    expected_split_file_sha256 = str(protocol.payload["parent_v2"]["split"]["sha256"])
    feature_source = f"prefilter-v3:{protocol.payload['protocol_digest']}"
    source_records = []
    all_rows: list[dict[str, Any]] = []
    representation_hashes = set()
    for role, raw_path in sorted(ledgers.items()):
        path = Path(raw_path).resolve()
        ledger, rows = _load_development_ledger(path)
        split_hash = expected_hashes[role]
        source_split = ledger.get("source_split", {})
        if (
            ledger.get("role") != role
            or ledger.get("feature_source") != feature_source
            or ledger.get("scientific_mode")
            != "v3_hypothesis_generating_development_feature_extraction"
            or ledger.get("cohort_split_sha256_by_role") != {role: split_hash}
            or source_split.get("sha256") != expected_split_file_sha256
            or source_split.get("role_split_sha256") != split_hash
        ):
            raise ContractError(f"v3 feature ledger contract mismatch for {role}")
        representation_hashes.add(str(ledger["representation_sha256"]))
        source_records.append(
            {
                "role": role,
                "path": path.as_posix(),
                "sha256": _sha256(path),
                "rows_sha256": ledger["rows_sha256"],
                "role_split_sha256": split_hash,
                "selection_partitions": ["development"],
            }
        )
        for row in rows:
            window = WindowIdentity.from_dict(row["window"])
            if (
                row.get("detector") != window.detector
                or row.get("roles") != [role]
                or row.get("split_artifact_sha256_by_role") != {role: split_hash}
            ):
                raise ContractError(f"v3 feature row annotation mismatch in {role}")
            if window.run == "O4B":
                raise ContractError("O4b development outcome leakage")
            all_rows.append(row)
    if len(representation_hashes) != 1:
        raise ContractError("v3 ledgers use multiple exact representations")
    identities = [row["window"]["window_id"] for row in all_rows]
    if len(identities) != len(set(identities)):
        raise ContractError("v3 development ledgers overlap in window identity")

    timings = np.asarray(
        [float(row["timings"]["feature_extraction_s"]) for row in all_rows],
        dtype=np.float64,
    )
    if not np.all(np.isfinite(timings)) or np.any(timings < 0.0):
        raise ContractError("v3 feature timing evidence is invalid")
    rules = protocol.payload["development"]
    detectors = tuple(protocol.payload["required_detectors"])
    for detector in detectors:
        background_n = sum(
            row["roles"] == ["background"] and row["detector"] == detector
            for row in all_rows
        )
        if background_n < int(rules["minimum_background_per_detector"]):
            raise ContractError(f"underpowered v3 background for {detector}: {background_n}")

    weights = _sample_weights(all_rows)
    target = np.asarray([row.get("retention_target") is True for row in all_rows], dtype=int)
    groups = _block_groups(all_rows, int(rules["gps_block_duration_s"]))
    folds = int(rules["cross_validation_folds"])
    if len(set(groups)) < folds:
        raise ContractError("insufficient independent GPS blocks for v3 cross-validation")
    audit = protocol.payload["audit"]
    candidates = []
    primary_name = str(rules["primary_feature_set"])
    for candidate_name in rules["ablation_feature_sets"]:
        names = _feature_names(protocol, str(candidate_name))
        matrix = _matrix(all_rows, names)
        oof_scores = np.full(len(all_rows), np.nan, dtype=np.float64)
        fold_records = []
        splitter = GroupKFold(
            n_splits=folds,
            shuffle=True,
            random_state=int(protocol.payload["audit"]["seed"]),
        )
        for fold_index, (train, test) in enumerate(splitter.split(matrix, target, groups), 1):
            if len(np.unique(target[train])) != 2:
                raise ContractError(f"v3 fold {fold_index} lacks a binary training target")
            scaler, model = _fit_model(
                matrix[train],
                target[train],
                weights[train],
                regularization_c=float(rules["regularization_c"]),
                maximum_iterations=int(rules["maximum_iterations"]),
                seed=int(protocol.payload["audit"]["seed"]) + fold_index,
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
            raise ContractError("v3 OOF prediction coverage is incomplete")
        points = {
            detector: _select_threshold(
                all_rows,
                oof_scores,
                detector=detector,
                rules=rules,
                audit_fraction=float(audit["fraction"]),
                audit_seed=int(audit["seed"]),
            )
            for detector in detectors
        }
        valid = all(point is not None for point in points.values())
        reduction = _combined_reduction(points) if valid else None
        criteria_met = bool(
            valid and reduction is not None and reduction >= float(rules["minimum_effective_reduction"])
        )
        candidates.append(
            {
                "feature_set": candidate_name,
                "feature_names": list(names),
                "is_predeclared_primary": candidate_name == primary_name,
                "eligible_for_selection": candidate_name == primary_name,
                "development_criteria": "MET" if criteria_met else "NOT_MET",
                "oof_development_background_call_reduction": reduction,
                "detectors": points,
                "folds": fold_records,
                "auc_diagnostics": _auc_diagnostics(
                    all_rows,
                    target,
                    oof_scores,
                    protocol,
                    candidate=str(candidate_name),
                ),
            }
        )

    primary = next(item for item in candidates if item["feature_set"] == primary_name)
    selected = None
    status = "NOT_READY"
    if primary["development_criteria"] == "MET":
        names = tuple(primary["feature_names"])
        matrix = _matrix(all_rows, names)
        final_models = {}
        final_points = {}
        for detector in detectors:
            indices = np.asarray(
                [index for index, row in enumerate(all_rows) if row["detector"] == detector],
                dtype=int,
            )
            detector_weights = _sample_weights([all_rows[index] for index in indices])
            scaler, model = _fit_model(
                matrix[indices],
                target[indices],
                detector_weights,
                regularization_c=float(rules["regularization_c"]),
                maximum_iterations=int(rules["maximum_iterations"]),
                seed=int(audit["seed"]),
            )
            detector_scores = np.full(len(all_rows), np.nan, dtype=np.float64)
            detector_scores[indices] = _score_model(scaler, model, matrix[indices])
            point = _select_threshold(
                all_rows,
                detector_scores,
                detector=detector,
                rules=rules,
                audit_fraction=float(audit["fraction"]),
                audit_seed=int(audit["seed"]),
            )
            if point is None:
                raise ContractError(f"v3 full-development calibration failed for {detector}")
            final_points[detector] = point
            final_models[detector] = _serialized_model(
                scaler, model, names, point["threshold"]
            )
        final_reduction = _combined_reduction(final_points)
        if final_reduction >= float(rules["minimum_effective_reduction"]):
            status = "READY_FOR_CONFIRMATION"
            selected = {
                "feature_set": primary_name,
                "selection_basis": "predeclared_primary_only",
                "calibration_method": rules["final_calibration_method"],
                "oof_development_background_call_reduction": primary[
                    "oof_development_background_call_reduction"
                ],
                "full_development_calibration_call_reduction": final_reduction,
                "detectors": final_points,
                "models": final_models,
            }

    result = {
        "schema_version": 3,
        "status": status,
        "scientific_mode": "exploratory_development_screen_before_reserved_confirmation",
        "development_interpretation": "hypothesis_generating_exploratory",
        "routing_enabled": False,
        "o4b_outcomes_used": [],
        "confirmation_values_used": [],
        "can_authorize_operational_pass": False,
        "protocol": protocol.reference,
        "representation_sha256": representation_hashes.pop(),
        "cohort_split_sha256_by_role": dict(sorted(expected_hashes.items())),
        "source_ledgers": source_records,
        "screening": {
            "cross_validation_method": rules["cross_validation_method"],
            "gps_block_duration_s": int(rules["gps_block_duration_s"]),
            "folds": folds,
            "model": rules["model"],
            "class_weighting": rules["class_weighting"],
            "primary_feature_set": primary_name,
            "ablation_eligible_for_selection": False,
            "development_call_reduction_target": float(rules["minimum_effective_reduction"]),
            "candidates": candidates,
        },
        "feature_cost": {
            "development_n": int(timings.size),
            "feature_extraction_median_s": float(np.median(timings)),
            "feature_extraction_p95_s": float(np.quantile(timings, 0.95)),
            "feature_extraction_max_s": float(np.max(timings)),
            "excludes_data_read_and_whitening": True,
        },
        "selected_operating_point": selected,
        "next_stage": (
            "open_reserved_positive_confirmation"
            if status == "READY_FOR_CONFIRMATION"
            else "stop_without_opening_reserved_confirmation_or_o4b"
        ),
    }
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
        raise ContractError(f"invalid v3 screening artifact {source}: {exc}") from exc
    if not isinstance(result, dict):
        raise ContractError("v3 screening artifact root must be an object")
    body = dict(result)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v3 screening artifact digest mismatch")
    if (
        result.get("schema_version") != 3
        or result.get("status") not in {"NOT_READY", "READY_FOR_CONFIRMATION"}
        or result.get("routing_enabled") is not False
        or result.get("o4b_outcomes_used") != []
        or result.get("confirmation_values_used") != []
        or result.get("can_authorize_operational_pass") is not False
    ):
        raise ContractError("v3 screening scientific boundary is invalid")
    return result


def verify_screening_result(
    saved_path: str | Path,
    *,
    ledgers: Mapping[str, str | Path],
    protocol: PrefilterProtocolV3,
) -> dict[str, Any]:
    saved = load_screening_result(saved_path)
    recomputed = screen_prefilter_v3(ledgers=ledgers, protocol=protocol)
    if saved != recomputed:
        raise ContractError("v3 screening artifact does not match exact recomputation")
    return {
        "status": "PASS",
        "scientific_status": saved["status"],
        "artifact_digest": saved["artifact_digest"],
        "routing_enabled": False,
        "o4b_outcomes_used": [],
        "confirmation_values_used": [],
    }
