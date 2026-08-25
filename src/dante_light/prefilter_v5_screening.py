"""Fail-closed frozen gate application for DANTE-Light v5 development."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import stats

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_evaluation import wilson_interval
from src.dante_light.prefilter_v5_development import (
    ARMS,
    DEFAULT_OUTPUT as DEFAULT_DEVELOPMENT_RESULT,
    default_development_cache_root,
)
from src.dante_light.prefilter_v5_development_contract import (
    DEFAULT_OUTPUT as DEFAULT_CONTRACT,
    load_development_contract,
)
from src.dante_light.prefilter_v5_protocol import ROOT, sha256_path


SCHEMA_VERSION = 1
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_development/screening_summary_v5.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v5 screening JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"v5 screening JSON is not a mapping: {path}")
    return value


def _load_rows(path: Path) -> list[dict[str, Any]]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v5 development ledger {path}: {exc}") from exc


def _audit_selected(seed: int, fraction: float, window_id: str) -> bool:
    digest = hashlib.sha256(f"{int(seed)}:{window_id}".encode("utf-8")).digest()
    uniform = int.from_bytes(digest[:8], "big") / float(2**64)
    return uniform < float(fraction)


def _subseed(seed: int, *parts: str) -> int:
    payload = ":".join((str(int(seed)), *parts)).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    if left.size < 2 or np.unique(left).size < 2 or np.unique(right).size < 2:
        return float("nan")
    return float(stats.spearmanr(left, right).statistic)


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def _serialize_threshold(value: float) -> float | str:
    return "POSITIVE_INFINITY" if math.isinf(value) else float(value)


def _threshold_float(value: float | str) -> float:
    if value == "POSITIVE_INFINITY":
        return float("inf")
    return float(value)


def _bootstrap_spearman_lower(
    rows: Sequence[Mapping[str, Any]],
    predictions: np.ndarray,
    targets: np.ndarray,
    *,
    n_resamples: int,
    confidence: float,
    seed: int,
    quantile_method: str,
) -> tuple[float, list[float]]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        blocks[str(row["gps_block"])].append(index)
    keys = sorted(blocks)
    if len(keys) < 2:
        raise ContractError("v5 fidelity block bootstrap has fewer than two blocks")
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(int(n_resamples)):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        indices = np.asarray([index for key in sampled for index in blocks[str(key)]], dtype=int)
        coefficient = _spearman(predictions[indices], targets[indices])
        if math.isfinite(coefficient):
            values.append(coefficient)
    if len(values) != int(n_resamples):
        raise ContractError("v5 fidelity bootstrap produced a non-finite replicate")
    alpha = (1.0 - float(confidence)) / 2.0
    interval = np.quantile(values, [alpha, 1.0 - alpha], method=quantile_method)
    return float(interval[0]), [float(interval[0]), float(interval[1])]


def _bootstrap_mean_lower(
    rows: Sequence[Mapping[str, Any]],
    values: np.ndarray,
    *,
    n_resamples: int,
    confidence: float,
    seed: int,
    quantile_method: str,
) -> tuple[float, list[float]]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        blocks[str(row["gps_block"])].append(index)
    keys = sorted(blocks)
    if len(keys) < 2:
        raise ContractError("v5 cost block bootstrap has fewer than two blocks")
    rng = np.random.default_rng(seed)
    estimates = np.empty(int(n_resamples), dtype=np.float64)
    for replicate in range(int(n_resamples)):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        indices = np.asarray([index for key in sampled for index in blocks[str(key)]], dtype=int)
        estimates[replicate] = float(np.mean(values[indices]))
    alpha = (1.0 - float(confidence)) / 2.0
    interval = np.quantile(estimates, [alpha, 1.0 - alpha], method=quantile_method)
    return float(interval[0]), [float(interval[0]), float(interval[1])]


def _prediction(row: Mapping[str, Any], arm: str, replicate: int) -> float:
    records = row["student"][arm]
    matches = [item for item in records if int(item["replicate_index"]) == replicate]
    if len(matches) != 1:
        raise ContractError("v5 development student prediction matrix is malformed")
    value = float(matches[0]["prediction_standardized"])
    if not math.isfinite(value):
        raise ContractError("v5 development student prediction is non-finite")
    return value


def _prefilter_cost(row: Mapping[str, Any], arm: str, replicate: int) -> float:
    records = row["student"][arm]
    matches = [item for item in records if int(item["replicate_index"]) == replicate]
    if len(matches) != 1:
        raise ContractError("v5 development student timing matrix is malformed")
    value = float(matches[0]["timings"]["prefilter_total_s"])
    if not math.isfinite(value) or value < 0:
        raise ContractError("v5 development prefilter timing is invalid")
    return value


def _retention_groups(
    rows: Sequence[Mapping[str, Any]], calls: np.ndarray, *, confidence: float,
    minimum_point: float, minimum_lower: float,
) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if bool(row["retention_target"]):
            groups[(str(row["role"]), str(row["morphology"]))].append(index)
    if not groups:
        raise ContractError("v5 development detector has no protected strata")
    results = {}
    for (role, morphology), indices in sorted(groups.items()):
        retained = int(calls[indices].sum())
        total = len(indices)
        point = retained / total
        lower, upper = wilson_interval(retained, total, confidence)
        passed = point >= minimum_point and lower >= minimum_lower
        results[f"{role}|{morphology}"] = {
            "retained": retained,
            "total": total,
            "point_retention": point,
            "wilson_interval": [float(lower), float(upper)],
            "pass": bool(passed),
        }
    return results


def _select_detector_threshold(
    rows: Sequence[Mapping[str, Any]], predictions: np.ndarray, *, audit: np.ndarray,
    confidence: float, minimum_point: float, minimum_lower: float,
) -> dict[str, Any] | None:
    candidates = [float(value) for value in np.unique(predictions)] + [float("inf")]
    best = None
    background = np.asarray([row["role"] == "background" for row in rows], dtype=bool)
    if not background.any():
        raise ContractError("v5 development detector has no background")
    for threshold in candidates:
        calls = (predictions >= threshold) | audit
        retention = _retention_groups(
            rows,
            calls,
            confidence=confidence,
            minimum_point=minimum_point,
            minimum_lower=minimum_lower,
        )
        if not all(record["pass"] for record in retention.values()):
            continue
        reduction = 1.0 - float(np.mean(calls[background]))
        candidate = {
            "threshold_standardized": _serialize_threshold(threshold),
            "background_call_reduction": reduction,
            "background_exact_calls": int(calls[background].sum()),
            "background_total": int(background.sum()),
            "protected_retention": retention,
        }
        if best is None or (-reduction, threshold) < (
            -float(best["background_call_reduction"]),
            _threshold_float(best["threshold_standardized"]),
        ):
            best = candidate
    return best


def _diagnostics(
    rows: Sequence[Mapping[str, Any]], predictions: np.ndarray, targets: np.ndarray,
    *, bins: int,
) -> dict[str, Any]:
    by_stratum = {}
    groups: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[(str(row["detector"]), str(row["role"]), str(row["morphology"]))].append(index)
    for key, indices in sorted(groups.items()):
        residual = predictions[indices] - targets[indices]
        by_stratum["|".join(key)] = {
            "n": len(indices),
            "mean_error_standardized": float(np.mean(residual)),
            "mean_absolute_error_standardized": float(np.mean(np.abs(residual))),
            "spearman": _finite_or_none(
                _spearman(predictions[indices], targets[indices])
            ),
        }
    quantile_edges = np.quantile(targets, np.linspace(0.0, 1.0, bins + 1))
    quantile_rows = []
    for index in range(bins):
        low = quantile_edges[index]
        high = quantile_edges[index + 1]
        mask = (targets >= low) & (targets <= high if index == bins - 1 else targets < high)
        residual = predictions[mask] - targets[mask]
        quantile_rows.append(
            {
                "bin": index,
                "n": int(mask.sum()),
                "teacher_standardized_interval": [float(low), float(high)],
                "mean_error_standardized": (
                    float(np.mean(residual)) if residual.size else None
                ),
                "mean_absolute_error_standardized": (
                    float(np.mean(np.abs(residual))) if residual.size else None
                ),
            }
        )
    return {"by_detector_role_morphology": by_stratum, "teacher_quantile_bins": quantile_rows}


def screen_development(
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    development_result_path: Path = DEFAULT_DEVELOPMENT_RESULT,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    contract = load_development_contract(contract_path, root=root)
    development = _load_json(development_result_path)
    dev_body = dict(development)
    if dev_body.pop("artifact_digest", None) != canonical_json_sha256(dev_body):
        raise ContractError("v5 development result digest mismatch")
    if development.get("status") != "DEVELOPMENT_MATRIX_COMPLETE_PENDING_SCREENING":
        raise ContractError("v5 development matrix is not complete")
    if (
        development.get("confirmation_rows_accessed") != []
        or development.get("o4b_rows_accessed") != []
        or development.get("routing_enabled") is not False
    ):
        raise ContractError("v5 development boundary was widened")
    run_dir = (cache_root or default_development_cache_root()) / development["full_ledger"]["run_subdirectory"]
    ledger_path = run_dir / development["full_ledger"]["path"]
    if sha256_path(ledger_path) != development["full_ledger"]["sha256"]:
        raise ContractError("v5 full development ledger hash mismatch")
    rows = _load_rows(ledger_path)
    if len(rows) != int(development["row_count"]):
        raise ContractError("v5 full development ledger row count mismatch")
    if any(
        row.get("partition") != "development"
        or row.get("confirmation_accessed") is not False
        or row.get("o4b_accessed") is not False
        for row in rows
    ):
        raise ContractError("v5 full ledger contains a protected partition")
    protocol = _load_json(root / contract["source_references"]["protocol"]["path"])
    gates = protocol["approved_design"]["gates"]
    retention_gate = gates["protected_retention"]
    fidelity_gate = gates["teacher_fidelity"]
    operational_gate = gates["operational"]
    uncertainty = gates["uncertainty"]
    design = contract["approved_design"]
    audit_fraction = float(design["audit_stream"]["fraction"])
    audit_seed = int(contract["audit_seed_uint64"])
    bootstrap_seed = int(contract["bootstrap_seed_uint64"])
    standardization = _load_json(
        root / contract["source_references"]["training_contract"]["path"]
    )["target_standardization"]
    results = {}
    ready_arms = []
    for arm in ARMS:
        replicate_rows = []
        for replicate in range(5):
            predictions = np.asarray([_prediction(row, arm, replicate) for row in rows])
            teacher_standardized = np.asarray(
                [
                    (
                        float(row["teacher_score_native"])
                        - float(standardization[row["detector"]]["mean_float64"])
                    )
                    / float(
                        standardization[row["detector"]][
                            "standard_deviation_float64_ddof0"
                        ]
                    )
                    for row in rows
                ],
                dtype=np.float64,
            )
            audit = np.asarray(
                [
                    _audit_selected(audit_seed, audit_fraction, row["window"]["window_id"])
                    for row in rows
                ],
                dtype=bool,
            )
            fidelity = {}
            thresholds = {}
            fidelity_pass = True
            for detector in ("H1", "L1"):
                mask = np.asarray([row["detector"] == detector for row in rows], dtype=bool)
                detector_rows = [row for row, selected in zip(rows, mask) if selected]
                point = _spearman(predictions[mask], teacher_standardized[mask])
                lower, interval = _bootstrap_spearman_lower(
                    detector_rows,
                    predictions[mask],
                    teacher_standardized[mask],
                    n_resamples=int(uncertainty["n_resamples"]),
                    confidence=float(uncertainty["confidence"]),
                    seed=_subseed(bootstrap_seed, arm, str(replicate), detector, "fidelity"),
                    quantile_method=design["teacher_fidelity"]["bootstrap_quantile_method"],
                )
                passed = point >= float(fidelity_gate["minimum_spearman"]) and lower >= float(
                    fidelity_gate["minimum_block_bootstrap_lower"]
                )
                fidelity[detector] = {
                    "n": int(mask.sum()),
                    "spearman": point,
                    "block_bootstrap_interval": interval,
                    "block_bootstrap_lower": lower,
                    "pass": bool(passed),
                }
                fidelity_pass = fidelity_pass and passed
                point_threshold = _select_detector_threshold(
                    detector_rows,
                    predictions[mask],
                    audit=audit[mask],
                    confidence=float(retention_gate["wilson_confidence"]),
                    minimum_point=float(retention_gate["minimum_point_retention"]),
                    minimum_lower=float(retention_gate["minimum_wilson_lower"]),
                )
                thresholds[detector] = point_threshold
            threshold_pass = all(value is not None for value in thresholds.values())
            background_indices = [index for index, row in enumerate(rows) if row["role"] == "background"]
            background_rows = [rows[index] for index in background_indices]
            if threshold_pass:
                calls = np.asarray(
                    [
                        predictions[index]
                        >= _threshold_float(
                            thresholds[rows[index]["detector"]]["threshold_standardized"]
                        )
                        or audit[index]
                        for index in background_indices
                    ],
                    dtype=bool,
                )
                reduction = 1.0 - float(np.mean(calls))
                exact_cost = np.asarray(
                    [float(rows[index]["avoidable_exact_path_cost_s"]) for index in background_indices]
                )
                prefilter_cost = np.asarray(
                    [_prefilter_cost(rows[index], arm, replicate) for index in background_indices]
                )
                net = (~calls).astype(np.float64) * exact_cost - prefilter_cost
                net_lower, net_interval = _bootstrap_mean_lower(
                    background_rows,
                    net,
                    n_resamples=int(uncertainty["n_resamples"]),
                    confidence=float(uncertainty["confidence"]),
                    seed=_subseed(bootstrap_seed, arm, str(replicate), "net_cost"),
                    quantile_method=design["paired_cost"]["bootstrap_quantile_method"],
                )
                operational = {
                    "background_call_reduction": reduction,
                    "background_exact_calls": int(calls.sum()),
                    "background_total": int(calls.size),
                    "mean_prefilter_cost_s": float(np.mean(prefilter_cost)),
                    "mean_avoidable_exact_path_cost_s": float(np.mean(exact_cost)),
                    "mean_net_saving_s": float(np.mean(net)),
                    "block_bootstrap_net_saving_interval": net_interval,
                    "block_bootstrap_net_saving_lower": net_lower,
                    "pass": bool(
                        reduction >= float(operational_gate["minimum_background_call_reduction"])
                        and net_lower > float(operational_gate["minimum_mean_net_saving_s"])
                    ),
                }
            else:
                operational = {
                    "background_call_reduction": None,
                    "block_bootstrap_net_saving_lower": None,
                    "pass": False,
                }
            replicate_pass = fidelity_pass and threshold_pass and operational["pass"]
            replicate_rows.append(
                {
                    "replicate_index": replicate,
                    "teacher_fidelity": fidelity,
                    "detector_thresholds": thresholds,
                    "operational": operational,
                    "diagnostics": _diagnostics(
                        rows,
                        predictions,
                        teacher_standardized,
                        bins=int(design["shortcut_controls"]["teacher_quantile_bins"]),
                    ),
                    "pass": bool(replicate_pass),
                }
            )
        arm_pass = all(row["pass"] for row in replicate_rows)
        results[arm] = {
            "replicates": replicate_rows,
            "worst_replicate_all_gates_pass": bool(arm_pass),
            "favorable_seed_selection_used": False,
        }
        if arm_pass:
            ready_arms.append(arm)
    priority = list(protocol["approved_design"]["students"]["selection_priority"])
    selected = next((arm for arm in priority if arm in ready_arms), None)
    status = "READY_FOR_CONFIRMATION" if selected is not None else "V5_NOT_READY"
    if selected is None:
        unlock = None
    else:
        thresholds = {
            str(row["replicate_index"]): row["detector_thresholds"]
            for row in results[selected]["replicates"]
        }
        model_material = {
            "architecture": selected,
            "training_artifact_digest": contract["training_artifact_digest"],
            "replicate_count": 5,
        }
        unlock = {
            "status": "READY_FOR_CONFIRMATION",
            "protocol_sha256": contract["source_references"]["protocol"]["sha256"],
            "manifest_digest": _load_json(
                root / contract["source_references"]["split_header"]["path"]
            )["manifest_digest"],
            "model_digest": canonical_json_sha256(model_material),
            "model_code_digest": contract["code_references"]["student_architectures"]["sha256"],
            "threshold_digest": canonical_json_sha256(thresholds),
            "teacher_contract_digest": _load_json(
                root / contract["source_references"]["teacher_contract"]["path"]
            )["teacher_contract_digest"],
            "paired_cost_contract_digest": contract["development_contract_digest"],
            "injection_generator_digest": contract["code_references"]["injection_reconstruction"]["sha256"],
            "replicate_selection_digest": canonical_json_sha256(model_material),
            "verifier_digest": contract["code_references"]["development_verifier"]["sha256"],
        }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "scientific_mode": "one_shot_frozen_v5_development_only",
        "development_contract_digest": contract["development_contract_digest"],
        "development_result_digest": development["artifact_digest"],
        "audit_fraction": audit_fraction,
        "audit_seed_uint64": audit_seed,
        "uncertainty": uncertainty,
        "architectures": results,
        "ready_architectures": ready_arms,
        "selected_architecture": selected,
        "unlock_authorization_material": unlock,
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
        "routing_enabled": False,
        "can_authorize_operational_pass": False,
        "next_stage": (
            "await_explicit_authorization_before_opening_confirmation"
            if selected is not None
            else "stop_without_opening_confirmation_or_o4b_and_do_not_retune_on_same_cohort"
        ),
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def write_screening(value: Mapping[str, Any], path: Path = DEFAULT_OUTPUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def verify_screening(
    saved_path: Path = DEFAULT_OUTPUT,
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    development_result_path: Path = DEFAULT_DEVELOPMENT_RESULT,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    saved = _load_json(saved_path)
    body = dict(saved)
    if body.pop("artifact_digest", None) != canonical_json_sha256(body):
        raise ContractError("v5 screening summary digest mismatch")
    recomputed = screen_development(
        root=root,
        contract_path=contract_path,
        development_result_path=development_result_path,
        cache_root=cache_root,
    )
    if saved != recomputed:
        raise ContractError("v5 screening summary differs from exact recomputation")
    return {
        "status": "PASS_VERIFIED_DEVELOPMENT",
        "scientific_status": saved["status"],
        "artifact_digest": saved["artifact_digest"],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
        "routing_enabled": False,
    }
