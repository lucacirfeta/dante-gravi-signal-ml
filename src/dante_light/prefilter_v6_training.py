"""Deterministic five-arm Phase-B screening for DANTE-Light v6."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import spearmanr
import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path
from src.dante_light.prefilter_v5_training import (
    NumericalTrainingFailure,
    _atomic_json,
    _atomic_torch,
    _finite_optimizer,
    _finite_tensor,
    deterministic_environment,
    epoch_block_batches,
    training_environment,
)
from src.dante_light.prefilter_v6_phase_a import (
    aggregation_contract,
    build_candidate,
    load_phase_a_contract,
)
from src.dante_light.prefilter_v6_phase_b import (
    detector_balanced_smooth_l1,
    equal_gradient_backward,
    load_phase_b_contract,
    ranknet_block_loss,
    select_phase_b_arm,
)
from src.dante_light.prefilter_v6_training_contract import (
    DEFAULT_CONTRACT,
    load_training_freeze,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "artifacts/dante_light/prefilter_l4_v6_training/phase_b_screening_summary_v6.json"
DEFAULT_CACHE = Path(
    os.environ.get(
        "DANTE_V6_TRAINING_CACHE_ROOT",
        r"E:\dante_cache\dante_light\prefilter_l4_v6_training",
    )
)


def _float32_from_hex(value: str) -> np.float32:
    raw = bytes.fromhex(value)
    if len(raw) != 4:
        raise ContractError("v6 training target is not one float32")
    result = np.frombuffer(raw, dtype=np.float32)[0]
    if not np.isfinite(result):
        raise NumericalTrainingFailure("non-finite v6 teacher target")
    return result


@dataclass(frozen=True, slots=True)
class BlockBatch:
    strain: np.ndarray
    targets: np.ndarray
    detectors: np.ndarray
    block_indices: np.ndarray
    window_ids: tuple[str, ...]


class TrainingCache:
    def __init__(self, *, root: Path, contract: Mapping[str, Any], cache_root: Path) -> None:
        self.root = root
        self.contract = contract
        summary_ref = contract["source_references"]["teacher_ledger_summary"]
        self.summary = json.loads((root / summary_ref["path"]).read_text(encoding="utf-8"))
        self.run_dir = (cache_root / self.summary["cache_location"]["run_subdirectory"]).resolve()
        target_ref = contract["source_references"]["teacher_targets_compact"]
        rows = [
            json.loads(line)
            for line in (root / target_ref["path"]).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in rows:
            self.by_key.setdefault((row["detector"], int(row["block_index"])), []).append(row)
        for block_rows in self.by_key.values():
            block_rows.sort(key=lambda row: int(row["window_index"]))
            if len(block_rows) != 8:
                raise ContractError("v6 training cache block does not contain eight windows")
        self._verified_shards: set[Path] = set()

    def block_indices(self, subset: str) -> dict[str, list[int]]:
        return {
            detector: sorted(
                index
                for (current, index), rows in self.by_key.items()
                if current == detector and rows[0]["subset"] == subset
            )
            for detector in ("H1", "L1")
        }

    def _block(self, detector: str, block_index: int) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
        rows = self.by_key[(detector, int(block_index))]
        shard_paths = {row["strain_shard_path"] for row in rows}
        shard_hashes = {row["strain_shard_sha256"] for row in rows}
        if len(shard_paths) != 1 or len(shard_hashes) != 1:
            raise ContractError("v6 training shard provenance differs within block")
        shard = (self.run_dir / next(iter(shard_paths))).resolve()
        if not shard.is_relative_to(self.run_dir):
            raise ContractError("v6 training shard escaped its cache run")
        if shard not in self._verified_shards:
            if not shard.is_file() or sha256_path(shard) != next(iter(shard_hashes)):
                raise ContractError("v6 training strain shard hash mismatch")
            self._verified_shards.add(shard)
        with np.load(shard, allow_pickle=False) as payload:
            strain = np.asarray(payload["clean_strain"], dtype=np.float32)
            stored_ids = tuple(str(value) for value in payload["window_ids"].tolist())
        position = {window_id: index for index, window_id in enumerate(stored_ids)}
        expected_ids = tuple(row["window_id"] for row in rows)
        if set(position) != set(expected_ids) or strain.shape[0] != 8:
            raise ContractError("v6 training strain shard identity mismatch")
        strain = np.stack([strain[position[window_id]] for window_id in expected_ids])
        targets = np.asarray(
            [_float32_from_hex(row["teacher_target_float32_hex"]) for row in rows],
            dtype=np.float32,
        )
        scale = self.contract["target_standardization"][detector]
        targets = (targets - np.float32(scale["mean_float64"])) / np.float32(
            scale["standard_deviation_float64_ddof0"]
        )
        if not np.isfinite(strain).all() or not np.isfinite(targets).all():
            raise NumericalTrainingFailure("non-finite v6 training data")
        return strain, targets, expected_ids

    def load_batch(self, h1_blocks: Sequence[int], l1_blocks: Sequence[int]) -> BlockBatch:
        strain_parts, target_parts, detector_parts, block_parts = [], [], [], []
        window_ids: list[str] = []
        for detector_value, (detector, indices) in enumerate(
            (("H1", h1_blocks), ("L1", l1_blocks))
        ):
            for block_index in indices:
                strain, targets, identities = self._block(detector, int(block_index))
                strain_parts.append(strain)
                target_parts.append(targets)
                detector_parts.append(np.full(8, detector_value, dtype=np.int8))
                block_parts.append(np.full(8, int(block_index), dtype=np.int64))
                window_ids.extend(identities)
        return BlockBatch(
            strain=np.concatenate(strain_parts),
            targets=np.concatenate(target_parts),
            detectors=np.concatenate(detector_parts),
            block_indices=np.concatenate(block_parts),
            window_ids=tuple(window_ids),
        )


def _phase_a_inputs(root: Path) -> tuple[dict[str, Any], dict[str, Any], Any]:
    phase_a = load_phase_a_contract(root / "config/dante_light_prefilter_v6_phase_a.json", root=root)
    teacher = json.loads((root / "config/dante_light_prefilter_v5_teacher_contract.json").read_text(encoding="utf-8"))
    aggregation = aggregation_contract(phase_a, teacher)
    candidates = {row["id"]: row for row in phase_a["candidate_matrix"]}
    return phase_a, candidates, aggregation


def _model(root: Path, architecture_id: str) -> torch.nn.Module:
    _phase_a, candidates, aggregation = _phase_a_inputs(root)
    if architecture_id not in candidates:
        raise ContractError(f"unknown v6 architecture: {architecture_id}")
    return build_candidate(candidates[architecture_id], aggregation)


def _optimizer(model: torch.nn.Module, contract: Mapping[str, Any]) -> torch.optim.AdamW:
    spec = contract["optimization"]["optimizer"]
    return torch.optim.AdamW(
        model.parameters(),
        lr=float(spec["learning_rate"]),
        weight_decay=float(spec["weight_decay"]),
        betas=tuple(float(value) for value in spec["betas"]),
        eps=float(spec["epsilon"]),
        amsgrad=bool(spec["amsgrad"]),
    )


def _reshape(values: torch.Tensor, blocks_per_detector: int) -> torch.Tensor:
    return values.reshape(2, blocks_per_detector, 8)


def _validation_metrics(
    *,
    model: torch.nn.Module,
    cache: TrainingCache,
    batches: Sequence[tuple[list[int], list[int]]],
    device: torch.device,
    limit_batches: int | None,
) -> dict[str, Any]:
    model.eval()
    predictions: dict[str, list[float]] = {"H1": [], "L1": []}
    targets: dict[str, list[float]] = {"H1": [], "L1": []}
    with torch.no_grad():
        for batch_index, (h1_blocks, l1_blocks) in enumerate(batches):
            if limit_batches is not None and batch_index >= limit_batches:
                break
            batch = cache.load_batch(h1_blocks, l1_blocks)
            inputs = torch.from_numpy(batch.strain[:, None, :]).to(device)
            output = model(inputs).squeeze(-1)
            _finite_tensor(output, "v6 validation prediction")
            for detector, value in (("H1", 0), ("L1", 1)):
                mask = batch.detectors == value
                predictions[detector].extend(output.detach().cpu().numpy()[mask].astype(float).tolist())
                targets[detector].extend(batch.targets[mask].astype(float).tolist())
    cells: dict[str, dict[str, float | int]] = {}
    for detector in ("H1", "L1"):
        if len(predictions[detector]) == 0:
            raise ContractError("v6 validation did not observe both detectors")
        correlation = float(spearmanr(targets[detector], predictions[detector]).statistic)
        prediction_tensor = torch.tensor(predictions[detector], dtype=torch.float64)
        target_tensor = torch.tensor(targets[detector], dtype=torch.float64)
        smooth = float(torch.nn.functional.smooth_l1_loss(prediction_tensor, target_tensor, beta=1.0).item())
        cells[detector] = {"n": len(predictions[detector]), "spearman": correlation, "smooth_l1": smooth}
    return {
        "by_detector": cells,
        "minimum_detector_spearman": min(float(cell["spearman"]) for cell in cells.values()),
        "equal_detector_mean_smooth_l1": float(np.mean([cell["smooth_l1"] for cell in cells.values()])),
    }


def _checkpoint_better(candidate: Mapping[str, Any], incumbent: Mapping[str, Any] | None) -> bool:
    if incumbent is None:
        return True
    candidate_key = (
        float(candidate["minimum_detector_spearman"]),
        -float(candidate["equal_detector_mean_smooth_l1"]),
    )
    incumbent_key = (
        float(incumbent["minimum_detector_spearman"]),
        -float(incumbent["equal_detector_mean_smooth_l1"]),
    )
    return candidate_key > incumbent_key


def train_replicate(
    *,
    root: Path,
    contract: Mapping[str, Any],
    cache: TrainingCache,
    run_dir: Path,
    run_key: str,
    arm: Mapping[str, Any],
    replicate_index: int,
    seed: int,
    device: torch.device,
    smoke: bool,
    limit_batches: int | None,
) -> dict[str, Any]:
    arm_id = str(arm["id"])
    replicate_dir = run_dir / arm_id / f"replicate_{replicate_index}"
    summary_path = replicate_dir / "replicate_summary.json"
    if summary_path.is_file():
        saved = json.loads(summary_path.read_text(encoding="utf-8"))
        if saved.get("run_key") != run_key or saved.get("seed") != seed:
            raise ContractError("v6 replicate cache identity collision")
        return saved
    deterministic_environment(seed)
    model = _model(root, str(arm["architecture_id"])).to(device=device, dtype=torch.float32)
    optimizer = _optimizer(model, contract)
    fit_blocks = cache.block_indices("fit")
    validation_blocks = cache.block_indices("internal_validation")
    blocks_per_detector = int(contract["optimization"]["batch"]["blocks_per_detector"])
    validation_batches = epoch_block_batches(
        validation_blocks,
        seed=seed,
        epoch=0,
        blocks_per_detector_batch=blocks_per_detector,
        shuffle=False,
    )
    maximum_epochs = 1 if smoke else int(contract["optimization"]["maximum_epochs"])
    identity = {
        "schema_version": 1,
        "run_key": run_key,
        "arm_id": arm_id,
        "architecture_id": arm["architecture_id"],
        "objective_id": arm["objective_id"],
        "replicate_index": replicate_index,
        "seed": seed,
        "smoke": smoke,
        "limit_batches": limit_batches,
        "phase_c_rows_accessed": [],
        "phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
        "morphology_labels_accessed": [],
    }
    replicate_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(replicate_dir / "run_identity.json", identity)
    latest_path = replicate_dir / "latest_state.pt"
    metrics: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    start_epoch = 1
    if latest_path.is_file():
        state = torch.load(latest_path, map_location=device, weights_only=True)
        if state["run_key"] != run_key or state["seed"] != seed:
            raise ContractError("v6 checkpoint identity collision")
        model.load_state_dict(state["model_state"])
        optimizer.load_state_dict(state["optimizer_state"])
        metrics = state["metrics"]
        best = state["best"]
        start_epoch = int(state["epoch"]) + 1
    started = time.perf_counter()
    try:
        for epoch in range(start_epoch, maximum_epochs + 1):
            model.train()
            batches = epoch_block_batches(
                fit_blocks,
                seed=seed,
                epoch=epoch,
                blocks_per_detector_batch=blocks_per_detector,
                shuffle=True,
            )
            value_total = 0.0
            rank_total = 0.0
            step_count = 0
            equal_steps: list[dict[str, float]] = []
            epoch_started = time.perf_counter()
            for batch_index, (h1_blocks, l1_blocks) in enumerate(batches):
                if limit_batches is not None and batch_index >= limit_batches:
                    break
                batch = cache.load_batch(h1_blocks, l1_blocks)
                inputs = torch.from_numpy(batch.strain[:, None, :]).to(device)
                targets = torch.from_numpy(batch.targets).to(device)
                _finite_tensor(inputs, "v6 fit input")
                _finite_tensor(targets, "v6 fit target")
                optimizer.zero_grad(set_to_none=True)
                predictions = model(inputs).squeeze(-1)
                shaped_predictions = _reshape(predictions, len(h1_blocks))
                shaped_targets = _reshape(targets, len(h1_blocks))
                value_loss = detector_balanced_smooth_l1(
                    shaped_predictions,
                    shaped_targets,
                    beta=float(contract["objective"]["value"]["beta"]),
                )
                _finite_tensor(value_loss, "v6 value loss")
                if arm["objective_id"] == "equal_gradient_smooth_l1_ranknet":
                    rank_loss = ranknet_block_loss(shaped_predictions, shaped_targets)
                    _finite_tensor(rank_loss, "v6 rank loss")
                    try:
                        equal_steps.append(
                            equal_gradient_backward(
                                value_loss=value_loss,
                                rank_loss=rank_loss,
                                parameters=tuple(model.parameters()),
                            )
                        )
                    except ContractError as exc:
                        raise NumericalTrainingFailure(str(exc)) from exc
                    rank_total += float(rank_loss.item())
                else:
                    value_loss.backward()
                for parameter in model.parameters():
                    if parameter.grad is not None:
                        _finite_tensor(parameter.grad, "v6 gradient")
                optimizer.step()
                for parameter in model.parameters():
                    _finite_tensor(parameter, "v6 parameter")
                _finite_optimizer(optimizer)
                value_total += float(value_loss.item())
                step_count += 1
            if step_count == 0:
                raise ContractError("v6 training epoch observed no fit blocks")
            validation = _validation_metrics(
                model=model,
                cache=cache,
                batches=validation_batches,
                device=device,
                limit_batches=limit_batches,
            )
            primary = float(validation["minimum_detector_spearman"])
            eligible = math.isfinite(primary)
            metric = {
                "epoch": epoch,
                "fit_value_loss_step_mean": value_total / step_count,
                "fit_rank_loss_step_mean": (
                    rank_total / step_count
                    if arm["objective_id"] == "equal_gradient_smooth_l1_ranknet"
                    else None
                ),
                "validation": validation,
                "checkpoint_eligible": eligible,
                "equal_gradient_step_diagnostics": equal_steps,
                "learning_rate": float(optimizer.param_groups[0]["lr"]),
                "fit_step_count": step_count,
                "elapsed_s": time.perf_counter() - epoch_started,
            }
            metrics.append(metric)
            if eligible and _checkpoint_better(validation, None if best is None else best["validation"]):
                best = {"epoch": epoch, "validation": validation}
                _atomic_torch(
                    replicate_dir / "best_model.pt",
                    {
                        "schema_version": 1,
                        "run_key": run_key,
                        "arm_id": arm_id,
                        "replicate_index": replicate_index,
                        "seed": seed,
                        "epoch": epoch,
                        "validation": validation,
                        "model_state": model.state_dict(),
                    },
                )
            _atomic_torch(
                latest_path,
                {
                    "schema_version": 1,
                    "run_key": run_key,
                    "seed": seed,
                    "epoch": epoch,
                    "best": best,
                    "model_state": model.state_dict(),
                    "optimizer_state": optimizer.state_dict(),
                    "metrics": metrics,
                },
            )
            _atomic_json(replicate_dir / "metrics.json", {"epochs": metrics})
    except NumericalTrainingFailure as exc:
        body = {
            **identity,
            "status": "FAILED_NUMERICAL",
            "reason": str(exc),
            "completed_epochs": len(metrics),
            "candidate_promotion_allowed": False,
        }
        summary = {**body, "replicate_digest": canonical_json_sha256(body)}
        _atomic_json(summary_path, summary)
        return summary
    if best is None:
        body = {
            **identity,
            "status": "FAILED_DEGENERATE_REPLICATE",
            "completed_epochs": len(metrics),
            "candidate_promotion_allowed": False,
        }
    else:
        best_path = replicate_dir / "best_model.pt"
        body = {
            **identity,
            "status": "SMOKE_COMPLETE_NON_PROMOTABLE" if smoke else "TRAINING_COMPLETE",
            "completed_epochs": len(metrics),
            "best_epoch": best["epoch"],
            "best_validation": best["validation"],
            "best_model": {
                "path": best_path.relative_to(run_dir).as_posix(),
                "sha256": sha256_path(best_path),
            },
            "metrics": {
                "path": (replicate_dir / "metrics.json").relative_to(run_dir).as_posix(),
                "sha256": sha256_path(replicate_dir / "metrics.json"),
            },
            "elapsed_this_invocation_s": time.perf_counter() - started,
            "candidate_promotion_allowed": False,
        }
    summary = {**body, "replicate_digest": canonical_json_sha256(body)}
    _atomic_json(summary_path, summary)
    return summary


def training_run_key(
    contract: Mapping[str, Any],
    *,
    code_references: Mapping[str, Mapping[str, str]],
    environment: Mapping[str, Any],
    smoke: bool,
    smoke_batches: int | None,
) -> str:
    return canonical_json_sha256(
        {
            "training_contract_digest": contract["training_contract_digest"],
            "code_references": dict(code_references),
            "environment": dict(environment),
            "smoke": smoke,
            "smoke_batches": smoke_batches,
        }
    )


def run_training(
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    cache_root: Path = DEFAULT_CACHE,
    code_references: Mapping[str, Mapping[str, str]],
    device_name: str | None = None,
    arm_ids: Sequence[str] | None = None,
    replicate_indices: Sequence[int] | None = None,
    smoke: bool = False,
    smoke_batches: int | None = None,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    contract = load_training_freeze(contract_path, root=root)
    phase_b = load_phase_b_contract(root=root)
    arms_by_id = {row["id"]: row for row in contract["arms"]}
    selected_arms = list(arms_by_id) if arm_ids is None else [str(value) for value in arm_ids]
    if len(selected_arms) != len(set(selected_arms)) or any(value not in arms_by_id for value in selected_arms):
        raise ContractError("v6 training requested an invalid or duplicate arm")
    seeds = [int(value) for value in contract["replicate_seeds"]]
    selected_replicates = list(range(len(seeds))) if replicate_indices is None else [int(value) for value in replicate_indices]
    if len(selected_replicates) != len(set(selected_replicates)) or any(
        value < 0 or value >= len(seeds) for value in selected_replicates
    ):
        raise ContractError("v6 training requested an invalid replicate")
    if smoke != (smoke_batches is not None):
        raise ContractError("v6 smoke mode and batch limit must be specified together")
    if smoke and int(smoke_batches) < 1:
        raise ContractError("v6 smoke batch limit must be positive")
    device = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))
    environment = training_environment(device)
    run_key = training_run_key(
        contract,
        code_references=code_references,
        environment=environment,
        smoke=smoke,
        smoke_batches=smoke_batches,
    )
    run_dir = cache_root.resolve() / f"student_{run_key}"
    identity = {
        "schema_version": 1,
        "run_key": run_key,
        "training_contract_digest": contract["training_contract_digest"],
        "code_references": dict(code_references),
        "environment": environment,
        "smoke": smoke,
        "smoke_batches": smoke_batches,
        "phase_c_rows_accessed": [],
        "phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
        "morphology_labels_accessed": [],
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file():
        if json.loads(identity_path.read_text(encoding="utf-8")) != identity:
            raise ContractError("v6 training run identity collision")
    else:
        _atomic_json(identity_path, identity)
    cache = TrainingCache(root=root, contract=contract, cache_root=cache_root.resolve())
    summaries = []
    for arm_id in selected_arms:
        for replicate_index in selected_replicates:
            summaries.append(
                train_replicate(
                    root=root,
                    contract=contract,
                    cache=cache,
                    run_dir=run_dir,
                    run_key=run_key,
                    arm=arms_by_id[arm_id],
                    replicate_index=replicate_index,
                    seed=seeds[replicate_index],
                    device=device,
                    smoke=smoke,
                    limit_batches=smoke_batches,
                )
            )
    full_request = set(selected_arms) == set(arms_by_id) and selected_replicates == list(range(len(seeds)))
    arm_results = []
    phase_a_artifact = json.loads(
        (root / "artifacts/dante_light/prefilter_l4_v6_design/phase_a_compute_feasibility_v6.json").read_text(
            encoding="utf-8"
        )
    )
    for arm_id in selected_arms:
        current = [row for row in summaries if row["arm_id"] == arm_id]
        arm = arms_by_id[arm_id]
        architecture = arm["architecture_id"]
        static = phase_a_artifact["results"][architecture]["static"]
        cpu = phase_a_artifact["results"][architecture]["devices"]["cpu"]["inference_only"]["mean_s"]
        cells = []
        for row in current:
            if row["status"] != "TRAINING_COMPLETE":
                continue
            for detector, metrics in row["best_validation"]["by_detector"].items():
                cells.append(
                    {
                        "detector": detector,
                        "replicate_index": row["replicate_index"],
                        "spearman": metrics["spearman"],
                        "smooth_l1": metrics["smooth_l1"],
                    }
                )
        arm_results.append(
            {
                "arm_id": arm_id,
                "architecture_id": architecture,
                "objective_id": arm["objective_id"],
                "numerical_failure": any(row["status"].startswith("FAILED") for row in current),
                "validation_cells": cells,
                "audited_cpu_mean_inference_s": cpu,
                "trainable_parameters": static["trainable_parameters"],
            }
        )
    selection = None
    if not smoke and full_request:
        selection = select_phase_b_arm(arm_results, contract=phase_b)
    status = (
        "FAILED_NUMERICAL"
        if any(row["status"].startswith("FAILED") for row in summaries)
        else "SMOKE_COMPLETE_NON_PROMOTABLE"
        if smoke
        else "PHASE_B_SCREENING_COMPLETE"
    )
    body = {
        **identity,
        "status": status,
        "full_request": full_request,
        "arm_ids": selected_arms,
        "replicate_indices": selected_replicates,
        "replicate_summaries": summaries,
        "arm_results": arm_results,
        "selection": selection,
        "phase_c_automatic_access": False,
        "phase_c_rows_accessed": [],
        "phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
        "morphology_labels_accessed": [],
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "phase_b_screening_summary_v6.json", summary)
    if not smoke and full_request:
        _atomic_json(output_path, summary)
    return summary
