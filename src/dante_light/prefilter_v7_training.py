"""Authorized training-only execution for the frozen DANTE-Light v7 candidate.

This module deliberately stops at the five fitted ensemble members.  It has no
API for threshold-search, risk-calibration, confirmation, O4b, or routing.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import random
import time
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np
import torch

from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.prefilter_v5_teacher import (
    ExactNativeTeacher,
    PreparedTeacherInput,
    TARGET_NAME,
    TARGET_SCORE_KEY,
    prepare_teacher_input,
)
from src.dante_light.prefilter_v6_cache import ensure_interval
from src.dante_light.prefilter_v7_training_freeze import (
    ROOT,
    file_sha256,
    load_training_freeze,
    repository_reference,
)


SCHEMA_VERSION = 1
DEFAULT_AUTHORIZATION = ROOT / "config/dante_light_prefilter_v7_training_authorization.json"
DEFAULT_CACHE = Path("E:/dante_cache/dante_light/prefilter_l4_v7_training")
DEFAULT_LEDGER_SUMMARY = (
    ROOT / "artifacts/dante_light/prefilter_l4_v7_training/teacher_ledger_summary_v7.json"
)
DEFAULT_TARGETS = (
    ROOT / "artifacts/dante_light/prefilter_l4_v7_training/teacher_targets_compact_v7.jsonl"
)
DEFAULT_TRAINING_SUMMARY = (
    ROOT / "artifacts/dante_light/prefilter_l4_v7_training/student_training_summary_v7.json"
)
DETECTORS = ("H1", "L1")
ROLES = ("background", "teacher_positive")
SUBSETS = ("fit", "internal_validation")


class NumericalTrainingFailure(RuntimeError):
    """Fail-closed numerical failure for one frozen ensemble member."""


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _atomic_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        "".join(
            json.dumps(dict(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("wb") as stream:
        np.savez(stream, **arrays)
    os.replace(temporary, path)


def _atomic_torch(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    torch.save(dict(payload), temporary)
    os.replace(temporary, path)


def _resolve_reference(root: Path, reference: Mapping[str, Any], label: str) -> Path:
    if set(reference) != {"path", "sha256"}:
        raise ContractError(f"v7 training authorization reference is malformed: {label}")
    relative = Path(str(reference["path"]))
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(reference["path"]):
        raise ContractError(f"v7 training authorization reference is not portable: {label}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ContractError(f"v7 training authorization reference is absent: {label}")
    if file_sha256(path) != str(reference["sha256"]):
        raise ContractError(f"v7 training authorization reference hash mismatch: {label}")
    return path


def build_training_authorization(
    *, root: Path = ROOT, source_references: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    """Create the auditable receipt for the user's one-partition authorization."""

    contract = load_training_freeze(root=root)
    for name, reference in source_references.items():
        _resolve_reference(root, reference, name)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "AUTHORIZED_TRAINING_ONLY",
        "authorization_id": "dante-light-l4-prefilter-v7-training-only-2026-08-26",
        "authorization_source": {
            "actor": "Luca Cirfeta",
            "date": "2026-08-26",
            "instruction": "procedi",
            "interpreted_scope": "open only v7 training; stop before threshold_search",
        },
        "training_contract_digest": contract["training_contract_digest"],
        "identity_assignment_digest": contract["internal_split"]["assignment_digest"],
        "allowed": {
            "partition": "training",
            "teacher_scoring": True,
            "student_fit": True,
            "ensemble_members": 5,
        },
        "forbidden": {
            "threshold_search": [],
            "risk_calibration": [],
            "confirmation": [],
            "o4b": [],
            "routing": False,
            "member_selection": False,
            "second_stage_distillation": False,
        },
        "source_references": dict(source_references),
    }
    return {**body, "authorization_digest": canonical_json_sha256(body)}


