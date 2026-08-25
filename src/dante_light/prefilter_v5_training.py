"""Deterministic training-only distillation for DANTE-Light v5."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import random
import time
from typing import Any, Mapping, Sequence

import numpy as np
from scipy import signal
import torch

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_student import (
    ComplexSTFT2DStudentProxy,
    Raw1DDepthwiseStudentProxy,
)
from src.dante_light.prefilter_v5_protocol import ROOT, sha256_path
from src.dante_light.prefilter_v5_teacher import default_cache_root
from src.dante_light.prefilter_v5_training_contract import (
    DEFAULT_CONTRACT,
    load_training_freeze,
)


SCHEMA_VERSION = 1
ARMS = ("raw_1d_depthwise", "complex_stft_2d")
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/student_training_summary_v5.json"
)


class NumericalTrainingFailure(RuntimeError):
    """A fail-closed non-finite condition attributable to one replicate."""


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(
        (json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n").encode(
            "utf-8"
        )
    )
    temporary.replace(path)


def _atomic_torch(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(value), temporary)
    temporary.replace(path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _float32_from_hex(value: str) -> np.float32:
    raw = bytes.fromhex(value)
    if len(raw) != 4:
        raise ContractError("v5 training target is not one float32")
    result = np.frombuffer(raw, dtype=np.float32)[0]
    if not np.isfinite(result):
        raise NumericalTrainingFailure("non-finite teacher target")
    return result


def _finite_tensor(value: torch.Tensor, label: str) -> None:
    if not torch.isfinite(value).all().item():
        raise NumericalTrainingFailure(f"non-finite {label}")


def _finite_optimizer(optimizer: torch.optim.Optimizer) -> None:
    for state in optimizer.state.values():
        for value in state.values():
            if isinstance(value, torch.Tensor):
                _finite_tensor(value, "optimizer state")


def deterministic_environment(seed: int) -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(int(seed))
    np.random.seed(int(seed) % (2**32))
    torch.manual_seed(int(seed))
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(int(seed))
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True


def epoch_block_batches(
    block_indices: Mapping[str, Sequence[int]],
    *,
    seed: int,
    epoch: int,
    blocks_per_detector_batch: int,
    shuffle: bool,
) -> list[tuple[list[int], list[int]]]:
    """Return balanced block batches without relying on mutable RNG state."""

    ordered: dict[str, list[int]] = {}
    for detector_index, detector in enumerate(("H1", "L1")):
        values = sorted(int(value) for value in block_indices[detector])
        if len(values) % blocks_per_detector_batch:
            raise ContractError("v5 training block count does not fill balanced batches")
        if shuffle:
            seed_sequence = np.random.SeedSequence(
                [int(seed) & 0xFFFFFFFF, int(seed) >> 32, int(epoch), detector_index]
            )
            permutation = np.random.default_rng(seed_sequence).permutation(len(values))
            values = [values[int(position)] for position in permutation]
        ordered[detector] = values
    if len(ordered["H1"]) != len(ordered["L1"]):
        raise ContractError("v5 training detectors have unequal block counts")
    return [
        (
            ordered["H1"][start : start + blocks_per_detector_batch],
            ordered["L1"][start : start + blocks_per_detector_batch],
        )
        for start in range(0, len(ordered["H1"]), blocks_per_detector_batch)
    ]


@dataclass(frozen=True, slots=True)
class BlockBatch:
    strain: np.ndarray
    targets: np.ndarray
    detectors: np.ndarray
    window_ids: tuple[str, ...]


class TrainingCache:
    """Read verified training-only shards in detector-balanced block batches."""

    def __init__(
        self,
        *,
        root: Path,
        contract: Mapping[str, Any],
        cache_root: Path,
    ) -> None:
        self.root = root
        self.contract = contract
        summary_reference = contract["source_references"]["teacher_ledger_summary"]
        self.summary = json.loads(
            (root / summary_reference["path"]).read_text(encoding="utf-8")
        )
        self.run_dir = (
            cache_root / self.summary["cache_location"]["run_subdirectory"]
        ).resolve()
        target_reference = contract["compact_teacher_targets"]["reference"]
        rows = _load_jsonl(root / target_reference["path"])
        self.by_key: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in rows:
            key = (str(row["detector"]), int(row["block_index"]))
            self.by_key.setdefault(key, []).append(row)
        for block_rows in self.by_key.values():
            block_rows.sort(key=lambda row: (float(row["gps_start"]), row["window_id"]))
        self._verified_shards: set[Path] = set()
        self._standardization = contract["target_standardization"]

    def block_indices(self, subset: str) -> dict[str, list[int]]:
        return {
            detector: sorted(
                index
                for (current, index), rows in self.by_key.items()
                if current == detector and rows[0]["subset"] == subset
            )
            for detector in ("H1", "L1")
        }

    def _load_block(self, detector: str, block_index: int) -> tuple[np.ndarray, np.ndarray, tuple[str, ...]]:
        rows = self.by_key[(detector, block_index)]
        shard_paths = {row["strain_shard_path"] for row in rows}
        shard_hashes = {row["strain_shard_sha256"] for row in rows}
        if len(shard_paths) != 1 or len(shard_hashes) != 1:
            raise ContractError("v5 training block has inconsistent strain shard provenance")
        shard = (self.run_dir / next(iter(shard_paths))).resolve()
        if not shard.is_relative_to(self.run_dir):
            raise ContractError("v5 training strain shard escaped its run cache")
        if shard not in self._verified_shards:
            if sha256_path(shard) != next(iter(shard_hashes)):
                raise ContractError("v5 training strain shard hash mismatch")
            self._verified_shards.add(shard)
        with np.load(shard, allow_pickle=False) as values:
            strain = np.asarray(values["clean_strain"], dtype=np.float32)
            window_ids = tuple(str(value) for value in values["window_ids"].tolist())
        positions = {window_id: index for index, window_id in enumerate(window_ids)}
        expected_ids = tuple(row["window_id"] for row in rows)
        if set(positions) != set(expected_ids) or strain.shape[0] != len(expected_ids):
            raise ContractError("v5 training strain shard identity mismatch")
        ordered_strain = np.stack([strain[positions[window_id]] for window_id in expected_ids])
        targets = np.asarray(
            [_float32_from_hex(row["teacher_target_float32_hex"]) for row in rows],
            dtype=np.float32,
        )
        scale = self._standardization[detector]
        targets = (
            targets - np.float32(scale["mean_float64"])
        ) / np.float32(scale["standard_deviation_float64_ddof0"])
        if not np.isfinite(ordered_strain).all() or not np.isfinite(targets).all():
            raise NumericalTrainingFailure("non-finite training input or standardized target")
        return ordered_strain, targets, expected_ids

    def load_batch(self, h1_blocks: Sequence[int], l1_blocks: Sequence[int]) -> BlockBatch:
        strain_parts = []
        target_parts = []
        detector_parts = []
        window_ids = []
        for detector, indices in (("H1", h1_blocks), ("L1", l1_blocks)):
            for block_index in indices:
                strain, targets, identities = self._load_block(detector, int(block_index))
                strain_parts.append(strain)
                target_parts.append(targets)
                detector_parts.append(
                    np.full(targets.shape, 0 if detector == "H1" else 1, dtype=np.int8)
                )
                window_ids.extend(identities)
        return BlockBatch(
            strain=np.concatenate(strain_parts),
            targets=np.concatenate(target_parts),
            detectors=np.concatenate(detector_parts),
            window_ids=tuple(window_ids),
        )


def student_input(
    strain: np.ndarray,
    *,
    arm: str,
    stft_contract: Mapping[str, Any],
) -> torch.Tensor:
    if not np.isfinite(strain).all():
        raise NumericalTrainingFailure("non-finite student input strain")
    if arm == "raw_1d_depthwise":
        values = np.asarray(strain[:, None, :], dtype=np.float32)
    elif arm == "complex_stft_2d":
        frequencies, _times, transform = signal.stft(
            strain,
            fs=4096,
            window=str(stft_contract["window"]),
            nperseg=int(stft_contract["nperseg"]),
            noverlap=int(stft_contract["noverlap"]),
            nfft=int(stft_contract["nfft"]),
            boundary=stft_contract["boundary"],
            padded=bool(stft_contract["padded"]),
            axis=-1,
        )
        low, high = (float(value) for value in stft_contract["frequency_band_hz"])
        selected = (frequencies >= low) & (frequencies <= high)
        band = transform[:, selected, :]
        values = np.stack((band.real, band.imag), axis=1).astype(np.float32)
    else:
        raise ContractError(f"unknown v5 student arm: {arm}")
    if not np.isfinite(values).all():
        raise NumericalTrainingFailure("non-finite transformed student input")
    return torch.from_numpy(values)


def _model(arm: str) -> torch.nn.Module:
    if arm == "raw_1d_depthwise":
        return Raw1DDepthwiseStudentProxy()
    if arm == "complex_stft_2d":
        return ComplexSTFT2DStudentProxy()
    raise ContractError(f"unknown v5 student arm: {arm}")


def training_environment(device: torch.device) -> dict[str, Any]:
    return {
        "python": os.sys.version.split()[0],
        "numpy": np.__version__,
        "scipy": __import__("scipy").__version__,
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device_type": device.type,
        "device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu",
        "deterministic_algorithms": True,
        "automatic_mixed_precision": False,
    }


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
            "schema_version": SCHEMA_VERSION,
            "training_contract_digest": contract["training_contract_digest"],
            "code_references": dict(code_references),
            "environment": dict(environment),
            "smoke": bool(smoke),
            "smoke_batches": smoke_batches,
        }
    )


def _optimizer(model: torch.nn.Module, design: Mapping[str, Any]) -> torch.optim.AdamW:
    spec = design["optimization"]["optimizer"]
    return torch.optim.AdamW(
        model.parameters(),
        lr=float(spec["learning_rate"]),
        weight_decay=float(spec["weight_decay"]),
        betas=tuple(float(value) for value in spec["betas"]),
        eps=float(spec["epsilon"]),
        amsgrad=bool(spec["amsgrad"]),
    )


def _loss(design: Mapping[str, Any]) -> torch.nn.SmoothL1Loss:
    spec = design["optimization"]["loss"]
    return torch.nn.SmoothL1Loss(beta=float(spec["beta"]), reduction="mean")


def _validation_loss(
    *,
    model: torch.nn.Module,
    cache: TrainingCache,
    batches: Sequence[tuple[list[int], list[int]]],
    arm: str,
    stft_contract: Mapping[str, Any],
    loss_function: torch.nn.Module,
    device: torch.device,
    limit_batches: int | None,
) -> tuple[float, dict[str, float]]:
    model.eval()
    sums = {"H1": 0.0, "L1": 0.0}
    counts = {"H1": 0, "L1": 0}
    with torch.no_grad():
        for batch_index, (h1_blocks, l1_blocks) in enumerate(batches):
            if limit_batches is not None and batch_index >= limit_batches:
                break
            batch = cache.load_batch(h1_blocks, l1_blocks)
            inputs = student_input(batch.strain, arm=arm, stft_contract=stft_contract).to(
                device
            )
            targets = torch.from_numpy(batch.targets).to(device)
            predictions = model(inputs).squeeze(-1)
            _finite_tensor(predictions, "validation prediction")
            for detector, detector_value in (("H1", 0), ("L1", 1)):
                mask = torch.from_numpy(batch.detectors == detector_value).to(device)
                value = loss_function(predictions[mask], targets[mask])
                _finite_tensor(value, "validation loss")
                count = int(mask.sum().item())
                sums[detector] += float(value.item()) * count
                counts[detector] += count
    if any(count == 0 for count in counts.values()):
        raise ContractError("v5 validation did not observe both detectors")
    by_detector = {detector: sums[detector] / counts[detector] for detector in sums}
    return float(np.mean(list(by_detector.values()))), by_detector


def train_replicate(
    *,
    root: Path,
    contract: Mapping[str, Any],
    cache: TrainingCache,
    run_dir: Path,
    run_key: str,
    arm: str,
    replicate_index: int,
    seed: int,
    device: torch.device,
    maximum_epochs: int,
    limit_batches: int | None,
    smoke: bool,
) -> dict[str, Any]:
    replicate_dir = run_dir / arm / f"replicate_{replicate_index}"
    summary_path = replicate_dir / "replicate_summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("run_key") != run_key or summary.get("seed") != seed:
            raise ContractError("v5 training replicate cache identity collision")
        return summary
    deterministic_environment(seed)
    design = contract["design"]
    protocol = json.loads(
        (root / contract["source_references"]["protocol"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    stft_contract = protocol["approved_design"]["students"]["complex_stft_2d"]["stft"]
    model = _model(arm).to(device=device, dtype=torch.float32)
    optimizer = _optimizer(model, design)
    loss_function = _loss(design)
    fit_blocks = cache.block_indices("fit")
    validation_blocks = cache.block_indices("validation")
    blocks_per_detector_batch = int(design["optimization"]["batch"]["H1_size"]) // 8
    validation_batches = epoch_block_batches(
        validation_blocks,
        seed=seed,
        epoch=0,
        blocks_per_detector_batch=blocks_per_detector_batch,
        shuffle=False,
    )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "run_key": run_key,
        "arm": arm,
        "replicate_index": replicate_index,
        "seed": seed,
        "maximum_epochs": maximum_epochs,
        "limit_batches": limit_batches,
        "smoke": smoke,
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
    replicate_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(replicate_dir / "run_identity.json", identity)
    latest_path = replicate_dir / "latest_state.pt"
    metrics: list[dict[str, Any]] = []
    best_loss = math.inf
    best_epoch = 0
    start_epoch = 1
    if latest_path.is_file():
        state = torch.load(latest_path, map_location=device, weights_only=True)
        if state["run_key"] != run_key or state["seed"] != seed:
            raise ContractError("v5 training checkpoint identity collision")
        model.load_state_dict(state["model_state"])
        optimizer.load_state_dict(state["optimizer_state"])
        metrics = state["metrics"]
        best_loss = float(state["best_validation_loss"])
        best_epoch = int(state["best_epoch"])
        start_epoch = int(state["epoch"]) + 1
    started = time.perf_counter()
    try:
        for epoch in range(start_epoch, maximum_epochs + 1):
            model.train()
            batches = epoch_block_batches(
                fit_blocks,
                seed=seed,
                epoch=epoch,
                blocks_per_detector_batch=blocks_per_detector_batch,
                shuffle=True,
            )
            loss_sum = 0.0
            observed = 0
            epoch_started = time.perf_counter()
            for batch_index, (h1_blocks, l1_blocks) in enumerate(batches):
                if limit_batches is not None and batch_index >= limit_batches:
                    break
                batch = cache.load_batch(h1_blocks, l1_blocks)
                inputs = student_input(
                    batch.strain, arm=arm, stft_contract=stft_contract
                ).to(device)
                targets = torch.from_numpy(batch.targets).to(device)
                _finite_tensor(inputs, "training input")
                _finite_tensor(targets, "training target")
                optimizer.zero_grad(set_to_none=True)
                predictions = model(inputs).squeeze(-1)
                _finite_tensor(predictions, "training prediction")
                loss = loss_function(predictions, targets)
                _finite_tensor(loss, "training loss")
                loss.backward()
                for parameter in model.parameters():
                    if parameter.grad is not None:
                        _finite_tensor(parameter.grad, "gradient")
                optimizer.step()
                for parameter in model.parameters():
                    _finite_tensor(parameter, "model parameter")
                _finite_optimizer(optimizer)
                count = int(targets.numel())
                loss_sum += float(loss.item()) * count
                observed += count
            if observed == 0:
                raise ContractError("v5 training epoch observed no fit windows")
            validation_loss, validation_by_detector = _validation_loss(
                model=model,
                cache=cache,
                batches=validation_batches,
                arm=arm,
                stft_contract=stft_contract,
                loss_function=loss_function,
                device=device,
                limit_batches=limit_batches,
            )
            metric = {
                "epoch": epoch,
                "fit_smooth_l1": loss_sum / observed,
                "validation_smooth_l1_equal_detector_mean": validation_loss,
                "validation_smooth_l1_by_detector": validation_by_detector,
                "learning_rate": float(optimizer.param_groups[0]["lr"]),
                "fit_window_count": observed,
                "elapsed_s": time.perf_counter() - epoch_started,
            }
            metrics.append(metric)
            if validation_loss < best_loss:
                best_loss = validation_loss
                best_epoch = epoch
                _atomic_torch(
                    replicate_dir / "best_model.pt",
                    {
                        "schema_version": SCHEMA_VERSION,
                        "run_key": run_key,
                        "arm": arm,
                        "replicate_index": replicate_index,
                        "seed": seed,
                        "epoch": epoch,
                        "validation_loss": validation_loss,
                        "model_state": model.state_dict(),
                    },
                )
            _atomic_torch(
                latest_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "run_key": run_key,
                    "seed": seed,
                    "epoch": epoch,
                    "best_epoch": best_epoch,
                    "best_validation_loss": best_loss,
                    "model_state": model.state_dict(),
                    "optimizer_state": optimizer.state_dict(),
                    "metrics": metrics,
                },
            )
            _atomic_json(replicate_dir / "metrics.json", {"epochs": metrics})
    except NumericalTrainingFailure as exc:
        failure_body = {
            **identity,
            "status": "FAILED_NUMERICAL",
            "reason": str(exc),
            "completed_epochs": len(metrics),
            "candidate_promotion_allowed": False,
        }
        summary = {
            **failure_body,
            "replicate_digest": canonical_json_sha256(failure_body),
        }
        _atomic_json(summary_path, summary)
        return summary
    best_path = replicate_dir / "best_model.pt"
    body = {
        **identity,
        "status": "SMOKE_COMPLETE_NON_PROMOTABLE" if smoke else "TRAINING_COMPLETE",
        "completed_epochs": len(metrics),
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
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


def run_training(
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    cache_root: Path | None = None,
    code_references: Mapping[str, Mapping[str, str]],
    device_name: str | None = None,
    arms: Sequence[str] = ARMS,
    replicate_indices: Sequence[int] | None = None,
    smoke: bool = False,
    smoke_batches: int | None = None,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    contract = load_training_freeze(contract_path, root=root)
    if any(arm not in ARMS for arm in arms) or len(set(arms)) != len(arms):
        raise ContractError("v5 training requested an invalid or duplicated arm")
    all_seeds = list(contract["training_replicate_seeds"])
    selected_indices = (
        list(range(len(all_seeds)))
        if replicate_indices is None
        else [int(value) for value in replicate_indices]
    )
    if any(index < 0 or index >= len(all_seeds) for index in selected_indices):
        raise ContractError("v5 training replicate index is out of range")
    design = contract["design"]
    maximum_epochs = 1 if smoke else int(design["optimization"]["maximum_epochs"])
    if smoke and (smoke_batches is None or smoke_batches <= 0):
        raise ContractError("v5 smoke training requires a positive batch limit")
    if not smoke and smoke_batches is not None:
        raise ContractError("v5 full training cannot limit its batches")
    device = torch.device(
        device_name or ("cuda" if torch.cuda.is_available() else "cpu")
    )
    environment = training_environment(device)
    run_key = training_run_key(
        contract,
        code_references=code_references,
        environment=environment,
        smoke=smoke,
        smoke_batches=smoke_batches,
    )
    selected_cache_root = (cache_root or default_cache_root()).resolve()
    run_dir = selected_cache_root / f"student_{run_key}"
    run_identity = {
        "schema_version": SCHEMA_VERSION,
        "run_key": run_key,
        "training_contract_digest": contract["training_contract_digest"],
        "code_references": dict(code_references),
        "environment": environment,
        "smoke": smoke,
        "smoke_batches": smoke_batches,
        "development_rows_accessed": [],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file():
        if json.loads(identity_path.read_text(encoding="utf-8")) != run_identity:
            raise ContractError("v5 training run identity collision")
    else:
        _atomic_json(identity_path, run_identity)
    cache = TrainingCache(
        root=root,
        contract=contract,
        cache_root=selected_cache_root,
    )
    summaries = []
    for arm in arms:
        for replicate_index in selected_indices:
            summaries.append(
                train_replicate(
                    root=root,
                    contract=contract,
                    cache=cache,
                    run_dir=run_dir,
                    run_key=run_key,
                    arm=arm,
                    replicate_index=replicate_index,
                    seed=int(all_seeds[replicate_index]),
                    device=device,
                    maximum_epochs=maximum_epochs,
                    limit_batches=smoke_batches,
                    smoke=smoke,
                )
            )
    full_request = set(arms) == set(ARMS) and selected_indices == list(range(len(all_seeds)))
    any_failed = any(row["status"] == "FAILED_NUMERICAL" for row in summaries)
    body = {
        **run_identity,
        "status": (
            "FAILED_NUMERICAL"
            if any_failed
            else "SMOKE_COMPLETE_NON_PROMOTABLE"
            if smoke
            else "TRAINING_COMPLETE_PENDING_DEVELOPMENT"
        ),
        "full_request": full_request,
        "arms": list(arms),
        "replicate_indices": selected_indices,
        "replicate_summaries": summaries,
        "candidate_promotion_allowed": False,
        "student_outputs_are_training_only": True,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "student_training_summary_v5.json", summary)
    if not smoke and full_request:
        _atomic_json(output_path, summary)
    return summary
