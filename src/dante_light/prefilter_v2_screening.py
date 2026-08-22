"""Block-cross-validated development screening for the frozen L4 v2 features."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from src.dante_light.contracts import ContractError, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_evaluation import wilson_interval
from src.dante_light.prefilter_v2 import feature_names_by_family
from src.dante_light.prefilter_v2_protocol import PrefilterProtocolV2


REQUIRED_ROLES = {"background", "robust_candidate", "known_glitch", "injection"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_ledger(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        ledger = json.loads(path.read_text(encoding="utf-8"))
        body = dict(ledger)
        if body.pop("ledger_digest", None) != canonical_json_sha256(body):
            raise ContractError(f"v2 feature ledger digest mismatch: {path}")
        rows_path = path.parent / ledger["rows_path"]
        if ledger.get("status") != "complete" or ledger.get("schema_version") != 2:
            raise ContractError(f"v2 feature ledger is not complete: {path}")
        if _sha256(rows_path) != ledger["rows_sha256"]:
            raise ContractError(f"v2 feature row SHA256 mismatch: {path}")
        rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v2 feature ledger {path}: {exc}") from exc
    if len(rows) != int(ledger["row_count"]):
        raise ContractError(f"v2 feature row count mismatch: {path}")
    return ledger, rows


def _audit_selected(seed: int, fraction: float, window_id: str) -> bool:
    digest = hashlib.sha256(f"{seed}:{window_id}".encode("ascii")).digest()
    uniform = int.from_bytes(digest[:8], "big") / float(2**64)
    return uniform < fraction


def _positive_group(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (str(row["roles"][0]), str(row["detector"]), str(row["morphology"]))


def _sample_weights(rows: list[dict[str, Any]]) -> np.ndarray:
    background = [index for index, row in enumerate(rows) if row["roles"] == ["background"]]
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.get("retention_target") is True:
            groups[_positive_group(row)].append(index)
    if not background or not groups:
        raise ContractError("v2 class weighting requires background and positive strata")
    weights = np.zeros(len(rows), dtype=np.float64)
    weights[background] = 0.5 / len(background)
    group_weight = 0.5 / len(groups)
    for indices in groups.values():
        weights[indices] = group_weight / len(indices)
    return weights * len(rows)


def _block_groups(rows: list[dict[str, Any]], block_duration_s: int) -> np.ndarray:
    return np.asarray(
        [
            f"{row['window']['run']}:{row['detector']}:"
            f"{int(float(row['window']['gps_start']) // block_duration_s)}"
            for row in rows
        ],
        dtype=object,
    )


def _feature_names(protocol: PrefilterProtocolV2, candidate: str) -> tuple[str, ...]:
    by_family = feature_names_by_family(protocol.payload["feature_extraction"])
    if candidate == "all":
        return tuple(name for family in by_family.values() for name in family)
    try:
        return by_family[candidate]
    except KeyError as exc:
        raise ContractError(f"unknown v2 feature candidate: {candidate}") from exc


def _matrix(rows: list[dict[str, Any]], names: tuple[str, ...]) -> np.ndarray:
    matrix = np.empty((len(rows), len(names)), dtype=np.float64)
    for row_index, row in enumerate(rows):
        try:
            values = row["features"]["values"]
            matrix[row_index] = [float(values[name]) for name in names]
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError("v2 feature row does not match frozen feature schema") from exc
    if not np.all(np.isfinite(matrix)):
        raise ContractError("v2 feature matrix contains non-finite values")
    return matrix


def _fit_model(
    matrix: np.ndarray,
    target: np.ndarray,
    weights: np.ndarray,
    *,
    regularization_c: float,
    maximum_iterations: int,
    seed: int,
) -> tuple[StandardScaler, LogisticRegression]:
    scaler = StandardScaler().fit(matrix)
    model = LogisticRegression(
        C=regularization_c,
        solver="liblinear",
        max_iter=maximum_iterations,
        random_state=seed,
    )
    model.fit(scaler.transform(matrix), target, sample_weight=weights)
    return scaler, model


def _score_model(
    scaler: StandardScaler, model: LogisticRegression, matrix: np.ndarray
) -> np.ndarray:
    return model.predict_proba(scaler.transform(matrix))[:, 1]


def _select_threshold(
    rows: list[dict[str, Any]],
    scores: np.ndarray,
    *,
    detector: str,
    rules: Mapping[str, Any],
    audit_fraction: float,
    audit_seed: int,
) -> dict[str, Any] | None:
    selected_indices = [index for index, row in enumerate(rows) if row["detector"] == detector]
    background_indices = [index for index in selected_indices if rows[index]["roles"] == ["background"]]
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index in selected_indices:
        if rows[index].get("retention_target") is True:
            groups[_positive_group(rows[index])].append(index)
    candidates = np.unique(scores[selected_indices])
    candidates = np.r_[candidates, np.nextafter(candidates[-1], np.inf)]
    confidence = float(rules["wilson_confidence"])
    for threshold in np.sort(candidates)[::-1]:
        metrics = {}
        valid = True
        for key, indices in sorted(groups.items()):
            role = key[0]
            retained = int(np.sum(scores[indices] >= threshold))
            total = len(indices)
            rate = retained / total
            lower, upper = wilson_interval(retained, total, confidence=confidence)
            group_pass = (
                total >= int(rules["minimum_group_n_by_role"][role])
                and rate >= float(rules["minimum_retention_by_role"][role])
                and lower >= float(rules["minimum_wilson_lower_by_role"][role])
            )
            metrics["/".join(key)] = {
                "retained": retained,
                "n": total,
                "rate": float(rate),
                "wilson_interval": [float(lower), float(upper)],
                "status": "PASS" if group_pass else "FAIL",
            }
            valid = valid and group_pass
        if not valid:
            continue
        calls = 0
        for index in background_indices:
            selected = bool(scores[index] >= threshold)
            window_id = rows[index]["window"]["window_id"]
            calls += bool(selected or ((not selected) and _audit_selected(audit_seed, audit_fraction, window_id)))
        reduction = 1.0 - calls / len(background_indices)
        return {
            "detector": detector,
            "threshold": float(threshold),
            "background_n": len(background_indices),
            "would_call_exact": int(calls),
            "development_background_call_reduction": float(reduction),
            "groups": metrics,
        }
    return None


def _combined_reduction(points: Mapping[str, Mapping[str, Any]]) -> float:
    total = sum(int(point["background_n"]) for point in points.values())
    calls = sum(int(point["would_call_exact"]) for point in points.values())
    return float(1.0 - calls / total)


def _serialized_model(
    scaler: StandardScaler,
    model: LogisticRegression,
    names: tuple[str, ...],
    threshold: float,
) -> dict[str, Any]:
    return {
        "feature_names": list(names),
        "scaler_mean": [float(value) for value in scaler.mean_],
        "scaler_scale": [float(value) for value in scaler.scale_],
        "coefficient": [float(value) for value in model.coef_[0]],
        "intercept": float(model.intercept_[0]),
        "probability_threshold": float(threshold),
    }


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[float, int, str]:
    """Order PASS candidates exactly as declared by the frozen protocol."""

    return (
        -float(candidate["oof_development_background_call_reduction"]),
        len(candidate["feature_names"]),
        str(candidate["feature_set"]),
    )


def screen_prefilter_v2(
    *,
    ledgers: Mapping[str, str | Path],
    expected_split_hashes: Mapping[str, str],
    protocol: PrefilterProtocolV2,
) -> dict[str, Any]:
    if set(ledgers) != REQUIRED_ROLES or set(expected_split_hashes) != REQUIRED_ROLES:
        raise ContractError("v2 screening requires exactly four frozen role ledgers")
    feature_source = f"prefilter-v2:{protocol.payload['protocol_digest']}"
    source_records = []
    all_rows = []
    representation_hashes = set()
    for role, raw_path in sorted(ledgers.items()):
        path = Path(raw_path).resolve()
        ledger, rows = _load_ledger(path)
        split_hash = str(expected_split_hashes[role])
        if ledger.get("role") != role or ledger.get("feature_source") != feature_source:
            raise ContractError(f"v2 feature ledger contract mismatch for {role}")
        if ledger.get("cohort_split_sha256_by_role") != {role: split_hash}:
            raise ContractError(f"v2 feature ledger split mismatch for {role}")
        representation_hashes.add(str(ledger["representation_sha256"]))
        source_records.append(
            {
                "role": role,
                "file_name": path.name,
                "sha256": _sha256(path),
                "rows_sha256": ledger["rows_sha256"],
                "role_split_sha256": split_hash,
            }
        )
        for row in rows:
            window = WindowIdentity.from_dict(row["window"])
            if row.get("detector") != window.detector or row.get("roles") != [role]:
                raise ContractError(f"v2 feature row annotation mismatch in {role}")
            if row.get("partition") == "development":
                if window.run == "O4B":
                    raise ContractError("O4b development outcome leakage")
                all_rows.append(row)
    if len(representation_hashes) != 1:
        raise ContractError("v2 ledgers use multiple exact representations")
    identities = [row["window"]["window_id"] for row in all_rows]
    if len(identities) != len(set(identities)):
        raise ContractError("v2 development ledgers overlap in window identity")
    feature_timings = np.asarray(
        [float(row["timings"]["feature_extraction_s"]) for row in all_rows],
        dtype=np.float64,
    )
    if not np.all(np.isfinite(feature_timings)) or np.any(feature_timings < 0.0):
        raise ContractError("v2 feature timing evidence is invalid")
    rules = protocol.payload["development"]
    detectors = tuple(protocol.payload["required_detectors"])
    for detector in detectors:
        background_n = sum(row["roles"] == ["background"] and row["detector"] == detector for row in all_rows)
        if background_n < int(rules["minimum_background_per_detector"]):
            raise ContractError(f"underpowered v2 background for {detector}: {background_n}")
    weights = _sample_weights(all_rows)
    target = np.asarray([row.get("retention_target") is True for row in all_rows], dtype=int)
    groups = _block_groups(all_rows, int(rules["gps_block_duration_s"]))
    folds = int(rules["cross_validation_folds"])
    if len(set(groups)) < folds:
        raise ContractError("insufficient independent GPS blocks for v2 cross-validation")
    audit = protocol.payload["audit"]
    audit_fraction = float(audit["fraction"])
    audit_seed = int(audit["seed"])
    candidates = []
    for candidate_name in rules["candidate_feature_sets"]:
        names = _feature_names(protocol, candidate_name)
        matrix = _matrix(all_rows, names)
        oof_scores = np.full(len(all_rows), np.nan, dtype=np.float64)
        fold_records = []
        splitter = GroupKFold(n_splits=folds, shuffle=True, random_state=int(protocol.payload["cohort_split_seed"]))
        for fold_index, (train, test) in enumerate(splitter.split(matrix, target, groups), 1):
            if len(np.unique(target[train])) != 2:
                raise ContractError(f"v2 fold {fold_index} lacks a binary training target")
            scaler, model = _fit_model(
                matrix[train],
                target[train],
                weights[train],
                regularization_c=float(rules["regularization_c"]),
                maximum_iterations=int(rules["maximum_iterations"]),
                seed=int(protocol.payload["cohort_split_seed"]) + fold_index,
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
            raise ContractError("v2 OOF prediction coverage is incomplete")
        points = {
            detector: _select_threshold(
                all_rows,
                oof_scores,
                detector=detector,
                rules=rules,
                audit_fraction=audit_fraction,
                audit_seed=audit_seed,
            )
            for detector in detectors
        }
        valid = all(point is not None for point in points.values())
        reduction = _combined_reduction(points) if valid else None
        status = (
            "PASS"
            if valid and reduction >= float(rules["minimum_effective_reduction"])
            else "NOT_READY"
        )
        candidates.append(
            {
                "feature_set": candidate_name,
                "feature_names": list(names),
                "status": status,
                "oof_development_background_call_reduction": reduction,
                "detectors": points,
                "folds": fold_records,
            }
        )
    passing = [candidate for candidate in candidates if candidate["status"] == "PASS"]
    if not passing:
        status = "NOT_READY"
        selected = None
    else:
        selected_screen = min(passing, key=_candidate_sort_key)
        names = tuple(selected_screen["feature_names"])
        matrix = _matrix(all_rows, names)
        final_models = {}
        final_points = {}
        for detector in detectors:
            indices = np.asarray([index for index, row in enumerate(all_rows) if row["detector"] == detector])
            scaler, model = _fit_model(
                matrix[indices],
                target[indices],
                weights[indices],
                regularization_c=float(rules["regularization_c"]),
                maximum_iterations=int(rules["maximum_iterations"]),
                seed=int(protocol.payload["cohort_split_seed"]),
            )
            detector_scores = np.full(len(all_rows), np.nan, dtype=np.float64)
            detector_scores[indices] = _score_model(scaler, model, matrix[indices])
            point = _select_threshold(
                all_rows,
                detector_scores,
                detector=detector,
                rules=rules,
                audit_fraction=audit_fraction,
                audit_seed=audit_seed,
            )
            if point is None:
                raise ContractError(f"v2 full-development calibration failed for {detector}")
            final_points[detector] = point
            final_models[detector] = _serialized_model(scaler, model, names, point["threshold"])
        final_reduction = _combined_reduction(final_points)
        if final_reduction < float(rules["minimum_effective_reduction"]):
            status = "NOT_READY"
            selected = None
        else:
            status = "PASS"
            selected = {
                "feature_set": selected_screen["feature_set"],
                "oof_development_background_call_reduction": selected_screen[
                    "oof_development_background_call_reduction"
                ],
                "full_development_calibration_call_reduction": final_reduction,
                "detectors": final_points,
                "models": final_models,
            }
    result = {
        "schema_version": 2,
        "status": status,
        "scientific_mode": "development_only_block_cross_validated_prefilter_screening",
        "routing_enabled": False,
        "o4b_outcomes_used": [],
        "protocol": protocol.reference,
        "representation_sha256": representation_hashes.pop(),
        "cohort_split_sha256_by_role": dict(sorted(expected_split_hashes.items())),
        "source_ledgers": source_records,
        "screening": {
            "cross_validation_method": rules["cross_validation_method"],
            "gps_block_duration_s": int(rules["gps_block_duration_s"]),
            "folds": folds,
            "model": rules["model"],
            "class_weighting": rules["class_weighting"],
            "selection_metric": rules["selection_metric"],
            "selection_tie_break": list(rules["selection_tie_break"]),
            "development_call_reduction_target": float(rules["minimum_effective_reduction"]),
            "candidates": candidates,
        },
        "feature_cost": {
            "development_n": int(feature_timings.size),
            "feature_extraction_median_s": float(np.median(feature_timings)),
            "feature_extraction_p95_s": float(np.quantile(feature_timings, 0.95)),
            "feature_extraction_max_s": float(np.max(feature_timings)),
            "excludes_data_read_and_whitening": True,
        },
        "selected_operating_point": selected,
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