def load_training_authorization(
    path: Path = DEFAULT_AUTHORIZATION, *, root: Path = ROOT
) -> dict[str, Any]:
    payload = _read_json(path)
    body = dict(payload)
    declared = body.pop("authorization_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v7 training authorization digest mismatch")
    if payload.get("status") != "AUTHORIZED_TRAINING_ONLY":
        raise ContractError("v7 training is not explicitly authorized")
    contract = load_training_freeze(root=root)
    if payload.get("training_contract_digest") != contract["training_contract_digest"]:
        raise ContractError("v7 training authorization binds a different contract")
    if payload.get("identity_assignment_digest") != contract["internal_split"]["assignment_digest"]:
        raise ContractError("v7 training authorization binds a different split")
    allowed = payload.get("allowed", {})
    if allowed != {
        "partition": "training",
        "teacher_scoring": True,
        "student_fit": True,
        "ensemble_members": 5,
    }:
        raise ContractError("v7 training authorization scope changed")
    forbidden = payload.get("forbidden", {})
    if forbidden != {
        "threshold_search": [],
        "risk_calibration": [],
        "confirmation": [],
        "o4b": [],
        "routing": False,
        "member_selection": False,
        "second_stage_distillation": False,
    }:
        raise ContractError("v7 protected-partition boundary widened")
    for name, reference in payload.get("source_references", {}).items():
        _resolve_reference(root, reference, name)
    return payload


def training_rows(*, root: Path = ROOT) -> list[dict[str, Any]]:
    """Join the frozen identity manifest to the training-only internal split."""

    contract = load_training_freeze(root=root)
    identities = {
        row["identity_id"]: row
        for row in _read_jsonl(root / "config/dante_light_prefilter_v7_identities.jsonl")
    }
    assignments = _read_jsonl(root / contract["internal_split"]["assignment_reference"]["path"])
    rows = []
    for assignment in assignments:
        identity = identities.get(assignment["identity_id"])
        if identity is None or identity.get("partition") != "training":
            raise ContractError("v7 training split references a non-training identity")
        if (
            identity["window"]["window_id"] != assignment["window_id"]
            or identity["block_key"] != assignment["block_key"]
            or identity["detector"] != assignment["detector"]
            or identity["role"] != assignment["sampling_role"]
        ):
            raise ContractError("v7 training split/identity join mismatch")
        rows.append({**identity, "subset": assignment["subset"], "sampling_role": assignment["sampling_role"]})
    rows.sort(key=lambda row: (row["detector"], row["sampling_role"], row["identity_id"]))
    if (
        len(rows) != 600
        or len({row["identity_id"] for row in rows}) != 600
        or len({row["block_key"] for row in rows}) != 600
    ):
        raise ContractError("v7 training rows are incomplete, duplicated, or block-overlapping")
    return rows


def strict_defer_label(score: float, threshold: float) -> int:
    if not math.isfinite(score) or not math.isfinite(threshold):
        raise ContractError("v7 label inputs must be finite")
    return int(score > threshold)


def _thresholds(root: Path) -> dict[str, float]:
    epochs = _read_json(root / "config/dante_light_epochs_v1.json")["epochs"]
    result = {detector: float(epochs[detector]["threshold"]) for detector in DETECTORS}
    if not all(math.isfinite(value) for value in result.values()):
        raise ContractError("v7 historical exact-DANTE thresholds are invalid")
    return result


def teacher_run_key(
    authorization: Mapping[str, Any], code_references: Mapping[str, Mapping[str, str]]
) -> str:
    return canonical_json_sha256(
        {
            "authorization_digest": authorization["authorization_digest"],
            "code_references": dict(code_references),
            "teacher_target": TARGET_NAME,
            "cache_schema": SCHEMA_VERSION,
        }
    )


