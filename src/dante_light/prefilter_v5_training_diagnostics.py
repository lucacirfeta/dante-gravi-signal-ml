"""Retrospective training-only diagnostics for frozen DANTE-Light v5 students."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time
from typing import Any, Mapping

import numpy as np
from scipy import stats
import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import ROOT, sha256_path
from src.dante_light.prefilter_v5_training import (
    ARMS,
    TrainingCache,
    _model,
    epoch_block_batches,
    student_input,
)
from src.dante_light.prefilter_v5_training_contract import load_training_freeze


DEFAULT_SPEC = ROOT / "config/dante_light_prefilter_v5_training_diagnostic.json"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/diagnostics_v5.json"
)
DETECTORS = ("H1", "L1")
SUBSETS = ("fit", "validation")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _repository_path(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    if set(reference) != {"path", "sha256"}:
        raise ContractError(f"v5 training diagnostic reference is malformed: {label}")
    raw = str(reference["path"])
    relative = Path(raw)
    path = (root / relative).resolve()
    if (
        relative.is_absolute()
        or relative.drive
        or "\\" in raw
        or ".." in relative.parts
        or not path.is_relative_to(root.resolve())
        or not path.is_file()
        or sha256_path(path) != str(reference["sha256"])
    ):
        raise ContractError(f"v5 training diagnostic provenance mismatch: {label}")
    return path


def load_diagnostic_spec(
    path: Path = DEFAULT_SPEC,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema_version") != 1 or spec.get("status") != (
        "FROZEN_RETROSPECTIVE_TRAINING_ONLY_BEFORE_PREDICTION_ACCESS"
    ):
        raise ContractError("v5 training diagnostic specification status mismatch")
    scope = spec.get("scope", {})
    if (
        scope.get("allowed_partition") != "training"
        or scope.get("allowed_internal_subsets") != list(SUBSETS)
        or scope.get("allowed_roles") != ["background"]
        or scope.get("morphology_labels_allowed") is not False
        or scope.get("development_access_allowed") is not False
        or scope.get("confirmation_access_allowed") is not False
        or scope.get("o4b_access_allowed") is not False
        or scope.get("routing_enabled") is not False
    ):
        raise ContractError("v5 training diagnostic protected boundary changed")
    matrix = spec.get("matrix", {})
    if (
        matrix.get("architectures") != list(ARMS)
        or matrix.get("replicate_indices") != list(range(5))
        or matrix.get("detectors") != list(DETECTORS)
        or matrix.get("internal_subsets") != list(SUBSETS)
    ):
        raise ContractError("v5 training diagnostic matrix changed")
    metrics = spec.get("metrics", {})
    if metrics.get("pass_fail_threshold") is not None or metrics.get(
        "uncertainty_interval"
    ) is not None:
        raise ContractError("v5 training diagnostic silently introduced a gate")
    boundary = spec.get("interpretation_boundary", {})
    if (
        boundary.get("retrospective_exploratory_only") is not True
        or boundary.get("candidate_promotion_allowed") is not False
        or boundary.get("may_change_v5_status") is not False
        or boundary.get("may_authorize_confirmation") is not False
        or boundary.get("may_authorize_o4b") is not False
    ):
        raise ContractError("v5 training diagnostic interpretation boundary changed")
    for label, reference in spec.get("parent_references", {}).items():
        _repository_path(root, reference, label)
    return spec


def diagnostic_metrics(
    targets: np.ndarray,
    predictions: np.ndarray,
    *,
    beta: float,
) -> dict[str, Any]:
    targets = np.asarray(targets, dtype=np.float64)
    predictions = np.asarray(predictions, dtype=np.float64)
    if (
        targets.ndim != 1
        or predictions.shape != targets.shape
        or targets.size < 2
        or not np.isfinite(targets).all()
        or not np.isfinite(predictions).all()
        or not math.isfinite(float(beta))
        or beta <= 0.0
    ):
        raise ContractError("invalid v5 training diagnostic metric input")
    if float(np.std(targets, ddof=0)) == 0.0 or float(
        np.std(predictions, ddof=0)
    ) == 0.0:
        raise ContractError("non-finite v5 training diagnostic metric: constant input")
    spearman = float(stats.spearmanr(targets, predictions).statistic)
    pearson = float(stats.pearsonr(targets, predictions).statistic)
    residual = np.abs(predictions - targets)
    smooth_l1 = np.where(
        residual < beta,
        0.5 * residual**2 / beta,
        residual - 0.5 * beta,
    )
    values = {
        "count": int(targets.size),
        "spearman": spearman,
        "pearson": pearson,
        "smooth_l1": float(np.mean(smooth_l1)),
        "prediction_standard_deviation_ddof0": float(np.std(predictions, ddof=0)),
        "target_standard_deviation_ddof0": float(np.std(targets, ddof=0)),
    }
    if not all(math.isfinite(float(value)) for key, value in values.items() if key != "count"):
        raise ContractError("non-finite v5 training diagnostic metric")
    return values


def _load_models(
    *,
    training: Mapping[str, Any],
    cache_root: Path,
    device: torch.device,
) -> tuple[dict[tuple[str, int], torch.nn.Module], Path]:
    run_dir = (cache_root / f"student_{training['run_key']}").resolve()
    models: dict[tuple[str, int], torch.nn.Module] = {}
    for row in training["replicate_summaries"]:
        arm = str(row["arm"])
        replicate = int(row["replicate_index"])
        if row.get("status") != "TRAINING_COMPLETE":
            raise ContractError("v5 training diagnostic found an incomplete replicate")
        checkpoint = (run_dir / row["best_model"]["path"]).resolve()
        if (
            not checkpoint.is_relative_to(run_dir)
            or sha256_path(checkpoint) != row["best_model"]["sha256"]
        ):
            raise ContractError("v5 training diagnostic checkpoint mismatch")
        state = torch.load(checkpoint, map_location=device, weights_only=True)
        model = _model(arm).to(device=device, dtype=torch.float32)
        model.load_state_dict(state["model_state"])
        model.eval()
        models[(arm, replicate)] = model
    expected = {(arm, replicate) for arm in ARMS for replicate in range(5)}
    if set(models) != expected:
        raise ContractError("v5 training diagnostic model matrix is incomplete")
    return models, run_dir


def run_training_diagnostics(
    *,
    root: Path = ROOT,
    spec_path: Path = DEFAULT_SPEC,
    cache_root: Path,
    device_name: str | None,
    code_references: Mapping[str, Mapping[str, str]],
    output_path: Path | None = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    started = time.perf_counter()
    spec = load_diagnostic_spec(spec_path, root=root)
    for label, reference in code_references.items():
        _repository_path(root, reference, label)
    parents = spec["parent_references"]
    contract = load_training_freeze(
        root / parents["training_contract"]["path"], root=root
    )
    training = json.loads(
        (root / parents["training_summary"]["path"]).read_text(encoding="utf-8")
    )
    training_body = dict(training)
    training_digest = training_body.pop("artifact_digest", None)
    if training_digest != canonical_json_sha256(training_body):
        raise ContractError("v5 training diagnostic parent summary digest mismatch")
    if any(
        training.get(field)
        for field in (
            "development_rows_accessed",
            "confirmation_rows_accessed",
            "o4b_rows_accessed",
        )
    ):
        raise ContractError("v5 training diagnostic parent accessed protected outcomes")
    device = torch.device(
        device_name or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    models, _run_dir = _load_models(
        training=training,
        cache_root=cache_root.resolve(),
        device=device,
    )
    cache = TrainingCache(root=root, contract=contract, cache_root=cache_root.resolve())
    protocol = json.loads(
        (root / contract["source_references"]["protocol"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    stft_contract = protocol["approved_design"]["students"]["complex_stft_2d"]["stft"]
    beta = float(contract["design"]["optimization"]["loss"]["beta"])
    blocks_per_detector_batch = int(
        contract["design"]["optimization"]["batch"]["H1_size"]
    ) // 8
    collected: dict[tuple[str, int, str, str], dict[str, list[np.ndarray]]] = {}
    accessed_counts: dict[str, dict[str, int]] = {}
    with torch.no_grad():
        for subset in SUBSETS:
            batches = epoch_block_batches(
                cache.block_indices(subset),
                seed=0,
                epoch=0,
                blocks_per_detector_batch=blocks_per_detector_batch,
                shuffle=False,
            )
            subset_counts = {detector: 0 for detector in DETECTORS}
            for h1_blocks, l1_blocks in batches:
                batch = cache.load_batch(h1_blocks, l1_blocks)
                for detector, detector_value in (("H1", 0), ("L1", 1)):
                    subset_counts[detector] += int(np.sum(batch.detectors == detector_value))
                for arm in ARMS:
                    inputs = student_input(
                        batch.strain,
                        arm=arm,
                        stft_contract=stft_contract,
                    ).to(device=device, dtype=torch.float32)
                    for replicate in range(5):
                        predictions = (
                            models[(arm, replicate)](inputs)
                            .squeeze(-1)
                            .detach()
                            .cpu()
                            .numpy()
                            .astype(np.float64)
                        )
                        if not np.isfinite(predictions).all():
                            raise ContractError("v5 training diagnostic prediction is non-finite")
                        for detector, detector_value in (("H1", 0), ("L1", 1)):
                            mask = batch.detectors == detector_value
                            key = (arm, replicate, subset, detector)
                            record = collected.setdefault(
                                key, {"targets": [], "predictions": []}
                            )
                            record["targets"].append(
                                np.asarray(batch.targets[mask], dtype=np.float64)
                            )
                            record["predictions"].append(predictions[mask])
                    del inputs
            accessed_counts[subset] = subset_counts
    results: dict[str, Any] = {}
    for arm in ARMS:
        replicates = []
        for replicate in range(5):
            subsets: dict[str, Any] = {}
            for subset in SUBSETS:
                detector_metrics = {}
                for detector in DETECTORS:
                    record = collected[(arm, replicate, subset, detector)]
                    detector_metrics[detector] = diagnostic_metrics(
                        np.concatenate(record["targets"]),
                        np.concatenate(record["predictions"]),
                        beta=beta,
                    )
                subsets[subset] = detector_metrics
            replicates.append(
                {"replicate_index": replicate, "subsets": subsets}
            )
        results[arm] = {"replicates": replicates}
    body = {
        "schema_version": 1,
        "status": "COMPLETE_RETROSPECTIVE_TRAINING_ONLY_DIAGNOSTIC",
        "diagnostic_spec": {
            "path": spec_path.resolve().relative_to(root.resolve()).as_posix(),
            "sha256": sha256_path(spec_path),
        },
        "parent_training_artifact_digest": training_digest,
        "training_run_key": training["run_key"],
        "code_references": dict(code_references),
        "environment": {
            "python": os.sys.version.split()[0],
            "numpy": np.__version__,
            "scipy": __import__("scipy").__version__,
            "torch": torch.__version__,
            "device_type": device.type,
            "device_name": (
                torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu"
            ),
            "automatic_mixed_precision": False,
        },
        "training_rows_accessed": accessed_counts,
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
        "morphology_labels_accessed": [],
        "candidate_promotion_allowed": False,
        "routing_enabled": False,
        "pass_fail_gate_evaluated": False,
        "results": results,
        "result_matrix_digest": canonical_json_sha256(results),
        "elapsed_s": time.perf_counter() - started,
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    if output_path is not None:
        _atomic_json(output_path, result)
    return result


def verify_diagnostic_result(
    result: Mapping[str, Any],
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    payload = dict(result)
    declared = payload.pop("artifact_digest", None)
    if declared != canonical_json_sha256(payload):
        raise ContractError("v5 training diagnostic result digest mismatch")
    if payload.get("status") != "COMPLETE_RETROSPECTIVE_TRAINING_ONLY_DIAGNOSTIC":
        raise ContractError("v5 training diagnostic result status mismatch")
    if (
        payload.get("development_rows_accessed")
        or payload.get("confirmation_rows_accessed")
        or payload.get("o4b_rows_accessed")
        or payload.get("morphology_labels_accessed")
        or payload.get("candidate_promotion_allowed") is not False
        or payload.get("routing_enabled") is not False
        or payload.get("pass_fail_gate_evaluated") is not False
    ):
        raise ContractError("v5 training diagnostic result crossed its boundary")
    _repository_path(root, payload["diagnostic_spec"], "diagnostic_spec")
    for label, reference in payload["code_references"].items():
        _repository_path(root, reference, label)
    spec = load_diagnostic_spec(
        root / payload["diagnostic_spec"]["path"], root=root
    )
    contract = load_training_freeze(
        root / spec["parent_references"]["training_contract"]["path"], root=root
    )
    expected_counts = contract["internal_split"]["row_counts"]
    for subset in SUBSETS:
        for detector in DETECTORS:
            if int(payload["training_rows_accessed"][subset][detector]) != int(
                expected_counts[detector][subset]
            ):
                raise ContractError("v5 training diagnostic row count mismatch")
    results = payload.get("results", {})
    if payload.get("result_matrix_digest") != canonical_json_sha256(results):
        raise ContractError("v5 training diagnostic result matrix digest mismatch")
    if set(results) != set(ARMS):
        raise ContractError("v5 training diagnostic architecture matrix mismatch")
    metric_count = 0
    for arm in ARMS:
        replicates = results[arm].get("replicates", [])
        if [row.get("replicate_index") for row in replicates] != list(range(5)):
            raise ContractError("v5 training diagnostic replicate matrix mismatch")
        for row in replicates:
            if set(row.get("subsets", {})) != set(SUBSETS):
                raise ContractError("v5 training diagnostic subset matrix mismatch")
            for subset in SUBSETS:
                by_detector = row["subsets"][subset]
                if set(by_detector) != set(DETECTORS):
                    raise ContractError("v5 training diagnostic detector matrix mismatch")
                for detector in DETECTORS:
                    values = by_detector[detector]
                    if int(values["count"]) != int(expected_counts[detector][subset]):
                        raise ContractError("v5 training diagnostic metric count mismatch")
                    for name in (
                        "spearman",
                        "pearson",
                        "smooth_l1",
                        "prediction_standard_deviation_ddof0",
                        "target_standard_deviation_ddof0",
                    ):
                        if not math.isfinite(float(values[name])):
                            raise ContractError("v5 training diagnostic metric is non-finite")
                    if not -1.0 <= float(values["spearman"]) <= 1.0:
                        raise ContractError("v5 training diagnostic Spearman is invalid")
                    if not -1.0 <= float(values["pearson"]) <= 1.0:
                        raise ContractError("v5 training diagnostic Pearson is invalid")
                    if min(
                        float(values["smooth_l1"]),
                        float(values["prediction_standard_deviation_ddof0"]),
                        float(values["target_standard_deviation_ddof0"]),
                    ) < 0.0:
                        raise ContractError("v5 training diagnostic scale metric is invalid")
                    metric_count += 1
    return {
        "status": "PASS_VERIFIED_RETROSPECTIVE_TRAINING_ONLY_DIAGNOSTIC",
        "artifact_digest": declared,
        "metric_cells": metric_count,
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
        "candidate_promotion_allowed": False,
    }
