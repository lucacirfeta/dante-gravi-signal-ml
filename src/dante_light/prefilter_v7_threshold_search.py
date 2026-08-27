"""One-shot threshold search for the frozen DANTE-Light v7 ensemble.

The stage may read only the ``threshold_search`` partition.  It requires a
fresh, training-only exact-teacher stability receipt before the first outcome
row is read and freezes its selected detector thresholds before any
``risk_calibration`` access.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import torch

from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.prefilter_evaluation import wilson_interval
from src.dante_light.prefilter_v5_teacher import ExactNativeTeacher, prepare_teacher_input
from src.dante_light.prefilter_v7_freeze import verify_freeze
from src.dante_light.prefilter_v7_teacher_stability import (
    DEFAULT_CONTRACT as DEFAULT_STABILITY_CONTRACT,
    verify_stability_contract,
    verify_stability_receipt,
)
from src.dante_light.prefilter_v7_training import (
    DEFAULT_TRAINING_SUMMARY,
    _atomic_json,
    _atomic_jsonl,
    _cache_raw_windows,
    _thresholds,
    strict_defer_label,
)
from src.dante_light.prefilter_v7_training_freeze import (
    ROOT,
    build_ensemble,
    file_sha256,
    load_training_freeze,
    repository_reference,
)


SCHEMA_VERSION = 1
DETECTORS = ("H1", "L1")
ROLES = ("background", "teacher_positive")
DEFAULT_CACHE = Path("E:/dante_cache/dante_light/prefilter_l4_v7_threshold_search")
DEFAULT_TRAINING_CACHE = Path("E:/dante_cache/dante_light/prefilter_l4_v7_training")
DEFAULT_AUTHORIZATION = ROOT / "config/dante_light_prefilter_v7_threshold_search_authorization.json"
DEFAULT_STABILITY_RECEIPT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_threshold_search"
    / "teacher_stability_receipt_threshold_search_v7.json"
)
DEFAULT_COMPACT_ROWS = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_threshold_search"
    / "threshold_search_scores_compact_v7.jsonl"
)
DEFAULT_RESULT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_threshold_search"
    / "threshold_search_summary_v7.json"
)
DEFAULT_THRESHOLD_CONTRACT = ROOT / "config/dante_light_prefilter_v7_threshold_contract.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _verify_digest(payload: Mapping[str, Any], field: str, label: str) -> None:
    body = dict(payload)
    declared = body.pop(field, None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"{label} digest mismatch")


def _resolve_reference(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    if set(reference) != {"path", "sha256"}:
        raise ContractError(f"v7 threshold-search reference is malformed: {label}")
    text = str(reference["path"])
    relative = Path(text)
    if relative.is_absolute() or ".." in relative.parts or "\\" in text:
        raise ContractError(f"v7 threshold-search reference is not portable: {label}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError(f"v7 threshold-search reference is absent: {label}")
    if file_sha256(path) != str(reference["sha256"]):
        raise ContractError(f"v7 threshold-search reference hash mismatch: {label}")
    return path


def threshold_search_code_references(root: Path = ROOT) -> dict[str, dict[str, str]]:
    paths = {
        "threshold_implementation": root / "src/dante_light/prefilter_v7_threshold_search.py",
        "threshold_freezer": root / "scripts/freeze_dante_light_prefilter_v7_threshold_search.py",
        "threshold_runner": root / "scripts/run_dante_light_prefilter_v7_threshold_search.py",
        "threshold_verifier": root / "scripts/verify_dante_light_prefilter_v7_threshold_search.py",
        "student_architecture": root / "src/dante_light/prefilter_v6_phase_a.py",
        "exact_teacher": root / "src/dante_light/prefilter_v5_teacher.py",
        "preprocessor": root / "src/core/preprocessor.py",
        "data_loader": root / "src/core/data_loader.py",
    }
    return {name: repository_reference(root, path) for name, path in paths.items()}


def build_threshold_search_authorization(
    *, root: Path = ROOT, code_references: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    frozen = verify_freeze(root)
    training = _read_json(root / DEFAULT_TRAINING_SUMMARY.relative_to(ROOT))
    _verify_digest(training, "artifact_digest", "v7 training summary")
    stability = verify_stability_contract(root=root)
    if training.get("status") != "TRAINING_COMPLETE_NON_PROMOTABLE":
        raise ContractError("v7 training is not complete before threshold authorization")
    if any(
        training.get(name)
        for name in ("threshold_search", "risk_calibration", "confirmation", "o4b")
    ):
        raise ContractError("v7 training summary already crossed a protected boundary")
    for name, reference in code_references.items():
        _resolve_reference(root, reference, name)
    source_paths = {
        "outcome_contract": root / "config/dante_light_prefilter_v7_outcome_blind_contract.json",
        "identity_manifest": root / "config/dante_light_prefilter_v7_identities.jsonl",
        "identity_header": root / "config/dante_light_prefilter_v7_identities.json",
        "training_contract": root / "config/dante_light_prefilter_v7_training_contract.json",
        "training_summary": root / DEFAULT_TRAINING_SUMMARY.relative_to(ROOT),
        "teacher_stability_contract": root / DEFAULT_STABILITY_CONTRACT.relative_to(ROOT),
        "confirmation_seal": root / "config/dante_light_prefilter_v7_confirmation_seal.json",
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "AUTHORIZED_THRESHOLD_SEARCH_ONLY",
        "authorization_id": "dante-light-l4-prefilter-v7-threshold-search-2026-08-27",
        "authorization_source": {
            "actor": "Luca Cirfeta",
            "date": "2026-08-27",
            "instruction": "procedi",
            "interpreted_scope": (
                "open threshold_search once; keep risk_calibration, confirmation "
                "and O4b sealed"
            ),
        },
        "outcome_contract_digest": frozen["contract_digest"],
        "training_artifact_digest": training["artifact_digest"],
        "teacher_stability_contract_digest": stability["stability_contract_digest"],
        "allowed": {
            "partition": "threshold_search",
            "exact_teacher_scoring": True,
            "frozen_ensemble_inference": True,
            "detector_threshold_selection_once": True,
        },
        "selection_rule": {
            "score": "five_member_mean_sigmoid_defer_score",
            "routing": "defer_if_score_greater_than_or_equal_to_threshold",
            "candidate_thresholds": "unique_detector_search_scores_plus_always_discard_endpoint",
            "objective": "maximum_natural_background_discard_fraction",
            "constraint": (
                "current_exact_teacher_positive_retention_point_gte_0.90_"
                "AND_Wilson95_lower_gte_0.80"
            ),
            "constraint_scope": (
                "separate_detector_catalog_conditioned_current_exact_teacher_positives"
            ),
            "safety_endpoint": "pre_audit_model_retention",
            "tie_break": "lower_numeric_threshold",
        },
        "forbidden": {
            "risk_calibration": [],
            "confirmation": [],
            "o4b": [],
            "routing": False,
            "retuning": False,
            "fallback_threshold": False,
            "member_selection": False,
        },
        "code_references": {name: dict(value) for name, value in code_references.items()},
        "source_references": {
            name: repository_reference(root, path) for name, path in source_paths.items()
        },
    }
    return {**body, "authorization_digest": canonical_json_sha256(body)}


def load_threshold_search_authorization(
    path: Path = DEFAULT_AUTHORIZATION, *, root: Path = ROOT
) -> dict[str, Any]:
    payload = _read_json(path)
    _verify_digest(payload, "authorization_digest", "v7 threshold-search authorization")
    if payload.get("status") != "AUTHORIZED_THRESHOLD_SEARCH_ONLY":
        raise ContractError("v7 threshold_search is not explicitly authorized")
    if payload.get("allowed") != {
        "partition": "threshold_search",
        "exact_teacher_scoring": True,
        "frozen_ensemble_inference": True,
        "detector_threshold_selection_once": True,
    }:
        raise ContractError("v7 threshold-search authorization scope changed")
    if payload.get("forbidden") != {
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
        "routing": False,
        "retuning": False,
        "fallback_threshold": False,
        "member_selection": False,
    }:
        raise ContractError("v7 threshold-search protected boundary widened")
    for group in ("code_references", "source_references"):
        for name, reference in payload[group].items():
            _resolve_reference(root, reference, f"{group}/{name}")
    training = _read_json(root / DEFAULT_TRAINING_SUMMARY.relative_to(ROOT))
    _verify_digest(training, "artifact_digest", "v7 training summary")
    stability = verify_stability_contract(root=root)
    frozen = verify_freeze(root)
    if (
        payload.get("training_artifact_digest") != training["artifact_digest"]
        or payload.get("teacher_stability_contract_digest")
        != stability["stability_contract_digest"]
        or payload.get("outcome_contract_digest") != frozen["contract_digest"]
    ):
        raise ContractError("v7 threshold-search authorization parent changed")
    return payload


def threshold_search_rows(*, root: Path = ROOT) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _read_jsonl(root / "config/dante_light_prefilter_v7_identities.jsonl")
        if row.get("partition") == "threshold_search"
    ]
    rows.sort(key=lambda row: (row["detector"], row["role"], row["identity_id"]))
    counts = {
        (detector, role): sum(
            row["detector"] == detector and row["role"] == role for row in rows
        )
        for detector in DETECTORS
        for role in ROLES
    }
    if len(rows) != 240 or any(value != 60 for value in counts.values()):
        raise ContractError("v7 threshold-search identities do not match the frozen 60x4 design")
    if len({row["identity_id"] for row in rows}) != 240:
        raise ContractError("v7 threshold-search identities are duplicated")
    if len({row["block_key"] for row in rows}) != 240:
        raise ContractError("v7 threshold-search blocks are not independent")
    return [{**row, "sampling_role": row["role"]} for row in rows]


def retention_gate(retained: int, total: int) -> dict[str, Any]:
    if total < 1 or retained < 0 or retained > total:
        raise ContractError("v7 threshold-search retention count is invalid")
    point = retained / total
    lower, upper = wilson_interval(retained, total, confidence=0.95)
    return {
        "retained": retained,
        "total": total,
        "point_retention": point,
        "wilson95": [float(lower), float(upper)],
        "pass": bool(point >= 0.90 and lower >= 0.80),
    }


def select_detector_threshold(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows or len({row["detector"] for row in rows}) != 1:
        raise ContractError("v7 threshold selection requires one nonempty detector")
    scores = np.asarray([float(row["student"]["ensemble_defer_score"]) for row in rows])
    if not np.isfinite(scores).all():
        raise ContractError("v7 threshold-search student score is non-finite")
    background = np.asarray([row["sampling_role"] == "background" for row in rows])
    positives = np.asarray(
        [
            row["sampling_role"] == "teacher_positive"
            and int(row["teacher_target"]["defer_label"]) == 1
            for row in rows
        ]
    )
    if int(background.sum()) != 60 or int(positives.sum()) < 1:
        raise ContractError("v7 threshold-search objective or conditioning cohort is empty")
    unique = sorted(float(value) for value in np.unique(scores))
    always_discard = float(np.nextafter(unique[-1], math.inf))
    candidates = unique + [always_discard]
    feasible = []
    for threshold in candidates:
        defer = scores >= threshold
        gate = retention_gate(int(defer[positives].sum()), int(positives.sum()))
        if not gate["pass"]:
            continue
        discard_fraction = float(np.mean(~defer[background]))
        feasible.append(
            {
                "threshold": threshold,
                "threshold_float64_hex": np.float64(threshold).tobytes().hex(),
                "candidate_kind": (
                    "always_discard" if threshold == always_discard else "observed_score"
                ),
                "natural_background_discarded": int((~defer[background]).sum()),
                "natural_background_total": int(background.sum()),
                "natural_background_discard_fraction": discard_fraction,
                "teacher_positive_retention": gate,
            }
        )
    if not feasible:
        raise ContractError("V7_NOT_READY: no threshold satisfies teacher-positive retention")
    feasible.sort(key=lambda row: (-row["natural_background_discard_fraction"], row["threshold"]))
    selected = feasible[0]
    selected["feasible_candidate_count"] = len(feasible)
    selected["candidate_count"] = len(candidates)
    selected["tie_break"] = "lower_numeric_threshold"
    return selected


def _load_ensemble(
    *, root: Path, training_cache_root: Path, device: torch.device
) -> tuple[torch.nn.Module, list[dict[str, Any]], dict[str, Any]]:
    contract = load_training_freeze(root=root)
    summary = _read_json(root / DEFAULT_TRAINING_SUMMARY.relative_to(ROOT))
    _verify_digest(summary, "artifact_digest", "v7 training summary")
    if summary.get("status") != "TRAINING_COMPLETE_NON_PROMOTABLE":
        raise ContractError("v7 frozen ensemble training is incomplete")
    run_dir = training_cache_root.resolve() / summary["cache_location"]["run_subdirectory"]
    ensemble = build_ensemble(root, contract["candidate"]["member_seeds"])
    checkpoints = []
    for member, record in zip(ensemble.members, summary["members"], strict=True):
        path = run_dir / record["best_model"]["path"]
        if not path.is_file() or file_sha256(path) != record["best_model"]["sha256"]:
            raise ContractError("v7 threshold-search checkpoint changed")
        state = torch.load(path, map_location="cpu", weights_only=True)
        if (
            state.get("run_key") != summary["run_key"]
            or int(state.get("member_index", -1)) != int(record["member_index"])
            or int(state.get("seed", -1)) != int(record["seed"])
        ):
            raise ContractError("v7 threshold-search checkpoint identity changed")
        member.load_state_dict(state["model_state"], strict=True)
        checkpoints.append(
            {
                "member_index": int(record["member_index"]),
                "seed": int(record["seed"]),
                "best_epoch": int(record["best_epoch"]),
                "path": record["best_model"]["path"],
                "sha256": record["best_model"]["sha256"],
            }
        )
    ensemble.to(device=device, dtype=torch.float32).eval()
    return ensemble, checkpoints, summary


def _run_key(
    authorization: Mapping[str, Any],
    receipt: Mapping[str, Any],
    checkpoints: Sequence[Mapping[str, Any]],
) -> str:
    return canonical_json_sha256(
        {
            "authorization_digest": authorization["authorization_digest"],
            "stability_receipt_digest": receipt["stability_receipt_digest"],
            "checkpoints": list(checkpoints),
            "stage": "threshold_search",
            "schema_version": SCHEMA_VERSION,
        }
    )


def _validate_batch(path: Path, *, run_key: str, expected_ids: Sequence[str]) -> dict[str, Any]:
    payload = _read_json(path)
    _verify_digest(payload, "batch_digest", "v7 threshold-search batch")
    if payload.get("run_key") != run_key or [
        row["identity_id"] for row in payload["rows"]
    ] != list(expected_ids):
        raise ContractError("v7 threshold-search cached batch identity changed")
    return payload


def run_threshold_search(
    *,
    root: Path = ROOT,
    cache_root: Path = DEFAULT_CACHE,
    training_cache_root: Path = DEFAULT_TRAINING_CACHE,
    stability_receipt_path: Path = DEFAULT_STABILITY_RECEIPT,
    workers: int = 4,
    retries: int = 3,
    device_name: str | None = None,
) -> dict[str, Any]:
    if workers < 1 or workers > 8 or retries < 1 or retries > 5:
        raise ContractError("v7 threshold-search worker/retry bound is invalid")
    authorization = load_threshold_search_authorization(root=root)
    stability_contract = verify_stability_contract(root=root)
    receipt = _read_json(stability_receipt_path)
    verify_stability_receipt(receipt, contract=stability_contract)
    if receipt.get("requested_partition") != "threshold_search":
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: wrong stability receipt stage")
    if receipt.get("partition_rows_accessed_before_check") != 0:
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: stability guard followed data access")

    device = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))
    ensemble, checkpoints, training_summary = _load_ensemble(
        root=root, training_cache_root=training_cache_root, device=device
    )
    run_key = _run_key(authorization, receipt, checkpoints)
    run_dir = cache_root.resolve() / f"threshold_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    access_marker = {
        "schema_version": SCHEMA_VERSION,
        "status": "THRESHOLD_SEARCH_ACCESS_STARTED_AFTER_STABILITY_PASS",
        "run_key": run_key,
        "stability_receipt_digest": receipt["stability_receipt_digest"],
        "partition_rows_accessed_before_check": 0,
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
    }
    marker_path = run_dir / "access_started.json"
    if marker_path.is_file() and _read_json(marker_path) != access_marker:
        raise ContractError("v7 threshold-search access-marker collision")
    if not marker_path.is_file():
        _atomic_json(marker_path, access_marker)

    rows = threshold_search_rows(root=root)
    raw_dir = run_dir / "raw"
    raw_records = _cache_raw_windows(rows, raw_dir=raw_dir, workers=workers, retries=retries)
    _atomic_jsonl(run_dir / "raw_manifest_threshold_search_v7.jsonl", raw_records)
    from src.core import data_loader

    if raw_dir not in data_loader._DATA_DIRECTORIES:
        data_loader._DATA_DIRECTORIES.insert(0, raw_dir)
    representation = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    )
    teacher = ExactNativeTeacher(root=root, representation=representation, device=str(device))
    historical_thresholds = _thresholds(root)
    batch_dir = run_dir / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    payloads = []
    for start in range(0, len(rows), 8):
        batch_index = start // 8
        batch_rows = rows[start : start + 8]
        expected_ids = [row["identity_id"] for row in batch_rows]
        batch_path = batch_dir / f"batch_{batch_index:04d}.json"
        if batch_path.is_file():
            payloads.append(_validate_batch(batch_path, run_key=run_key, expected_ids=expected_ids))
            continue
        prepared_by_id = {}
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    prepare_teacher_input,
                    WindowIdentity.from_dict(row["window"]),
                    representation=representation,
                    local_only=True,
                ): row
                for row in batch_rows
            }
            for future in as_completed(futures):
                row = futures[future]
                try:
                    prepared_by_id[row["identity_id"]] = future.result()
                except Exception as exc:
                    failures.append(
                        {
                            "identity_id": row["identity_id"],
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
        if failures:
            raise ContractError(f"v7 threshold-search preparation failed: {failures}")
        prepared = [prepared_by_id[row["identity_id"]] for row in batch_rows]
        teacher_scores, teacher_timings = teacher.score([item.image for item in prepared])
        values = torch.from_numpy(
            np.stack([item.clean_strain for item in prepared]).astype(np.float32, copy=False)
        ).unsqueeze(1).to(device)
        with torch.inference_mode():
            member_scores = torch.sigmoid(ensemble.member_logits(values))
            ensemble_scores = member_scores.mean(dim=-1)
        member_np = member_scores.detach().cpu().numpy()
        ensemble_np = ensemble_scores.detach().cpu().numpy()
        if not np.isfinite(teacher_scores).all() or not np.isfinite(member_np).all():
            raise ContractError("v7 threshold-search scorer produced non-finite output")
        result_rows = []
        for offset, (row, item, teacher_score, student_score) in enumerate(
            zip(batch_rows, prepared, teacher_scores, ensemble_np, strict=True)
        ):
            exact_threshold = historical_thresholds[row["detector"]]
            result_rows.append(
                {
                    "identity_id": row["identity_id"],
                    "window_id": row["window"]["window_id"],
                    "detector": row["detector"],
                    "sampling_role": row["sampling_role"],
                    "block_key": row["block_key"],
                    "raw_strain_sha256": item.raw_strain_sha256,
                    "clean_strain_sha256": item.clean_strain_sha256,
                    "image_sha256": item.image_sha256,
                    "teacher_target": {
                        "native_score": float(teacher_score),
                        "native_score_float32_hex": np.float32(teacher_score).tobytes().hex(),
                        "historical_detector_threshold": exact_threshold,
                        "defer_label": strict_defer_label(float(teacher_score), exact_threshold),
                    },
                    "student": {
                        "ensemble_defer_score": float(student_score),
                        "ensemble_score_float32_hex": np.float32(student_score).tobytes().hex(),
                        "member_defer_scores": [float(value) for value in member_np[offset]],
                    },
                }
            )
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "COMPLETE_THRESHOLD_SEARCH_BATCH",
            "run_key": run_key,
            "batch_index": batch_index,
            "rows": result_rows,
            "teacher_timings_s": teacher_timings,
            "risk_calibration": [],
            "confirmation": [],
            "o4b": [],
        }
        payload = {**body, "batch_digest": canonical_json_sha256(body)}
        _atomic_json(batch_path, payload)
        payloads.append(payload)

    compact = sorted(
        [row for payload in payloads for row in payload["rows"]],
        key=lambda row: row["identity_id"],
    )
    if len(compact) != 240 or len({row["identity_id"] for row in compact}) != 240:
        raise ContractError("v7 threshold-search ledger is incomplete")
    _atomic_jsonl(DEFAULT_COMPACT_ROWS, compact)
    selections = {
        detector: select_detector_threshold(
            [row for row in compact if row["detector"] == detector]
        )
        for detector in DETECTORS
    }
    role_counts = {
        f"{detector}/{role}": {
            "n": sum(
                row["detector"] == detector and row["sampling_role"] == role
                for row in compact
            ),
            "current_exact_teacher_positive": sum(
                row["detector"] == detector
                and row["sampling_role"] == role
                and row["teacher_target"]["defer_label"] == 1
                for row in compact
            ),
        }
        for detector in DETECTORS
        for role in ROLES
    }
    result_body = {
        "schema_version": SCHEMA_VERSION,
        "status": "THRESHOLD_SEARCH_COMPLETE_THRESHOLDS_SELECTED",
        "run_key": run_key,
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "authorization_digest": authorization["authorization_digest"],
        "teacher_stability_receipt_digest": receipt["stability_receipt_digest"],
        "training_artifact_digest": training_summary["artifact_digest"],
        "checkpoint_contract": checkpoints,
        "row_count": len(compact),
        "role_counts": role_counts,
        "selected": selections,
        "compact_rows": {
            "path": DEFAULT_COMPACT_ROWS.relative_to(root).as_posix(),
            "sha256": file_sha256(DEFAULT_COMPACT_ROWS),
            "records_digest": canonical_json_sha256(compact),
        },
        "full_cache": {
            "environment_alias": "DANTE_V7_THRESHOLD_SEARCH_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
            "raw_manifest_sha256": file_sha256(run_dir / "raw_manifest_threshold_search_v7.jsonl"),
            "access_marker_sha256": file_sha256(marker_path),
        },
        "accessed": {
            "threshold_search_identity_ids": [row["identity_id"] for row in compact],
            "risk_calibration": [],
            "confirmation": [],
            "o4b": [],
        },
        "routing_enabled": False,
        "candidate_promoted": False,
    }
    result = {
        **result_body,
        "threshold_search_result_digest": canonical_json_sha256(result_body),
    }
    _atomic_json(DEFAULT_RESULT, result)
    training_contract = load_training_freeze(root=root)
    audit_seed = int(
        canonical_json_sha256(
            {
                "training_contract_digest": training_contract["training_contract_digest"],
                "threshold_search_result_digest": result["threshold_search_result_digest"],
                "purpose": "v7_deterministic_audit_stream",
            }
        )[:16],
        16,
    )
    threshold_body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_PRE_RISK_CALIBRATION",
        "threshold_search_result_digest": result["threshold_search_result_digest"],
        "threshold_search_result_reference": repository_reference(root, DEFAULT_RESULT),
        "compact_rows_reference": repository_reference(root, DEFAULT_COMPACT_ROWS),
        "teacher_stability_receipt_reference": repository_reference(
            root, stability_receipt_path
        ),
        "training_contract_digest": training_contract["training_contract_digest"],
        "detector_thresholds": {
            detector: {
                "defer_score_threshold": selections[detector]["threshold"],
                "threshold_float64_hex": selections[detector]["threshold_float64_hex"],
            }
            for detector in DETECTORS
        },
        "audit_stream": {
            "nominal_fraction": 0.05,
            "seed_uint64": audit_seed,
            "decision": "sha256(seed_uint64:window_id)_uniform_below_0.05",
            "safety_gate_role": False,
            "operational_cost_role": True,
        },
        "failure_rule": "STOP_NO_RETUNE_NO_FALLBACK",
        "accessed": {"risk_calibration": [], "confirmation": [], "o4b": []},
        "routing_enabled": False,
        "candidate_promoted": False,
    }
    threshold_contract = {
        **threshold_body,
        "threshold_contract_digest": canonical_json_sha256(threshold_body),
    }
    _atomic_json(DEFAULT_THRESHOLD_CONTRACT, threshold_contract)
    return result


def verify_threshold_search_result(
    *, root: Path = ROOT, cache_root: Path | None = None
) -> dict[str, Any]:
    authorization = load_threshold_search_authorization(root=root)
    stability = verify_stability_contract(root=root)
    receipt = _read_json(DEFAULT_STABILITY_RECEIPT)
    verify_stability_receipt(receipt, contract=stability)
    if receipt.get("requested_partition") != "threshold_search":
        raise ContractError("v7 threshold-search receipt stage mismatch")
    result = _read_json(DEFAULT_RESULT)
    _verify_digest(result, "threshold_search_result_digest", "v7 threshold-search result")
    if result.get("status") != "THRESHOLD_SEARCH_COMPLETE_THRESHOLDS_SELECTED":
        raise ContractError("v7 threshold-search result is incomplete")
    if (
        result.get("authorization_digest") != authorization["authorization_digest"]
        or result.get("teacher_stability_receipt_digest")
        != receipt["stability_receipt_digest"]
        or result.get("routing_enabled") is not False
        or result.get("candidate_promoted") is not False
        or any(result["accessed"].get(name) for name in ("risk_calibration", "confirmation", "o4b"))
    ):
        raise ContractError("v7 threshold-search boundary or provenance changed")
    compact_path = root / result["compact_rows"]["path"]
    if file_sha256(compact_path) != result["compact_rows"]["sha256"]:
        raise ContractError("v7 threshold-search compact ledger changed")
    rows = _read_jsonl(compact_path)
    if len(rows) != 240 or canonical_json_sha256(rows) != result["compact_rows"]["records_digest"]:
        raise ContractError("v7 threshold-search compact ledger is incomplete")
    replayed = {
        detector: select_detector_threshold([row for row in rows if row["detector"] == detector])
        for detector in DETECTORS
    }
    if replayed != result["selected"]:
        raise ContractError("v7 threshold-search selection does not replay exactly")
    threshold_contract = _read_json(DEFAULT_THRESHOLD_CONTRACT)
    _verify_digest(threshold_contract, "threshold_contract_digest", "v7 threshold contract")
    if (
        threshold_contract.get("status") != "FROZEN_PRE_RISK_CALIBRATION"
        or threshold_contract.get("threshold_search_result_digest")
        != result["threshold_search_result_digest"]
        or threshold_contract.get("failure_rule") != "STOP_NO_RETUNE_NO_FALLBACK"
        or any(
            threshold_contract["accessed"].get(name)
            for name in ("risk_calibration", "confirmation", "o4b")
        )
        or threshold_contract.get("routing_enabled") is not False
        or threshold_contract.get("candidate_promoted") is not False
    ):
        raise ContractError("v7 threshold contract boundary changed")
    for label in (
        "threshold_search_result_reference",
        "compact_rows_reference",
        "teacher_stability_receipt_reference",
    ):
        _resolve_reference(root, threshold_contract[label], label)
    for detector in DETECTORS:
        selected = result["selected"][detector]
        frozen = threshold_contract["detector_thresholds"][detector]
        if (
            frozen["defer_score_threshold"] != selected["threshold"]
            or frozen["threshold_float64_hex"] != selected["threshold_float64_hex"]
        ):
            raise ContractError("v7 selected threshold changed during freeze")
    if cache_root is not None:
        run_dir = cache_root.resolve() / result["full_cache"]["run_subdirectory"]
        if (
            file_sha256(run_dir / "raw_manifest_threshold_search_v7.jsonl")
            != result["full_cache"]["raw_manifest_sha256"]
            or file_sha256(run_dir / "access_started.json")
            != result["full_cache"]["access_marker_sha256"]
        ):
            raise ContractError("v7 threshold-search full cache changed")
    return {
        "status": "PASS_THRESHOLDS_FROZEN_PRE_RISK_CALIBRATION",
        "threshold_search_result_digest": result["threshold_search_result_digest"],
        "threshold_contract_digest": threshold_contract["threshold_contract_digest"],
        "selected": result["selected"],
        "accessed": threshold_contract["accessed"],
    }