def _cache_raw_windows(
    rows: Sequence[Mapping[str, Any]], *, raw_dir: Path, workers: int, retries: int
) -> list[dict[str, Any]]:
    from src.core import data_loader

    def fetch(detector: str, start: float, end: float, sample_rate_hz: int) -> object:
        return data_loader.fetch_strain_data(
            detector,
            start,
            end,
            sample_rate=sample_rate_hz,
            local_only=False,
            remote_only=False,
        )

    def one(row: Mapping[str, Any]) -> dict[str, Any]:
        window = row["window"]
        identity = {
            "detector": row["detector"],
            "block_index": int(row["stratum"].get("block_index", int(window["gps_start"]) // 4096)),
            "gps_start": float(window["gps_start"]) - 4.0,
            "gps_end": float(window["gps_start"]) + float(window["duration_s"]) + 4.0,
        }
        record = ensure_interval(
            identity=identity,
            cache_root=raw_dir,
            sample_rate_hz=4096,
            fetch=fetch,
            retries=retries,
        )
        return {**record, "identity_id": row["identity_id"]}

    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(one, row): row for row in rows}
        for future in as_completed(futures):
            row = futures[future]
            try:
                records.append(future.result())
            except Exception as exc:
                failures.append(
                    {
                        "identity_id": str(row["identity_id"]),
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
    if failures:
        raise ContractError(f"v7 training raw cache incomplete: {len(failures)} failures")
    records.sort(key=lambda row: row["identity_id"])
    return records


def _validate_teacher_batch(
    path: Path, *, run_key: str, expected_ids: Sequence[str]
) -> dict[str, Any]:
    payload = _read_json(path)
    body = dict(payload)
    declared = body.pop("batch_digest", None)
    if declared != canonical_json_sha256(body) or payload.get("status") != "COMPLETE":
        raise ContractError(f"v7 cached teacher batch is invalid: {path.name}")
    if payload.get("run_key") != run_key:
        raise ContractError(f"v7 cached teacher batch run key changed: {path.name}")
    if [row["identity_id"] for row in payload["rows"]] != list(expected_ids):
        raise ContractError(f"v7 cached teacher batch identities changed: {path.name}")
    shard = path.parent / payload["strain_shard"]["path"]
    if not shard.is_file() or file_sha256(shard) != payload["strain_shard"]["sha256"]:
        raise ContractError(f"v7 cached teacher strain changed: {path.name}")
    return payload


def build_teacher_ledger(
    *,
    root: Path = ROOT,
    cache_root: Path = DEFAULT_CACHE,
    authorization_path: Path = DEFAULT_AUTHORIZATION,
    code_references: Mapping[str, Mapping[str, str]],
    workers: int = 4,
    retries: int = 3,
    device: str | None = None,
    prepare: Callable[[WindowIdentity], PreparedTeacherInput] | None = None,
    score: Callable[[Sequence[np.ndarray]], tuple[list[float], dict[str, float]]] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Create a resumable exact-teacher ledger and canonical strain cache."""

    if workers < 1 or workers > 8 or retries < 1 or retries > 5:
        raise ContractError("v7 teacher worker/retry setting is outside the execution bound")
    authorization = load_training_authorization(authorization_path, root=root)
    for name, reference in code_references.items():
        _resolve_reference(root, reference, name)
    rows = training_rows(root=root)
    if limit is not None:
        if limit < 1:
            raise ContractError("v7 teacher smoke limit must be positive")
        rows = rows[:limit]
    run_key = teacher_run_key(authorization, code_references)
    run_dir = cache_root.resolve() / f"teacher_{run_key}"
    batch_dir = run_dir / "batches"
    raw_dir = run_dir / "raw"
    batch_dir.mkdir(parents=True, exist_ok=True)
    run_identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "authorization_digest": authorization["authorization_digest"],
        "training_contract_digest": authorization["training_contract_digest"],
        "code_references": dict(code_references),
        "accessed": {"training": [], "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": []},
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file() and _read_json(identity_path) != run_identity:
        raise ContractError("v7 teacher run identity collision")
    if not identity_path.is_file():
        _atomic_json(identity_path, run_identity)

    raw_records = _cache_raw_windows(rows, raw_dir=raw_dir, workers=workers, retries=retries)
    _atomic_jsonl(run_dir / "raw_manifest_v7.jsonl", raw_records)

    from src.core import data_loader

    if raw_dir not in data_loader._DATA_DIRECTORIES:
        data_loader._DATA_DIRECTORIES.insert(0, raw_dir)
    representation = RepresentationContract.from_reference_manifest(root / "config/reference_artifacts.json")
    actual_prepare = prepare or (
        lambda window: prepare_teacher_input(
            window, representation=representation, local_only=True
        )
    )
    exact = None
    if score is None:
        exact = ExactNativeTeacher(root=root, representation=representation, device=device)
        actual_score = exact.score
    else:
        actual_score = score
    thresholds = _thresholds(root)
    batches = [rows[start : start + 8] for start in range(0, len(rows), 8)]
    payloads: list[dict[str, Any]] = []
    for batch_index, batch_rows in enumerate(batches):
        expected_ids = [str(row["identity_id"]) for row in batch_rows]
        batch_path = batch_dir / f"batch_{batch_index:04d}.json"
        if batch_path.is_file():
            payloads.append(
                _validate_teacher_batch(batch_path, run_key=run_key, expected_ids=expected_ids)
            )
            continue
        prepared_by_id: dict[str, PreparedTeacherInput] = {}
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(actual_prepare, WindowIdentity.from_dict(row["window"])): row
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
            _atomic_json(run_dir / "failure.json", {
                "status": "NOT_READY_INCOMPLETE_TRAINING_INPUT",
                "run_key": run_key,
                "failures": failures,
                "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
            })
            raise ContractError(f"v7 teacher preparation failed for {len(failures)} windows")
        prepared = [prepared_by_id[row["identity_id"]] for row in batch_rows]
        scores, timings = actual_score([item.image for item in prepared])
        if len(scores) != len(batch_rows) or not np.isfinite(scores).all():
            raise ContractError("v7 exact teacher returned invalid scores")
        strain = np.stack([item.clean_strain for item in prepared]).astype(np.float32, copy=False)
        window_ids = np.asarray([row["window"]["window_id"] for row in batch_rows], dtype="U32")
        identity_ids = np.asarray(expected_ids, dtype="U32")
        shard = batch_dir / f"batch_{batch_index:04d}_clean_strain.npz"
        _atomic_npz(shard, clean_strain=strain, window_ids=window_ids, identity_ids=identity_ids)
        result_rows = []
        for row, item, native_score in zip(batch_rows, prepared, scores, strict=True):
            threshold = thresholds[row["detector"]]
            result_rows.append(
                {
                    "identity_id": row["identity_id"],
                    "window_id": row["window"]["window_id"],
                    "detector": row["detector"],
                    "sampling_role": row["sampling_role"],
                    "subset": row["subset"],
                    "block_key": row["block_key"],
                    "raw_strain_sha256": item.raw_strain_sha256,
                    "clean_strain_sha256": item.clean_strain_sha256,
                    "image_sha256": item.image_sha256,
                    "teacher_target": {
                        "name": TARGET_NAME,
                        "score_key": TARGET_SCORE_KEY,
                        TARGET_NAME: float(native_score),
                        "float32_hex": np.float32(native_score).tobytes().hex(),
                        "historical_detector_threshold": threshold,
                        "defer_label": strict_defer_label(float(native_score), threshold),
                    },
                    "preparation_timings_s": item.timings,
                }
            )
        batch_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "COMPLETE",
            "run_key": run_key,
            "batch_index": batch_index,
            "strain_shard": {
                "path": shard.name,
                "sha256": file_sha256(shard),
                "dtype": "float32",
                "shape": list(strain.shape),
            },
            "score_timings_s": timings,
            "rows": result_rows,
            "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
        }
        payload = {**batch_body, "batch_digest": canonical_json_sha256(batch_body)}
        _atomic_json(batch_path, payload)
        payloads.append(payload)

    compact_rows = []
    batch_references = []
    for payload in payloads:
        batch_path = batch_dir / f"batch_{int(payload['batch_index']):04d}.json"
        batch_references.append({"path": batch_path.relative_to(run_dir).as_posix(), "sha256": file_sha256(batch_path)})
        for offset, row in enumerate(payload["rows"]):
            compact_rows.append({
                **row,
                "strain_shard": payload["strain_shard"],
                "strain_row_index": offset,
                "batch_reference": batch_references[-1],
            })
    compact_rows.sort(key=lambda row: row["identity_id"])
    complete = limit is None
    if complete and len(compact_rows) != 600:
        raise ContractError("v7 teacher ledger is incomplete")
    role_labels = {
        f"{detector}/{role}": {
            "n": sum(row["detector"] == detector and row["sampling_role"] == role for row in compact_rows),
            "defer_label_1": sum(row["detector"] == detector and row["sampling_role"] == role and row["teacher_target"]["defer_label"] == 1 for row in compact_rows),
        }
        for detector in DETECTORS for role in ROLES
    }
    summary_body = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_TRAINING_ONLY" if complete else "SMOKE_ONLY_NON_PROMOTABLE",
        "run_key": run_key,
        "authorization_digest": authorization["authorization_digest"],
        "training_contract_digest": authorization["training_contract_digest"],
        "row_count": len(compact_rows),
        "expected_row_count": 600,
        "batch_count": len(payloads),
        "role_label_counts": role_labels,
        "batch_references": batch_references,
        "raw_manifest": {
            "path": "raw_manifest_v7.jsonl",
            "sha256": file_sha256(run_dir / "raw_manifest_v7.jsonl"),
            "record_count": len(raw_records),
        },
        "compact_targets": {
            "path": DEFAULT_TARGETS.relative_to(root).as_posix(),
            "records_digest": canonical_json_sha256(compact_rows),
        },
        "code_references": dict(code_references),
        "cache_location": {"environment_alias": "DANTE_V7_TRAINING_CACHE_ROOT", "run_subdirectory": run_dir.name},
        "student_training_executed": False,
        "accessed": {
            "training_identity_ids": [row["identity_id"] for row in compact_rows],
            "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
        },
    }
    summary = {**summary_body, "artifact_digest": canonical_json_sha256(summary_body)}
    _atomic_jsonl(run_dir / "teacher_targets_compact_v7.jsonl", compact_rows)
    _atomic_json(run_dir / "teacher_ledger_summary_v7.json", summary)
    if complete:
        _atomic_jsonl(DEFAULT_TARGETS, compact_rows)
        summary["compact_targets"]["sha256"] = file_sha256(DEFAULT_TARGETS)
        body = dict(summary)
        body.pop("artifact_digest")
        summary["artifact_digest"] = canonical_json_sha256(body)
        _atomic_json(run_dir / "teacher_ledger_summary_v7.json", summary)
        _atomic_json(DEFAULT_LEDGER_SUMMARY, summary)
    return summary


@dataclass(slots=True)
class TrainingArrays:
    strain: np.ndarray
    labels: np.ndarray
    detectors: np.ndarray
    roles: np.ndarray
    subsets: np.ndarray
    identity_ids: tuple[str, ...]


def load_training_arrays(
    *, root: Path, cache_root: Path, summary_path: Path = DEFAULT_LEDGER_SUMMARY
) -> TrainingArrays:
    summary = _read_json(summary_path)
    if summary.get("status") != "COMPLETE_TRAINING_ONLY":
        raise ContractError("v7 teacher ledger is not complete")
    run_dir = cache_root.resolve() / summary["cache_location"]["run_subdirectory"]
    rows = _read_jsonl(root / summary["compact_targets"]["path"])
    if file_sha256(root / summary["compact_targets"]["path"]) != summary["compact_targets"]["sha256"]:
        raise ContractError("v7 compact teacher targets changed")
    values = []
    for row in rows:
        shard_path = run_dir / "batches" / row["strain_shard"]["path"]
        if not shard_path.is_file() or file_sha256(shard_path) != row["strain_shard"]["sha256"]:
            raise ContractError("v7 training strain shard changed")
        with np.load(shard_path, allow_pickle=False) as shard:
            value = np.asarray(shard["clean_strain"][int(row["strain_row_index"])], dtype=np.float32)
        if value.shape != (131072,) or not np.isfinite(value).all():
            raise NumericalTrainingFailure("non-finite or malformed v7 training strain")
        if hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest() != row["clean_strain_sha256"]:
            raise ContractError("v7 cached clean-strain digest mismatch")
        values.append(value)
    return TrainingArrays(
        strain=np.stack(values),
        labels=np.asarray([row["teacher_target"]["defer_label"] for row in rows], dtype=np.float32),
        detectors=np.asarray([DETECTORS.index(row["detector"]) for row in rows], dtype=np.int8),
        roles=np.asarray([ROLES.index(row["sampling_role"]) for row in rows], dtype=np.int8),
        subsets=np.asarray([SUBSETS.index(row["subset"]) for row in rows], dtype=np.int8),
        identity_ids=tuple(row["identity_id"] for row in rows),
    )


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


def balanced_epoch_batches(
    arrays: TrainingArrays, *, subset: str, seed: int, epoch: int, batch_per_cell: int
) -> list[np.ndarray]:
    if subset not in SUBSETS or batch_per_cell < 1:
        raise ContractError("v7 balanced-batch request is invalid")
    cell_rows: dict[tuple[int, int], list[int]] = {}
    for detector in range(2):
        for role in range(2):
            current = np.flatnonzero(
                (arrays.detectors == detector)
                & (arrays.roles == role)
                & (arrays.subsets == SUBSETS.index(subset))
            ).tolist()
            generator = np.random.default_rng(
                np.random.SeedSequence([seed & 0xFFFFFFFF, seed >> 32, epoch, detector, role])
            )
            current = [current[int(index)] for index in generator.permutation(len(current))]
            cell_rows[(detector, role)] = current
    lengths = {len(value) for value in cell_rows.values()}
    if len(lengths) != 1:
        raise ContractError("v7 balanced cells have unequal cardinality")
    count = lengths.pop()
    batches = []
    for start in range(0, count, batch_per_cell):
        indices = []
        for detector in range(2):
            for role in range(2):
                indices.extend(cell_rows[(detector, role)][start : start + batch_per_cell])
        batches.append(np.asarray(indices, dtype=np.int64))
    flattened = np.concatenate(batches)
    expected = np.flatnonzero(arrays.subsets == SUBSETS.index(subset))
    if len(flattened) != len(expected) or set(flattened.tolist()) != set(expected.tolist()):
        raise ContractError("v7 epoch batching is not without replacement")
    return batches


def _finite_tensor(value: torch.Tensor, label: str) -> None:
    if not torch.isfinite(value).all().item():
        raise NumericalTrainingFailure(f"non-finite {label}")


def _finite_optimizer(optimizer: torch.optim.Optimizer) -> None:
    for state in optimizer.state.values():
        for value in state.values():
            if isinstance(value, torch.Tensor):
                _finite_tensor(value, "optimizer state")


def _binary_metrics(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    if len(labels) == 0 or not np.isfinite(probabilities).all():
        raise NumericalTrainingFailure("invalid v7 diagnostic predictions")
    result = {
        "n": len(labels),
        "positive": int(labels.sum()),
        "bce": float(torch.nn.functional.binary_cross_entropy(
            torch.from_numpy(probabilities.astype(np.float64)),
            torch.from_numpy(labels.astype(np.float64)),
        ).item()),
        "score_mean": float(np.mean(probabilities)),
        "score_std_population": float(np.std(probabilities, ddof=0)),
    }
    if len(np.unique(labels)) == 2:
        result["auroc_diagnostic_only"] = float(roc_auc_score(labels, probabilities))
        result["average_precision_diagnostic_only"] = float(average_precision_score(labels, probabilities))
    else:
        result["auroc_diagnostic_only"] = None
        result["average_precision_diagnostic_only"] = None
    return result


def _validation_metrics(
    model: torch.nn.Module, arrays: TrainingArrays, *, device: torch.device
) -> dict[str, Any]:
    model.eval()
    probabilities = np.full(len(arrays.labels), np.nan, dtype=np.float64)
    validation = np.flatnonzero(arrays.subsets == SUBSETS.index("internal_validation"))
    with torch.inference_mode():
        for start in range(0, len(validation), 64):
            indices = validation[start : start + 64]
            inputs = torch.from_numpy(arrays.strain[indices, None, :]).to(device)
            logits = model(inputs).squeeze(-1)
            _finite_tensor(logits, "v7 validation logits")
            probabilities[indices] = torch.sigmoid(logits).cpu().numpy()
    by_detector = {}
    for detector_index, detector in enumerate(DETECTORS):
        indices = validation[arrays.detectors[validation] == detector_index]
        by_detector[detector] = _binary_metrics(arrays.labels[indices], probabilities[indices])
    return {
        "by_detector": by_detector,
        "equal_detector_mean_bce": float(np.mean([row["bce"] for row in by_detector.values()])),
    }


def checkpoint_better(candidate: Mapping[str, Any], incumbent: Mapping[str, Any] | None) -> bool:
    if incumbent is None:
        return True
    return float(candidate["equal_detector_mean_bce"]) < float(incumbent["equal_detector_mean_bce"])


def _optimizer(model: torch.nn.Module, contract: Mapping[str, Any]) -> torch.optim.AdamW:
    spec = contract["optimization"]["optimizer"]
    return torch.optim.AdamW(
        model.parameters(),
        lr=float(spec["learning_rate"]),
        weight_decay=float(spec["weight_decay"]),
        betas=tuple(float(value) for value in spec["betas"]),
        eps=float(spec["epsilon"]),
    )


def training_environment(device: torch.device) -> dict[str, Any]:
    return {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "numpy": np.__version__,
        "device": str(device),
        "cuda_available": torch.cuda.is_available(),
        "cuda_runtime": torch.version.cuda,
        "cuda_device": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "deterministic_algorithms": True,
        "dtype": "float32",
    }


def training_run_key(
    authorization: Mapping[str, Any], code_references: Mapping[str, Mapping[str, str]], environment: Mapping[str, Any]
) -> str:
    return canonical_json_sha256({
        "authorization_digest": authorization["authorization_digest"],
        "code_references": dict(code_references),
        "environment": dict(environment),
    })


def train_member(
    *, root: Path, contract: Mapping[str, Any], arrays: TrainingArrays, run_dir: Path,
    run_key: str, member_index: int, seed: int, device: torch.device,
) -> dict[str, Any]:
    from src.dante_light.prefilter_v7_training_freeze import build_ensemble

    member_dir = run_dir / f"member_{member_index}"
    summary_path = member_dir / "member_summary.json"
    if summary_path.is_file():
        saved = _read_json(summary_path)
        if saved.get("run_key") != run_key or saved.get("seed") != seed:
            raise ContractError("v7 member cache identity collision")
        return saved
    deterministic_environment(seed)
    ensemble = build_ensemble(root, contract["candidate"]["member_seeds"])
    model = ensemble.members[member_index].to(device=device, dtype=torch.float32)
    optimizer = _optimizer(model, contract)
    loss_fn = torch.nn.BCEWithLogitsLoss(reduction="mean")
    maximum_epochs = int(contract["optimization"]["maximum_epochs"])
    per_cell = int(contract["optimization"]["batch"]["full_batch_per_detector_sampling_role"])
    member_dir.mkdir(parents=True, exist_ok=True)
    latest_path = member_dir / "latest_state.pt"
    metrics: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    start_epoch = 1
    if latest_path.is_file():
        state = torch.load(latest_path, map_location=device, weights_only=True)
        if state.get("run_key") != run_key or int(state.get("seed")) != seed:
            raise ContractError("v7 member checkpoint identity collision")
        model.load_state_dict(state["model_state"])
        optimizer.load_state_dict(state["optimizer_state"])
        metrics = state["metrics"]
        best = state["best"]
        start_epoch = int(state["epoch"]) + 1
    started = time.perf_counter()
    try:
        for epoch in range(start_epoch, maximum_epochs + 1):
            model.train()
            batches = balanced_epoch_batches(
                arrays, subset="fit", seed=seed, epoch=epoch, batch_per_cell=per_cell
            )
            loss_total = 0.0
            sample_total = 0
            epoch_started = time.perf_counter()
            for indices in batches:
                inputs = torch.from_numpy(arrays.strain[indices, None, :]).to(device)
                labels = torch.from_numpy(arrays.labels[indices]).to(device)
                _finite_tensor(inputs, "v7 fit input")
                _finite_tensor(labels, "v7 fit label")
                optimizer.zero_grad(set_to_none=True)
                logits = model(inputs).squeeze(-1)
                _finite_tensor(logits, "v7 fit logits")
                loss = loss_fn(logits, labels)
                _finite_tensor(loss, "v7 fit loss")
                loss.backward()
                for parameter in model.parameters():
                    if parameter.grad is not None:
                        _finite_tensor(parameter.grad, "v7 gradient")
                optimizer.step()
                for parameter in model.parameters():
                    _finite_tensor(parameter, "v7 parameter")
                _finite_optimizer(optimizer)
                loss_total += float(loss.item()) * len(indices)
                sample_total += len(indices)
            validation = _validation_metrics(model, arrays, device=device)
            epoch_record = {
                "epoch": epoch,
                "fit_bce_sample_mean": loss_total / sample_total,
                "fit_sample_count": sample_total,
                "fit_batch_count": len(batches),
                "validation": validation,
                "elapsed_s": time.perf_counter() - epoch_started,
                "learning_rate": float(optimizer.param_groups[0]["lr"]),
            }
            metrics.append(epoch_record)
            if checkpoint_better(validation, None if best is None else best["validation"]):
                best = {"epoch": epoch, "validation": validation}
                _atomic_torch(member_dir / "best_model.pt", {
                    "schema_version": SCHEMA_VERSION,
                    "run_key": run_key,
                    "member_index": member_index,
                    "seed": seed,
                    "epoch": epoch,
                    "validation": validation,
                    "model_state": model.state_dict(),
                })
            _atomic_torch(latest_path, {
                "schema_version": SCHEMA_VERSION,
                "run_key": run_key,
                "member_index": member_index,
                "seed": seed,
                "epoch": epoch,
                "best": best,
                "model_state": model.state_dict(),
                "optimizer_state": optimizer.state_dict(),
                "metrics": metrics,
            })
            _atomic_json(member_dir / "metrics.json", {"epochs": metrics})
    except NumericalTrainingFailure as exc:
        body = {
            "schema_version": SCHEMA_VERSION, "status": "FAILED_NUMERICAL",
            "run_key": run_key, "member_index": member_index, "seed": seed,
            "reason": str(exc), "completed_epochs": len(metrics),
            "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
            "candidate_promotion_allowed": False,
        }
        summary = {**body, "member_digest": canonical_json_sha256(body)}
        _atomic_json(summary_path, summary)
        return summary
    if best is None:
        raise NumericalTrainingFailure("v7 member produced no finite checkpoint")
    best_path = member_dir / "best_model.pt"
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "TRAINING_COMPLETE_NON_PROMOTABLE",
        "run_key": run_key,
        "member_index": member_index,
        "seed": seed,
        "completed_epochs": len(metrics),
        "best_epoch": best["epoch"],
        "best_validation": best["validation"],
        "best_model": {"path": best_path.relative_to(run_dir).as_posix(), "sha256": file_sha256(best_path)},
        "metrics": {"path": (member_dir / "metrics.json").relative_to(run_dir).as_posix(), "sha256": file_sha256(member_dir / "metrics.json")},
        "elapsed_this_invocation_s": time.perf_counter() - started,
        "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
        "candidate_promotion_allowed": False,
    }
    summary = {**body, "member_digest": canonical_json_sha256(body)}
    _atomic_json(summary_path, summary)
    return summary


def run_training(
    *, root: Path = ROOT, cache_root: Path = DEFAULT_CACHE,
    authorization_path: Path = DEFAULT_AUTHORIZATION,
    code_references: Mapping[str, Mapping[str, str]], device_name: str | None = None,
) -> dict[str, Any]:
    authorization = load_training_authorization(authorization_path, root=root)
    contract = load_training_freeze(root=root)
    for name, reference in code_references.items():
        _resolve_reference(root, reference, name)
    device = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))
    environment = training_environment(device)
    run_key = training_run_key(authorization, code_references, environment)
    run_dir = cache_root.resolve() / f"student_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    identity = {
        "schema_version": SCHEMA_VERSION, "status": "RUN_IDENTITY", "run_key": run_key,
        "authorization_digest": authorization["authorization_digest"],
        "training_contract_digest": contract["training_contract_digest"],
        "code_references": dict(code_references), "environment": environment,
        "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
    }
    identity_path = run_dir / "run_identity.json"
    if identity_path.is_file() and _read_json(identity_path) != identity:
        raise ContractError("v7 training run identity collision")
    if not identity_path.is_file():
        _atomic_json(identity_path, identity)
    arrays = load_training_arrays(root=root, cache_root=cache_root)
    members = []
    for member_index, seed in enumerate(contract["candidate"]["member_seeds"]):
        members.append(train_member(
            root=root, contract=contract, arrays=arrays, run_dir=run_dir,
            run_key=run_key, member_index=member_index, seed=int(seed), device=device,
        ))
    failed = [row for row in members if row["status"] != "TRAINING_COMPLETE_NON_PROMOTABLE"]
    body = {
        **identity,
        "status": "FAILED_NUMERICAL" if failed else "TRAINING_COMPLETE_NON_PROMOTABLE",
        "member_count": len(members),
        "all_five_members_complete": not failed and len(members) == 5,
        "members": members,
        "ensemble_validation_diagnostic_only": {
            "member_equal_detector_bce": [row.get("best_validation", {}).get("equal_detector_mean_bce") for row in members],
            "selection_or_promotion_role": False,
        },
        "teacher_ledger_reference": repository_reference(root, DEFAULT_LEDGER_SUMMARY),
        "cache_location": {"environment_alias": "DANTE_V7_TRAINING_CACHE_ROOT", "run_subdirectory": run_dir.name},
        "threshold_search_automatic_access": False,
        "threshold_search": [], "risk_calibration": [], "confirmation": [], "o4b": [],
        "routing_enabled": False, "candidate_promoted": False,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "student_training_summary_v7.json", summary)
    _atomic_json(DEFAULT_TRAINING_SUMMARY, summary)
    return summary


def execution_code_references(root: Path = ROOT) -> dict[str, dict[str, str]]:
    return {
        "training_implementation": repository_reference(root, root / "src/dante_light/prefilter_v7_training.py"),
        "training_runner": repository_reference(root, root / "scripts/run_dante_light_prefilter_v7_training.py"),
        "core_preprocessor": repository_reference(root, root / "src/core/preprocessor.py"),
        "data_loader": repository_reference(root, root / "src/core/data_loader.py"),
        "patch_scorer": repository_reference(root, root / "src/core/patch_scorer.py"),
        "exact_teacher": repository_reference(root, root / "src/dante_light/prefilter_v5_teacher.py"),
        "student_architecture": repository_reference(root, root / "src/dante_light/prefilter_v6_phase_a.py"),
        "training_contract": repository_reference(root, root / "config/dante_light_prefilter_v7_training_contract.json"),
        "training_split": repository_reference(root, root / "config/dante_light_prefilter_v7_training_split.jsonl"),
        "identity_manifest": repository_reference(root, root / "config/dante_light_prefilter_v7_identities.jsonl"),
        "historical_thresholds": repository_reference(root, root / "config/dante_light_epochs_v1.json"),
        "reference_artifacts": repository_reference(root, root / "config/reference_artifacts.json"),
    }
