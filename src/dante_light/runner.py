"""Exact replay/shadow runner for the opt-in DANTE-Light schema."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import numpy as np

from src.core.index_contract import sha256_file
from src.core.patch_scorer import PatchScorer
from src.dante_light.contracts import (
    CalibrationEpochContract,
    ContractError,
    FailClosedReason,
    LightDisposition,
    LightRecord,
    RepresentationContract,
    WindowIdentity,
)
from src.dante_light.executor import (
    BoundedPipelineExecutor,
    DeferredWindow,
    WindowTask,
)
from src.dante_light.epoch import verified_epoch_from_promotion
from src.dante_light.preprocessing import (
    PreparedWindow,
    prepare_canonical_window,
    stage_canonical_strain,
)
from src.dante_light.review_queue import ReviewQueue
from src.dante_light.sources.files import ReplayManifestSource


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPLAY = ROOT / "config/dante_light_replay_v1.json"
DEFAULT_EPOCHS = ROOT / "config/dante_light_epochs_v1.json"
PRIMARY_INDEX = ROOT / "data/reference/patch_compressed_index_o3b.npz"
NATIVE_INDEX = ROOT / "data/reference/patch_compressed_index_o4a_q4-64_ex.npz"


def runtime_provenance() -> dict[str, Any]:
    def git(*arguments: str) -> str | None:
        try:
            return subprocess.check_output(
                ["git", *arguments],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    status = git("status", "--porcelain", "--untracked-files=no")
    source_paths = (
        ROOT / "main.py",
        Path(__file__).resolve(),
        ROOT / "src/dante_light/contracts.py",
        ROOT / "src/dante_light/epoch.py",
        ROOT / "src/dante_light/executor.py",
        ROOT / "src/dante_light/evidence.py",
        ROOT / "src/dante_light/preprocessing.py",
        ROOT / "src/dante_light/review_queue.py",
        ROOT / "src/dante_light/sources/files.py",
        ROOT / "src/core/data_loader.py",
        ROOT / "src/core/preprocessor.py",
        ROOT / "src/core/patch_scorer.py",
    )
    def normalized_source_sha256(path: Path) -> str:
        content = (
            path.read_text(encoding="utf-8")
            .replace("\r\n", "\n")
            .replace("\r", "\n")
            .encode("utf-8")
        )
        return hashlib.sha256(content).hexdigest()

    packages = {}
    for distribution in ("numpy", "torch", "gwpy", "astropy", "matplotlib"):
        try:
            packages[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            packages[distribution] = None
    accelerator: dict[str, Any] = {"cuda_available": False}
    try:
        import torch

        accelerator["cuda_available"] = bool(torch.cuda.is_available())
        accelerator["torch_cuda_version"] = torch.version.cuda
        if torch.cuda.is_available():
            accelerator["cuda_device_name"] = torch.cuda.get_device_name(0)
            accelerator["cuda_device_capability"] = list(
                torch.cuda.get_device_capability(0)
            )
    except (ImportError, RuntimeError):
        pass
    return {
        "code_state": {
            "commit": git("rev-parse", "HEAD"),
            "branch": git("branch", "--show-current"),
            "tracked_dirty": None if status is None else bool(status),
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "packages": packages,
            "accelerator": accelerator,
        },
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): normalized_source_sha256(path)
            for path in source_paths
        },
        "source_hash_semantics": "utf8_lf_v1",
    }


def load_epochs(
    path: str | Path = DEFAULT_EPOCHS,
    *,
    representation: RepresentationContract | None = None,
    root: str | Path = ROOT,
) -> tuple[dict[str, Any], dict[str, CalibrationEpochContract]]:
    path = Path(path)
    root = Path(root)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ContractError("Unsupported DANTE-Light epoch-file schema")
    source = payload["source_threshold_artifact"]
    source_path = root / source["path"]
    if source_path.is_file() and sha256_file(source_path) != source["sha256"]:
        raise ContractError("DANTE-Light threshold artifact SHA256 mismatch")
    epochs: dict[str, CalibrationEpochContract] = {}
    for detector, raw in payload["epochs"].items():
        epoch_fields = {
            key: value
            for key, value in raw.items()
            if key not in {"calibration_ledger_sha256", "promotion_evidence"}
        }
        if raw.get("causal") is True:
            if representation is None:
                raise ContractError(
                    "causal DANTE-Light epochs require a representation contract"
                )
            if "promotion_evidence" not in raw:
                raise ContractError(
                    f"causal DANTE-Light epoch {detector} lacks promotion evidence"
                )
            if not source_path.is_file():
                raise ContractError(
                    "causal DANTE-Light epoch requires the source threshold artifact"
                )
            if raw.get("threshold_artifact_sha256") != source["sha256"]:
                raise ContractError(
                    f"causal DANTE-Light epoch {detector} threshold provenance mismatch"
                )
            evidence_hashes = {
                item.get("sha256")
                for item in raw["promotion_evidence"].get("artifacts", [])
            }
            if raw.get("calibration_ledger_sha256") not in evidence_hashes:
                raise ContractError(
                    f"causal DANTE-Light epoch {detector} calibration ledger "
                    "is not verified evidence"
                )
            epoch = verified_epoch_from_promotion(
                {
                    "epoch": epoch_fields,
                    "promotion_evidence": raw["promotion_evidence"],
                },
                representation=representation,
                root=root,
            )
        else:
            epoch = CalibrationEpochContract(**epoch_fields)
        if epoch.detector != detector:
            raise ContractError(
                f"DANTE-Light epoch key/detector mismatch: {detector}/{epoch.detector}"
            )
        epochs[epoch.detector] = epoch
    return payload, epochs


def load_replay_tasks(
    path: str | Path = DEFAULT_REPLAY,
    *,
    roles: set[str] | None = None,
    limit: int | None = None,
    limit_per_detector: int | None = None,
) -> tuple[dict[str, Any], list[WindowTask]]:
    source = ReplayManifestSource(path, root=ROOT)
    return source.header, source.tasks(
        roles=roles,
        limit=limit,
        limit_per_detector=limit_per_detector,
    )


class DanteLightRunner:
    def __init__(
        self,
        *,
        representation: RepresentationContract,
        epochs: dict[str, CalibrationEpochContract],
        primary: PatchScorer,
        native: PatchScorer,
        review_queue: ReviewQueue,
        cat1_active: Callable[[WindowIdentity], bool | None],
        prepare: Callable[[WindowTask], PreparedWindow],
        stage_data: Callable[[WindowTask], dict[str, Any]] | None = None,
        prospective: bool,
        engine: str = "canonical",
        workers: int = 2,
        batch_size: int = 8,
        max_preprocess_in_flight: int = 16,
        max_pending_writes: int = 2,
    ) -> None:
        if primary.reference_sha256 != representation.primary_index_sha256:
            raise ContractError("Primary scorer violates representation contract")
        if native.reference_sha256 != representation.native_index_sha256:
            raise ContractError("Native scorer violates representation contract")
        self.representation = representation
        self.epochs = epochs
        self.primary = primary
        self.native = native
        self.queue = review_queue
        self.cat1_active = cat1_active
        self.prepare_window = prepare
        self.stage_data = stage_data
        self.staged_strain_sha256: dict[str, str] = {}
        self.prospective = prospective
        if engine not in {"canonical", "shared_encoder_score_only"}:
            raise ValueError(f"Unsupported DANTE-Light engine: {engine}")
        self.engine = engine
        self.evidence: dict[str, dict[str, Any]] = {}
        self.executor = BoundedPipelineExecutor(
            preprocess=self._preprocess,
            score_batch=self._score_batch,
            write_batch=self._write_batch,
            defer_record=self._defer,
            workers=workers,
            batch_size=batch_size,
            max_preprocess_in_flight=max_preprocess_in_flight,
            max_pending_writes=max_pending_writes,
        )

    def _epoch(self, window: WindowIdentity) -> CalibrationEpochContract:
        epoch = self.epochs.get(window.detector)
        if epoch is None:
            raise DeferredWindow(FailClosedReason.MISSING_CALIBRATION)
        reason = epoch.incompatibility(
            window, self.representation, prospective=self.prospective
        )
        if reason is not None:
            raise DeferredWindow(reason)
        return epoch

    def _preprocess(self, task: WindowTask) -> PreparedWindow:
        self._epoch(task.window)
        cat1 = self.cat1_active(task.window)
        if cat1 is None:
            raise DeferredWindow(FailClosedReason.DEPENDENCY_UNAVAILABLE)
        if not cat1:
            raise DeferredWindow(FailClosedReason.MISSING_CAT1)
        prepared = self.prepare_window(task)
        staged_sha256 = self.staged_strain_sha256.get(task.window.window_id)
        if staged_sha256 is not None and prepared.strain_sha256 != staged_sha256:
            raise DeferredWindow(FailClosedReason.INTERNAL_ERROR)
        return prepared

    def _stage_before_submission(self, tasks: list[WindowTask]) -> dict[str, Any]:
        """Stage immutable inputs without exposing DANTE outcomes."""
        if self.stage_data is None or not tasks:
            return {
                "mode": "none",
                "windows": 0,
                "failures": [],
                "elapsed_s": 0.0,
                "duration_s": [],
            }
        began = time.perf_counter()
        results: dict[str, dict[str, Any]] = {}
        failures: list[dict[str, str]] = []
        with ThreadPoolExecutor(
            max_workers=self.executor.workers,
            thread_name_prefix="dante-light-acquisition",
        ) as pool:
            futures = {pool.submit(self.stage_data, task): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = dict(future.result())
                    if result.get("window_id") != task.window.window_id:
                        raise ContractError("staging reordered the window identity")
                    results[task.window.window_id] = result
                    self.staged_strain_sha256[task.window.window_id] = str(
                        result["strain_sha256"]
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "window_id": task.window.window_id,
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
        ordered = [results[key] for key in sorted(results)]
        return {
            "mode": "prestage_before_task_submission",
            "windows": len(ordered),
            "failures": sorted(failures, key=lambda item: item["window_id"]),
            "elapsed_s": time.perf_counter() - began,
            "duration_s": [float(item["duration_s"]) for item in ordered],
        }

    def _defer(
        self, window: WindowIdentity, reason: FailClosedReason
    ) -> LightRecord:
        epoch = self.epochs.get(window.detector)
        return LightRecord.deferred(
            window,
            self.representation,
            reason,
            epoch_id=None if epoch is None else epoch.epoch_id,
        )

    def _score_batch(
        self, batch: list[tuple[WindowTask, PreparedWindow]]
    ) -> list[LightRecord]:
        images = [prepared.image for _, prepared in batch]
        if self.engine == "canonical":
            scored = {
                "primary": self.primary.score_spectrogram(images, threshold=1.0),
                "native": self.native.score_spectrogram(images, threshold=1.0),
            }
        else:
            scored = self.primary.score_multi_index(
                images,
                {"primary": (self.primary, 1.0), "native": (self.native, 1.0)},
                output_modes={"native": "score_only"},
            )
        records = []
        for index, (task, prepared) in enumerate(batch):
            epoch = self._epoch(task.window)
            primary = scored["primary"][index]
            native = scored["native"][index]
            native_score = float(native["novelty_score"])
            disposition = (
                LightDisposition.ESCALATE
                if native_score > epoch.threshold
                else LightDisposition.NOT_ESCALATED
            )
            record = LightRecord(
                window=task.window,
                representation_sha256=self.representation.contract_sha256,
                disposition=disposition,
                epoch_id=epoch.epoch_id,
                scores=(
                    ("native", native_score),
                    ("primary", float(primary["novelty_score"])),
                ),
            )
            top_k = np.asarray(primary["top_k_indices"], dtype=np.int32)
            mil = np.asarray(primary["mil_vector"], dtype=np.float32)
            self.evidence[task.window.window_id] = {
                "case_ids": task.payload.get("case_ids", []),
                "roles": task.payload.get("roles", []),
                "expected": task.payload.get("expected", []),
                "strain_sha256": prepared.strain_sha256,
                "image_sha256": prepared.image_sha256,
                "primary_top_k_indices": top_k.tolist(),
                "primary_top_k_sha256": hashlib.sha256(top_k.tobytes()).hexdigest(),
                "primary_mil_vector_sha256": hashlib.sha256(mil.tobytes()).hexdigest(),
                "decision_score": "native",
                "decision_threshold": epoch.threshold,
                "timings": prepared.timings,
            }
            records.append(record)
        return records

    def _write_batch(self, records: list[LightRecord]) -> None:
        payloads = []
        for record in records:
            payload = record.to_dict()
            evidence = self.evidence.get(record.window.window_id)
            if evidence is not None:
                payload["evidence"] = evidence
            payloads.append(payload)
        self.queue.append(payloads)

    def run(self, tasks: list[WindowTask]):
        remaining = [
            task
            for task in tasks
            if task.window.window_id not in self.queue.completed_window_ids
        ]
        acquisition = self._stage_before_submission(remaining)
        summary = self.executor.run(remaining)
        disposition_counts: dict[str, int] = {}
        if self.queue.records_path.exists():
            for line in self.queue.records_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    disposition = json.loads(line)["disposition"]
                    disposition_counts[disposition] = (
                        disposition_counts.get(disposition, 0) + 1
                    )
        executor_payload = asdict(summary)
        executor_payload["drops"] = summary.drops
        output = {
            "schema_version": 1,
            "status": (
                "failed"
                if summary.drops
                else "complete_with_defer"
                if summary.deferred
                else "complete"
            ),
            "executor": executor_payload,
            "acquisition": acquisition,
            "records_total": len(self.queue.completed_window_ids),
            "dispositions": disposition_counts,
        }
        self.queue.write_summary(output)
        return output


def gwosc_cat1_provider(tasks: list[WindowTask]) -> Callable[[WindowIdentity], bool | None]:
    from gwosc.timeline import get_segments

    cache: dict[str, list[tuple[float, float]] | None] = {}
    for detector in sorted({task.window.detector for task in tasks}):
        selected = [task.window for task in tasks if task.window.detector == detector]
        start = int(min(window.gps_start for window in selected))
        end = int(max(window.gps_start + window.duration_s for window in selected)) + 1
        try:
            cache[detector] = [
                (float(left), float(right))
                for left, right in get_segments(f"{detector}_CBC_CAT1", start, end)
            ]
        except Exception:
            cache[detector] = None

    def active(window: WindowIdentity) -> bool | None:
        segments = cache.get(window.detector)
        if segments is None:
            return None
        return any(
            left <= window.gps_start
            and right >= window.gps_start + window.duration_s
            for left, right in segments
        )

    return active


def run_replay(args) -> dict[str, Any]:
    representation = RepresentationContract.from_reference_manifest(
        ROOT / "config/reference_artifacts.json"
    )
    epoch_payload, epochs = load_epochs(
        args.epochs, representation=representation, root=ROOT
    )
    replay_header, tasks = load_replay_tasks(
        args.manifest,
        roles=set(args.role),
        limit=args.limit,
        limit_per_detector=args.limit_per_detector,
    )
    strain_source = getattr(args, "strain_source", "auto")
    latency_objective = getattr(args, "latency_objective_s", None)
    if latency_objective is not None:
        latency_objective = float(latency_objective)
        if not math.isfinite(latency_objective) or latency_objective <= 0:
            raise ContractError("--latency-objective-s must be finite and positive")
    if args.local_only:
        if strain_source != "auto":
            raise ContractError(
                "--local-only cannot be combined with an explicit --strain-source"
            )
        strain_source = "local-only"
    local_only = strain_source == "local-only"
    remote_only = strain_source == "gwosc-only"
    if args.cat1_mode == "frozen-replay-attestation":
        cat1_active = lambda _window: True
        cat1_provenance = (
            "frozen corpus source attestation; not valid for prospective operation"
        )
    else:
        cat1_active = gwosc_cat1_provider(tasks)
        cat1_provenance = "GWOSC CBC_CAT1 whole-window containment"

    primary = PatchScorer(
        PRIMARY_INDEX,
        device=args.device,
        k=representation.top_k,
    )
    native = PatchScorer(
        NATIVE_INDEX,
        device=args.device,
        k=representation.top_k,
        model=(primary.model if args.engine == "shared_encoder_score_only" else None),
    )
    run_manifest = {
        "schema_version": 1,
        "mode": "shadow" if args.prospective else "historical_replay",
        "scientific_engine": args.engine,
        "prefilter": "none",
        "prospective": bool(args.prospective),
        "representation": representation.to_dict(),
        "epochs": epoch_payload,
        "replay_manifest_sha256": replay_header["manifest_sha256"],
        "replay_entries_file_sha256": replay_header["entries_file_sha256"],
        "roles": sorted(set(args.role)),
        "limit": args.limit,
        "limit_per_detector": args.limit_per_detector,
        "cat1_provenance": cat1_provenance,
        "local_only": local_only,
        "strain_source": strain_source,
        "data_availability_mode": (
            "prestage_before_task_submission" if args.prospective else "inline"
        ),
        "pre_registered_latency_objective_s": latency_objective,
        "executor_config": {
            "requested_device": args.device,
            "workers": args.workers,
            "batch_size": args.batch_size,
            "max_preprocess_in_flight": args.max_in_flight,
            "max_pending_writes": args.max_pending_writes,
        },
        "runtime_provenance": runtime_provenance(),
    }
    queue = ReviewQueue(args.output_dir, run_manifest)
    runner = DanteLightRunner(
        representation=representation,
        epochs=epochs,
        primary=primary,
        native=native,
        review_queue=queue,
        cat1_active=cat1_active,
        prepare=lambda task: prepare_canonical_window(
            task.window, local_only=local_only, remote_only=remote_only
        ),
        stage_data=(
            (
                lambda task: stage_canonical_strain(
                    task.window, local_only=local_only, remote_only=remote_only
                )
            )
            if args.prospective
            else None
        ),
        prospective=args.prospective,
        engine=args.engine,
        workers=args.workers,
        batch_size=args.batch_size,
        max_preprocess_in_flight=args.max_in_flight,
        max_pending_writes=args.max_pending_writes,
    )
    return runner.run(tasks)
