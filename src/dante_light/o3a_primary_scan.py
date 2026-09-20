"""Frozen, resumable, frame-streaming O3a primary scan.

Only the already frozen CBC_CAT1 identity universe is scored.  Raw frames not
belonging to the retained calibration subset live in a bounded transient cache
and are removed after their final use; their hashes remain in SQLite evidence.
Intermediate candidate outcomes are intentionally absent from progress output.
"""

from __future__ import annotations

from collections import Counter, deque
from concurrent.futures import Future, ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import queue
import sqlite3
import threading
import time
from typing import Any, Iterator, Mapping, Sequence

import h5py
import numpy as np
import requests

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_initial_calibration_acceptance import (
    CONTRACT_REL as ACCEPTANCE_CONTRACT_REL,
    _build_scorer,
    _preprocess_task,
    _tokens_are_finite,
    file_sha256,
    load_acceptance_contract,
)
from src.dante_light.o3a_initial_thresholds import (
    CONTRACT_REL as THRESHOLD_CONTRACT_REL,
    load_threshold_contract,
)
from src.dante_light.o3a_native_contract import (
    ROOT,
    RUNTIME_REL,
    load_runtime_contract,
)
from src.dante_light.o3a_population_geometry import (
    MANIFEST_REL as IDENTITY_UNIVERSE_REL,
    iter_role_identities,
    load_identity_universes,
)
from src.dante_light.o3a_raw_acquisition import (
    INVENTORY_REL,
    _cover_interval,
    _inventory_frames,
    load_source_inventory,
)
from src.dante_light.o3a_raw_download import (
    CHUNK_BYTES,
    validate_hdf5_metadata,
)


CONTRACT_REL = "config/dante_o3a_primary_scan_v1.json"
THRESHOLD_ARTIFACT_REL = (
    "artifacts/dante_light/o3a_native_v1/initial_thresholds.json"
)
IMPLEMENTATION_REL = "src/dante_light/o3a_primary_scan.py"
FREEZE_ENTRYPOINT_REL = "scripts/freeze_dante_o3a_primary_scan.py"
RUN_ENTRYPOINT_REL = "scripts/run_dante_o3a_primary_scan.py"
TEST_REL = "tests/test_dante_o3a_primary_scan.py"
SCHEMA_VERSION = 1
DEFAULT_RAW_ROOT = Path("/mnt/e/o3a")
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")
DEFAULT_WORKERS_PER_DETECTOR = 8
DEFAULT_ENCODER_BATCH_SIZE = 32
DEFAULT_MAX_PREPROCESS_IN_FLIGHT = 16
DEFAULT_QUEUE_DEPTH_BATCHES = 2
DEFAULT_DATABASE_COMMIT_ROWS = 1024
DEFAULT_DOWNLOAD_RETRIES = 5


class InfrastructureError(RuntimeError):
    """A retryable transport or host failure, not a scientific failure."""


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _binding(root: Path, relative: str, **extra: Any) -> dict[str, Any]:
    return {
        "path": relative,
        "sha256": file_sha256(root / relative),
        **extra,
    }


def _implementation_sources(root: Path) -> dict[str, str]:
    relatives = (
        IMPLEMENTATION_REL,
        FREEZE_ENTRYPOINT_REL,
        RUN_ENTRYPOINT_REL,
        TEST_REL,
        "src/dante_light/o3a_initial_calibration_acceptance.py",
        "src/dante_light/o3a_raw_download.py",
    )
    return {relative: file_sha256(root / relative) for relative in relatives}


def _threshold_body(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "artifact_digest"}


def _threshold_artifact(root: Path) -> dict[str, Any]:
    value = _read_json(root / THRESHOLD_ARTIFACT_REL)
    if (
        value.get("status") != "PASS_VERIFIED_O3A_INITIAL_THRESHOLDS"
        or value.get("artifact_digest")
        != canonical_json_sha256(_threshold_body(value))
        or value.get("adequacy_gate", {}).get("passed") is not True
    ):
        raise ContractError("O3a initial-threshold artifact is not verified")
    return value


def group_identities_by_target_frame(
    identities: Sequence[int], frames: Sequence[Mapping[str, Any]]
) -> list[tuple[dict[str, Any], list[int]]]:
    """Assign each ordered analysis start to its unique containing frame."""

    result: list[tuple[dict[str, Any], list[int]]] = []
    frame_index = 0
    previous: int | None = None
    for raw_gps in identities:
        gps = int(raw_gps)
        if previous is not None and gps <= previous:
            raise ContractError("O3a scan identities are not strictly increasing")
        previous = gps
        while (
            frame_index < len(frames)
            and int(frames[frame_index]["gps_end"]) <= gps
        ):
            frame_index += 1
        if frame_index >= len(frames):
            raise ContractError(f"no O3a source frame contains GPS {gps}")
        frame = dict(frames[frame_index])
        if not int(frame["gps_start"]) <= gps < int(frame["gps_end"]):
            raise ContractError(f"O3a source inventory has a gap at GPS {gps}")
        if result and result[-1][0]["filename"] == frame["filename"]:
            result[-1][1].append(gps)
        else:
            result.append((frame, [gps]))
    return result


def _required_frame_summary(
    *, identities: Mapping[str, Sequence[int]], inventory: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    stream = hashlib.sha256()
    total = 0
    for detector in ("H1", "L1"):
        frames = _inventory_frames(inventory, detector)
        required: dict[str, Mapping[str, Any]] = {}
        for _, starts in group_identities_by_target_frame(
            identities[detector], frames
        ):
            coverage = _cover_interval(
                frames, min(starts) - 4, max(starts) + 36
            )
            for frame in coverage:
                required[str(frame["filename"])] = frame
        ordered = sorted(
            required.values(), key=lambda row: (int(row["gps_start"]), row["filename"])
        )
        for frame in ordered:
            stream.update(
                (
                    f"{detector}|{frame['gps_start']}|{frame['gps_end']}|"
                    f"{frame['filename']}|{frame['url']}\n"
                ).encode("utf-8")
            )
        result[detector] = len(ordered)
        total += len(ordered)
    return {
        "counts_by_detector": result,
        "total_count": total,
        "ordered_required_frame_stream_sha256": stream.hexdigest(),
    }


def build_scan_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    thresholds_contract = load_threshold_contract(root=root)
    thresholds = _threshold_artifact(root)
    acceptance = load_acceptance_contract(root=root)
    universe = load_identity_universes(root=root)
    inventory = load_source_inventory(root=root)
    runtime = load_runtime_contract(root=root, require_current=False)
    identities = {"H1": [], "L1": []}
    for detector, gps in iter_role_identities(
        universe, "primary_scan_geometric_universe"
    ):
        identities[detector].append(int(gps))
    required_frames = _required_frame_summary(
        identities=identities, inventory=inventory
    )
    threshold_values = {
        detector: float(thresholds["thresholds"][detector]["p99"])
        for detector in ("H1", "L1")
    }
    counts = universe["roles"]["primary_scan_geometric_universe"][
        "counts_by_detector"
    ]
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_PRIMARY_SCAN_V1",
        "run": "O3A",
        "parents": {
            "identity_universe": _binding(
                root,
                IDENTITY_UNIVERSE_REL,
                manifest_digest=universe["manifest_digest"],
            ),
            "source_inventory": _binding(
                root,
                INVENTORY_REL,
                inventory_digest=inventory["inventory_digest"],
            ),
            "acceptance_contract": _binding(
                root,
                ACCEPTANCE_CONTRACT_REL,
                contract_digest=acceptance["contract_digest"],
            ),
            "threshold_contract": _binding(
                root,
                THRESHOLD_CONTRACT_REL,
                contract_digest=thresholds_contract["contract_digest"],
            ),
            "threshold_artifact": _binding(
                root,
                THRESHOLD_ARTIFACT_REL,
                artifact_digest=thresholds["artifact_digest"],
                run_key=thresholds["run_key"],
            ),
            "canonical_runtime": _binding(
                root,
                RUNTIME_REL,
                contract_digest=runtime["contract_digest"],
                environment_digest=runtime["runtime_environment"][
                    "environment_digest"
                ],
            ),
        },
        "representation": dict(acceptance["method_parity"]),
        "population": {
            "role": "primary_scan_geometric_universe",
            "counts_by_detector": counts,
            "total_count": sum(int(value) for value in counts.values()),
            "identity_stream_sha256": universe["roles"][
                "primary_scan_geometric_universe"
            ]["ordered_identity_stream_sha256"],
            "required_source_frames": required_frames,
        },
        "thresholds": {
            "rule": "primary_score_strictly_greater_than_detector_p99",
            "values": threshold_values,
            "detector_pooling_allowed": False,
            "retuning_allowed": False,
        },
        "execution": {
            "device": "cuda",
            "workers_per_detector": DEFAULT_WORKERS_PER_DETECTOR,
            "encoder_batch_size": DEFAULT_ENCODER_BATCH_SIZE,
            "max_preprocess_in_flight_per_detector": (
                DEFAULT_MAX_PREPROCESS_IN_FLIGHT
            ),
            "detector_mode": "parallel_producers_shared_scorer",
            "queue_depth_batches": DEFAULT_QUEUE_DEPTH_BATCHES,
            "database_commit_rows": DEFAULT_DATABASE_COMMIT_ROWS,
            "download_retries": DEFAULT_DOWNLOAD_RETRIES,
            "raw_series_cache_files": 0,
            "temporary_frame_cleanup": "EVICT_AFTER_FINAL_USE",
            "sqlite_wal": True,
        },
        "storage": {
            "raw_root": DEFAULT_RAW_ROOT.as_posix(),
            "external_root": DEFAULT_EXTERNAL_ROOT.as_posix(),
            "transient_raw_subdirectory": "primary_scan_transient_raw",
            "retained_primary_scan_raw_frames": 0,
            "retained_calibration_raw_reuse_allowed": True,
        },
        "ci_asymmetry_annotation": {
            "status": "NON_CAUSAL_HYPOTHESIS",
            "observation": "L1_P99_CI_RELATIVE_WIDTH_EXCEEDS_H1",
            "hypothesis": (
                "detector-specific score-tail heterogeneity, nonstationarity, "
                "or calibration-population composition may contribute"
            ),
            "not_established_by": [
                "gross CBC_CAT1 livetime",
                "gross CBC_CAT1 segment count",
            ],
            "required_followup": (
                "compare recurrence at native calibration and final thresholds"
            ),
        },
        "scientific_boundary": {
            "fresh_o3a_scores_only": True,
            "candidate_outcomes_visible_during_run": False,
            "native_classification_executed": False,
            "native_cohort_selected": False,
            "taxonomy_coincidence_pem_executed": False,
            "publication_claim_authorized": False,
        },
        "implementation_sources": _implementation_sources(root),
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_scan_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("contract_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("O3a primary-scan contract digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_O3A_PRIMARY_SCAN_V1"
        or value.get("run") != "O3A"
        or value.get("implementation_sources") != _implementation_sources(root)
    ):
        raise ContractError("O3a primary-scan contract boundary changed")
    for reference in value["parents"].values():
        path = root / str(reference["path"])
        if not path.is_file() or file_sha256(path) != reference["sha256"]:
            raise ContractError(f"O3a primary-scan parent changed: {path}")
    expected = build_scan_contract(root=root)
    if dict(value) != expected:
        raise ContractError("O3a primary-scan contract is stale")
    return dict(value)


def load_scan_contract(*, root: Path = ROOT) -> dict[str, Any]:
    return validate_scan_contract(_read_json(root / CONTRACT_REL), root=root)


def write_scan_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_scan_contract(root=root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


class FrameGroupReader:
    """Read exact 40-second contexts from already verified frame files."""

    def __init__(
        self,
        frames: Sequence[Mapping[str, Any]],
        paths: Mapping[str, Path],
    ) -> None:
        self.frames = [dict(frame) for frame in frames]
        self.paths = paths
        self.handles: dict[str, h5py.File] = {}

    def __enter__(self) -> FrameGroupReader:
        try:
            for frame in self.frames:
                filename = str(frame["filename"])
                path = self.paths[filename]
                handle: h5py.File | None = None
                last_error: OSError | None = None
                for attempt in range(4):
                    try:
                        handle = h5py.File(path, "r")
                        break
                    except (FileNotFoundError, OSError) as exc:
                        last_error = exc
                        if attempt < 3:
                            time.sleep(0.25 * (attempt + 1))
                if handle is None:
                    raise InfrastructureError(
                        f"O3a scan frame could not be opened after preparation: {path}"
                    ) from last_error
                dataset = handle.get("strain/Strain")
                if dataset is None:
                    handle.close()
                    raise ContractError("O3a scan strain dataset is absent")
                self.handles[filename] = handle
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *_: object) -> None:
        for handle in self.handles.values():
            handle.close()
        self.handles.clear()

    def read(self, start: int, end: int) -> np.ndarray:
        pieces: list[np.ndarray] = []
        cursor = int(start)
        for frame in self.frames:
            frame_start = int(frame["gps_start"])
            frame_end = int(frame["gps_end"])
            if frame_end <= cursor or frame_start >= end:
                continue
            used_start = max(cursor, frame_start)
            used_end = min(end, frame_end)
            first = (used_start - frame_start) * 4096
            last = (used_end - frame_start) * 4096
            dataset = self.handles[str(frame["filename"])]["strain/Strain"]
            values = np.asarray(dataset[first:last], dtype=np.float64)
            if values.shape != (last - first,) or not np.isfinite(values).all():
                raise ContractError("O3a scan raw slice is invalid")
            pieces.append(values)
            cursor = used_end
            if cursor >= end:
                break
        joined = np.ascontiguousarray(np.concatenate(pieces), dtype=np.float64)
        if cursor != end or joined.shape != ((end - start) * 4096,):
            raise ContractError("O3a scan context coverage is incomplete")
        return joined


def _download_frame(
    *,
    frame: Mapping[str, Any],
    target: Path,
    retries: int,
    expected_sha256: str | None,
) -> dict[str, Any]:
    """Download one inventory-bound frame atomically and validate it."""

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        validate_hdf5_metadata(target, frame)
        digest = file_sha256(target)
        if expected_sha256 is not None and digest != expected_sha256:
            raise ContractError("resumed O3a scan frame hash changed")
        return {
            "sha256": digest,
            "size_bytes": target.stat().st_size,
            "network_bytes": 0,
            "source": "VERIFIED_EXISTING",
        }
    partial = target.with_suffix(target.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            existing = partial.stat().st_size if partial.is_file() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            with requests.get(
                str(frame["url"]),
                headers=headers,
                stream=True,
                timeout=(20, 180),
            ) as response:
                response.raise_for_status()
                append = existing > 0 and response.status_code == 206
                if append:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {existing}-"):
                        raise ContractError("invalid O3a scan Content-Range")
                mode = "ab" if append else "wb"
                if existing and not append:
                    existing = 0
                with partial.open(mode) as stream:
                    for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                        if chunk:
                            stream.write(chunk)
            validate_hdf5_metadata(partial, frame)
            digest = file_sha256(partial)
            if expected_sha256 is not None and digest != expected_sha256:
                raise ContractError("redownloaded O3a scan frame hash changed")
            size = partial.stat().st_size
            os.replace(partial, target)
            return {
                "sha256": digest,
                "size_bytes": size,
                "network_bytes": size - existing,
                "source": "GWOSC_HTTPS",
            }
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 30))
    if isinstance(last_error, (OSError, requests.RequestException)):
        raise InfrastructureError(
            f"O3a scan frame transport failed: {last_error}"
        ) from last_error
    raise ContractError(f"O3a scan frame validation failed: {last_error}") from last_error


def _retained_raw_map(
    *, raw_root: Path, acceptance: Mapping[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    relative = Path(
        str(acceptance["verified_raw_input"]["manifest_relative_to_raw_root"])
    )
    manifest = raw_root / relative
    if (
        not manifest.is_file()
        or file_sha256(manifest)
        != acceptance["verified_raw_input"]["manifest_sha256"]
    ):
        raise ContractError("retained O3a calibration raw manifest changed")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _read_jsonl(manifest):
        detector = str(row["detector"])
        for copy in row["physical_copies"]:
            path = raw_root / str(copy["relative_path"])
            result[(detector, path.name)] = {
                "path": path,
                "sha256": str(copy["sha256"]),
            }
    return result


def _frame_record(
    detector: str,
    frame: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    retained: bool,
) -> dict[str, Any]:
    return {
        "detector": detector,
        "gps_start": int(frame["gps_start"]),
        "gps_end": int(frame["gps_end"]),
        "filename": str(frame["filename"]),
        "url": str(frame["url"]),
        "sha256": str(result["sha256"]),
        "size_bytes": int(result["size_bytes"]),
        "retained_calibration_raw": retained,
        "transport_source": str(result["source"]),
    }


def _prepare_frame(
    *,
    detector: str,
    frame: Mapping[str, Any],
    raw_root: Path,
    transient_root: Path,
    retained: Mapping[tuple[str, str], Mapping[str, Any]],
    known_hashes: Mapping[tuple[str, str], str],
    retries: int,
) -> tuple[Path, dict[str, Any], bool]:
    key = (detector, str(frame["filename"]))
    retained_row = retained.get(key)
    if retained_row is not None:
        path = Path(str(retained_row["path"]))
        result = _download_frame(
            frame=frame,
            target=path,
            retries=retries,
            expected_sha256=str(retained_row["sha256"]),
        )
        return path, _frame_record(detector, frame, result, retained=True), True
    target = transient_root / detector / str(frame["filename"])
    result = _download_frame(
        frame=frame,
        target=target,
        retries=retries,
        expected_sha256=known_hashes.get(key),
    )
    return target, _frame_record(detector, frame, result, retained=False), False


def _identity_digest(detector: str, gps: int) -> str:
    return canonical_json_sha256(
        {
            "run": "O3A",
            "detector": detector,
            "analysis_gps_start": gps,
            "duration_s": 32,
        }
    )


def _detector_events(
    *,
    detector: str,
    identities: Sequence[int],
    frames: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    raw_root: Path,
    transient_root: Path,
    retained: Mapping[tuple[str, str], Mapping[str, Any]],
    known_hashes: Mapping[tuple[str, str], str],
    completed: set[int],
) -> Iterator[tuple[str, Any]]:
    execution = contract["execution"]
    representation = contract["representation"]
    batch_size = int(execution["encoder_batch_size"])
    max_in_flight = int(execution["max_preprocess_in_flight_per_detector"])
    workers = int(execution["workers_per_detector"])
    retries = int(execution["download_retries"])
    groups = group_identities_by_target_frame(identities, frames)
    pending: deque[tuple[int, Future[np.ndarray]]] = deque()
    gps_batch: list[int] = []
    image_batch: list[np.ndarray] = []
    cached: dict[str, tuple[Path, Mapping[str, Any], bool]] = {}

    def drain_one() -> Iterator[tuple[str, Any]]:
        gps, future = pending.popleft()
        image = future.result()
        if image.shape != (256, 256, 3) or not np.isfinite(image).all():
            raise ContractError("O3a scan preprocessing result is invalid")
        gps_batch.append(gps)
        image_batch.append(image)
        if len(gps_batch) == batch_size:
            yield "batch", (list(gps_batch), list(image_batch))
            gps_batch.clear()
            image_batch.clear()

    completed_normally = False
    try:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for group_index, (_, starts) in enumerate(groups):
                remaining = [gps for gps in starts if gps not in completed]
                if not remaining:
                    continue
                coverage = _cover_interval(
                    frames, min(remaining) - 4, max(remaining) + 36
                )
                paths: dict[str, Path] = {}
                for frame in coverage:
                    filename = str(frame["filename"])
                    cached_row = cached.get(filename)
                    if cached_row is not None and not cached_row[0].is_file():
                        cached.pop(filename)
                        cached_row = None
                    if cached_row is None:
                        path, record, is_retained = _prepare_frame(
                            detector=detector,
                            frame=frame,
                            raw_root=raw_root,
                            transient_root=transient_root,
                            retained=retained,
                            known_hashes=known_hashes,
                            retries=retries,
                        )
                        cached_row = (path, frame, is_retained)
                        cached[filename] = cached_row
                        yield "frame", record
                    paths[filename] = cached_row[0]
                with FrameGroupReader(coverage, paths) as reader:
                    for gps in remaining:
                        values = reader.read(gps - 4, gps + 36)
                        future = pool.submit(
                            _preprocess_task,
                            values,
                            float(gps - 4),
                            detector,
                            float(gps),
                            float(gps + 32),
                            float(representation["whitening_pad_s"]),
                            tuple(int(v) for v in representation["query_qrange"]),
                            tuple(
                                int(v)
                                for v in representation["frequency_range_hz"]
                            ),
                            tuple(int(v) for v in representation["image_shape"][:2]),
                            str(representation["colormap"]),
                        )
                        pending.append((gps, future))
                        while len(pending) >= max_in_flight:
                            yield from drain_one()
                next_start = (
                    min(groups[group_index + 1][1]) - 4
                    if group_index + 1 < len(groups)
                    else None
                )
                if next_start is not None:
                    for filename, (path, frame, is_retained) in list(cached.items()):
                        if int(frame["gps_end"]) <= next_start:
                            if not is_retained and path.is_file():
                                path.unlink()
                            cached.pop(filename)
            while pending:
                yield from drain_one()
            if gps_batch:
                yield "batch", (list(gps_batch), list(image_batch))
        completed_normally = True
    finally:
        if completed_normally:
            for path, _, is_retained in cached.values():
                if not is_retained and path.is_file():
                    path.unlink()


def _parallel_events(
    producers: Mapping[str, Iterator[tuple[str, Any]]], *, queue_depth: int
) -> Iterator[tuple[str, str, Any]]:
    event_queue: queue.Queue[tuple[str, str, Any]] = queue.Queue(
        maxsize=max(2, queue_depth * len(producers))
    )
    stop = threading.Event()
    consumer_active = threading.Event()
    consumer_active.set()

    def emit(event: tuple[str, str, Any], *, terminal: bool = False) -> bool:
        while consumer_active.is_set():
            if stop.is_set() and not terminal:
                return False
            try:
                event_queue.put(event, timeout=0.5)
                return True
            except queue.Full:
                continue
        return False

    def produce(detector: str, iterator: Iterator[tuple[str, Any]]) -> None:
        try:
            for kind, payload in iterator:
                if not emit((kind, detector, payload)):
                    break
        except BaseException as exc:
            emit(("error", detector, exc), terminal=True)
        finally:
            emit(("done", detector, None), terminal=True)

    threads = [
        threading.Thread(target=produce, args=(detector, iterator), daemon=True)
        for detector, iterator in producers.items()
    ]
    for thread in threads:
        thread.start()
    remaining = len(threads)
    first_error: tuple[str, BaseException] | None = None
    try:
        while remaining:
            kind, detector, payload = event_queue.get()
            if kind == "done":
                remaining -= 1
            elif kind == "error":
                if first_error is None:
                    first_error = (detector, payload)
                    stop.set()
            elif first_error is None:
                yield kind, detector, payload
        if first_error is not None:
            detector, error = first_error
            error.add_note(f"O3a {detector} primary-scan producer failed")
            raise error
    finally:
        stop.set()
        consumer_active.clear()
        for thread in threads:
            thread.join()


def _open_database(path: Path, *, identity: Mapping[str, Any]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata(
          key TEXT PRIMARY KEY, value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS windows(
          detector TEXT NOT NULL,
          gps_start INTEGER NOT NULL,
          primary_score REAL NOT NULL,
          score_float32_hex TEXT NOT NULL,
          is_candidate INTEGER NOT NULL,
          identity_digest TEXT NOT NULL,
          image_sha256 TEXT NOT NULL,
          mil_vector BLOB,
          top_k_indices BLOB,
          patch_anomaly_scores BLOB,
          PRIMARY KEY(detector,gps_start)
        );
        CREATE TABLE IF NOT EXISTS raw_frames(
          detector TEXT NOT NULL,
          gps_start INTEGER NOT NULL,
          gps_end INTEGER NOT NULL,
          filename TEXT NOT NULL,
          url TEXT NOT NULL,
          sha256 TEXT NOT NULL,
          size_bytes INTEGER NOT NULL,
          retained_calibration_raw INTEGER NOT NULL,
          PRIMARY KEY(detector,filename)
        );
        """
    )
    serialized = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    observed = connection.execute(
        "SELECT value FROM metadata WHERE key='run_identity'"
    ).fetchone()
    if observed is None:
        connection.execute(
            "INSERT INTO metadata(key,value) VALUES('run_identity',?)",
            (serialized,),
        )
        connection.commit()
    elif observed[0] != serialized:
        connection.close()
        raise ContractError("O3a primary-scan database identity changed")
    return connection


def _progress(
    run_dir: Path,
    *,
    connection: sqlite3.Connection,
    contract: Mapping[str, Any],
    status: str = "RUNNING",
    failure_count: int = 0,
) -> dict[str, Any]:
    completed = {
        detector: int(
            connection.execute(
                "SELECT COUNT(*) FROM windows WHERE detector=?", (detector,)
            ).fetchone()[0]
        )
        for detector in ("H1", "L1")
    }
    total = contract["population"]["counts_by_detector"]
    value = {
        "status": status,
        "completed_windows_by_detector": completed,
        "total_windows_by_detector": total,
        "completed_window_total": sum(completed.values()),
        "total_window_count": int(contract["population"]["total_count"]),
        "fraction_complete": sum(completed.values())
        / int(contract["population"]["total_count"]),
        "verified_raw_frame_count": int(
            connection.execute("SELECT COUNT(*) FROM raw_frames").fetchone()[0]
        ),
        "required_raw_frame_count": int(
            contract["population"]["required_source_frames"]["total_count"]
        ),
        "failure_count": failure_count,
        "candidate_outcomes_disclosed": False,
    }
    _atomic_json(run_dir / "progress.json", value)
    return value


def _run_key(contract: Mapping[str, Any], *, environment_digest: str) -> str:
    return canonical_json_sha256(
        {
            "stage": "o3a_primary_scan_v1",
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": environment_digest,
            "threshold_artifact_digest": contract["parents"][
                "threshold_artifact"
            ]["artifact_digest"],
        }
    )


def _run_identity(
    contract: Mapping[str, Any],
    *,
    run_key: str,
    environment_digest: str,
    preflight_digest: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": environment_digest,
        "execution": contract["execution"],
        "population_identity_stream_sha256": contract["population"][
            "identity_stream_sha256"
        ],
        "threshold_artifact_digest": contract["parents"][
            "threshold_artifact"
        ]["artifact_digest"],
        "preflight_digest": preflight_digest,
    }


def _insert_frame(connection: sqlite3.Connection, record: Mapping[str, Any]) -> None:
    key = (record["detector"], record["filename"])
    existing = connection.execute(
        "SELECT gps_start,gps_end,url,sha256,size_bytes,retained_calibration_raw "
        "FROM raw_frames WHERE detector=? AND filename=?",
        key,
    ).fetchone()
    expected = (
        int(record["gps_start"]),
        int(record["gps_end"]),
        str(record["url"]),
        str(record["sha256"]),
        int(record["size_bytes"]),
        int(bool(record["retained_calibration_raw"])),
    )
    if existing is not None and tuple(existing) != expected:
        raise ContractError("O3a primary-scan raw frame provenance changed")
    if existing is None:
        connection.execute(
            "INSERT INTO raw_frames VALUES(?,?,?,?,?,?,?,?)",
            (*key, *expected),
        )


def _preflight_path(run_dir: Path) -> Path:
    return run_dir / "preflight.json"


def load_primary_scan_preflight(
    *,
    contract: Mapping[str, Any],
    run_dir: Path,
    run_key: str,
    environment_digest: str,
) -> dict[str, Any]:
    path = _preflight_path(run_dir)
    if not path.is_file():
        raise ContractError("O3a primary-scan preflight is absent")
    value = _read_json(path)
    body = {key: item for key, item in value.items() if key != "preflight_digest"}
    if (
        value.get("preflight_digest") != canonical_json_sha256(body)
        or value.get("status") != "PASS_O3A_PRIMARY_SCAN_PREFLIGHT"
        or value.get("run_key") != run_key
        or value.get("contract_digest") != contract["contract_digest"]
        or value.get("runtime_environment_digest") != environment_digest
        or value.get("candidate_outcome_disclosed") is not False
        or value.get("finite_score_observed") is not True
    ):
        raise ContractError("O3a primary-scan preflight provenance mismatch")
    token_shape = value.get("token_shape")
    if (
        not isinstance(token_shape, list)
        or len(token_shape) != 3
        or token_shape[0] != 1
        or any(not isinstance(item, int) or item <= 0 for item in token_shape)
    ):
        raise ContractError("O3a primary-scan preflight token shape is invalid")
    return value


def preflight_primary_scan(
    *,
    root: Path = ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    """Exercise real raw context, preprocessing, CUDA encoding and scoring once.

    The deterministic first frozen identity is used without comparing its score
    with a threshold, and the score magnitude is never persisted.
    """

    root = root.resolve()
    raw_root = raw_root.resolve()
    external_root = external_root.resolve()
    contract = load_scan_contract(root=root)
    if device != contract["execution"]["device"]:
        raise ContractError("O3a primary-scan preflight device changed")
    runtime = load_runtime_contract(root=root, require_current=True, device=device)
    environment_digest = runtime["runtime_environment"]["environment_digest"]
    run_key = _run_key(contract, environment_digest=environment_digest)
    run_dir = external_root / f"primary_scan_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = _preflight_path(run_dir)
    if path.is_file():
        return (
            load_primary_scan_preflight(
                contract=contract,
                run_dir=run_dir,
                run_key=run_key,
                environment_digest=environment_digest,
            ),
            run_dir,
        )

    universe = load_identity_universes(root=root)
    inventory = load_source_inventory(root=root)
    acceptance = load_acceptance_contract(root=root)
    retained = _retained_raw_map(raw_root=raw_root, acceptance=acceptance)
    detector, gps = next(
        iter_role_identities(universe, "primary_scan_geometric_universe")
    )
    frames = _inventory_frames(inventory, detector)
    coverage = _cover_interval(frames, int(gps) - 4, int(gps) + 36)
    transient_root = run_dir / "preflight_transient_raw"
    paths: dict[str, Path] = {}
    records: list[dict[str, Any]] = []
    temporary: list[Path] = []
    try:
        for frame in coverage:
            frame_path, record, is_retained = _prepare_frame(
                detector=detector,
                frame=frame,
                raw_root=raw_root,
                transient_root=transient_root,
                retained=retained,
                known_hashes={},
                retries=int(contract["execution"]["download_retries"]),
            )
            paths[str(frame["filename"])] = frame_path
            records.append(record)
            if not is_retained:
                temporary.append(frame_path)
        with FrameGroupReader(coverage, paths) as reader:
            values = reader.read(int(gps) - 4, int(gps) + 36)
        representation = contract["representation"]
        image = _preprocess_task(
            values,
            float(int(gps) - 4),
            detector,
            float(gps),
            float(int(gps) + 32),
            float(representation["whitening_pad_s"]),
            tuple(int(v) for v in representation["query_qrange"]),
            tuple(int(v) for v in representation["frequency_range_hz"]),
            tuple(int(v) for v in representation["image_shape"][:2]),
            str(representation["colormap"]),
        )
        scorer = _build_scorer(root=root, contract=acceptance, device=device)
        tokens = scorer.encode_patch_tokens([image])
        if not _tokens_are_finite(tokens):
            raise ContractError("O3a primary-scan preflight tokens are non-finite")
        token_shape = [int(value) for value in tokens.shape]
        if (
            len(token_shape) != 3
            or token_shape[0] != 1
            or token_shape[1] <= 0
            or token_shape[2] <= 0
        ):
            raise ContractError("O3a primary-scan preflight token shape is invalid")
        score_rows = scorer.score_patch_tokens(tokens, 1.0, output_mode="score_only")
        if len(score_rows) != 1 or not np.isfinite(
            float(score_rows[0]["novelty_score"])
        ):
            raise ContractError("O3a primary-scan preflight score is invalid")
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_O3A_PRIMARY_SCAN_PREFLIGHT",
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": environment_digest,
            "deterministic_identity": {
                "detector": detector,
                "analysis_gps_start": int(gps),
                "identity_digest": _identity_digest(detector, int(gps)),
            },
            "source_frames": [
                {
                    "detector": row["detector"],
                    "filename": row["filename"],
                    "sha256": row["sha256"],
                    "retained_calibration_raw": row[
                        "retained_calibration_raw"
                    ],
                }
                for row in records
            ],
            "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
            "token_shape": token_shape,
            "finite_tokens_observed": True,
            "finite_score_observed": True,
            "candidate_outcome_disclosed": False,
        }
        value = {**body, "preflight_digest": canonical_json_sha256(body)}
        _atomic_json(path, value)
        return value, run_dir
    finally:
        for temporary_path in temporary:
            if temporary_path.is_file():
                temporary_path.unlink()
        if transient_root.is_dir():
            for directory in sorted(transient_root.rglob("*"), reverse=True):
                if directory.is_dir():
                    directory.rmdir()
            transient_root.rmdir()


def clear_infrastructure_failure(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> Path:
    """Archive one verified infrastructure failure so the same run can resume."""

    contract = load_scan_contract(root=root.resolve())
    runtime = load_runtime_contract(
        root=root.resolve(), require_current=True, device=device
    )
    run_key = _run_key(
        contract,
        environment_digest=runtime["runtime_environment"]["environment_digest"],
    )
    run_dir = external_root.resolve() / f"primary_scan_{run_key}"
    failure_path = run_dir / "failure.json"
    failure = _read_json(failure_path)
    body = {key: item for key, item in failure.items() if key != "artifact_digest"}
    if (
        failure.get("artifact_digest") != canonical_json_sha256(body)
        or failure.get("run_key") != run_key
        or failure.get("contract_digest") != contract["contract_digest"]
        or failure.get("failure_category") != "INFRASTRUCTURE_INTERRUPTION"
    ):
        raise ContractError("failure is not a verified retryable infrastructure event")
    archive = run_dir / "failures" / f"failure_{failure['artifact_digest']}.json"
    archive.parent.mkdir(parents=True, exist_ok=True)
    os.replace(failure_path, archive)
    return archive


def _run_primary_scan_locked(
    *,
    root: Path = ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    raw_root = raw_root.resolve()
    external_root = external_root.resolve()
    contract = load_scan_contract(root=root)
    if device != contract["execution"]["device"]:
        raise ContractError("O3a primary-scan device changed")
    runtime = load_runtime_contract(root=root, require_current=True, device=device)
    environment_digest = runtime["runtime_environment"]["environment_digest"]
    run_key = _run_key(contract, environment_digest=environment_digest)
    run_dir = external_root / f"primary_scan_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("O3a primary-scan failure artifact is present")
    summary_path = run_dir / "primary_scan_summary.json"
    if summary_path.is_file():
        return verify_primary_scan(root=root, external_root=external_root)
    preflight = load_primary_scan_preflight(
        contract=contract,
        run_dir=run_dir,
        run_key=run_key,
        environment_digest=environment_digest,
    )
    identity = _run_identity(
        contract,
        run_key=run_key,
        environment_digest=environment_digest,
        preflight_digest=preflight["preflight_digest"],
    )
    _atomic_json(run_dir / "run_identity.json", identity)
    connection = _open_database(run_dir / "primary_scan.sqlite", identity=identity)
    universe = load_identity_universes(root=root)
    inventory = load_source_inventory(root=root)
    acceptance = load_acceptance_contract(root=root)
    retained = _retained_raw_map(raw_root=raw_root, acceptance=acceptance)
    identities: dict[str, list[int]] = {"H1": [], "L1": []}
    for detector, gps in iter_role_identities(
        universe, "primary_scan_geometric_universe"
    ):
        identities[detector].append(int(gps))
    completed = {
        detector: {
            int(row[0])
            for row in connection.execute(
                "SELECT gps_start FROM windows WHERE detector=?", (detector,)
            )
        }
        for detector in ("H1", "L1")
    }
    known_hashes = {
        (str(row[0]), str(row[1])): str(row[2])
        for row in connection.execute(
            "SELECT detector,filename,sha256 FROM raw_frames"
        )
    }
    transient_root = run_dir / str(
        contract["storage"]["transient_raw_subdirectory"]
    )
    producers = {
        detector: _detector_events(
            detector=detector,
            identities=identities[detector],
            frames=_inventory_frames(inventory, detector),
            contract=contract,
            raw_root=raw_root,
            transient_root=transient_root,
            retained=retained,
            known_hashes=known_hashes,
            completed=completed[detector],
        )
        for detector in ("H1", "L1")
    }
    scorer = _build_scorer(root=root, contract=acceptance, device=device)
    thresholds = {
        detector: float(contract["thresholds"]["values"][detector])
        for detector in ("H1", "L1")
    }
    pending: list[tuple[Any, ...]] = []
    insert_sql = """
        INSERT INTO windows(
          detector,gps_start,primary_score,score_float32_hex,is_candidate,
          identity_digest,image_sha256,mil_vector,top_k_indices,
          patch_anomaly_scores
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
    """

    def flush() -> None:
        nonlocal pending
        if pending:
            with connection:
                connection.executemany(insert_sql, pending)
            pending = []
            _progress(run_dir, connection=connection, contract=contract)

    _progress(run_dir, connection=connection, contract=contract)
    try:
        for kind, detector, payload in _parallel_events(
            producers,
            queue_depth=int(contract["execution"]["queue_depth_batches"]),
        ):
            if kind == "frame":
                with connection:
                    _insert_frame(connection, payload)
                continue
            gps_batch, images = payload
            tokens = scorer.encode_patch_tokens(images)
            if not _tokens_are_finite(tokens):
                raise ContractError("O3a primary-scan tokens are non-finite")
            score_rows = scorer.score_patch_tokens(
                tokens, 1.0, output_mode="score_only"
            )
            if len(score_rows) != len(gps_batch):
                raise ContractError("O3a primary scorer returned the wrong row count")
            scores = [float(row["novelty_score"]) for row in score_rows]
            if not np.isfinite(np.asarray(scores, dtype=np.float64)).all():
                raise ContractError("O3a primary scorer returned a non-finite score")
            candidate_indices = [
                index
                for index, score in enumerate(scores)
                if score > thresholds[detector]
            ]
            full_by_index: dict[int, Mapping[str, Any]] = {}
            if candidate_indices:
                import torch

                selection = torch.as_tensor(candidate_indices, device=tokens.device)
                selected = tokens.index_select(0, selection)
                full_rows = scorer.score_patch_tokens(
                    selected, 1.0, output_mode="full"
                )
                for index, full in zip(candidate_indices, full_rows, strict=True):
                    if abs(float(full["novelty_score"]) - scores[index]) > 2e-7:
                        raise ContractError(
                            "O3a primary full/score-only paths diverged"
                        )
                    full_by_index[index] = full
            for index, (gps, image, score) in enumerate(
                zip(gps_batch, images, scores, strict=True)
            ):
                full = full_by_index.get(index)
                pending.append(
                    (
                        detector,
                        int(gps),
                        score,
                        np.float32(score).tobytes().hex(),
                        int(full is not None),
                        _identity_digest(detector, int(gps)),
                        hashlib.sha256(
                            np.ascontiguousarray(image).tobytes()
                        ).hexdigest(),
                        None
                        if full is None
                        else np.ascontiguousarray(
                            full["mil_vector"], dtype=np.float32
                        ).tobytes(),
                        None
                        if full is None
                        else np.ascontiguousarray(
                            full["top_k_indices"], dtype=np.int32
                        ).tobytes(),
                        None
                        if full is None
                        else np.ascontiguousarray(
                            full["patch_anomaly_scores"], dtype=np.float32
                        ).tobytes(),
                    )
                )
            if len(pending) >= int(contract["execution"]["database_commit_rows"]):
                flush()
        flush()
    except BaseException as exc:
        category = (
            "INFRASTRUCTURE_INTERRUPTION"
            if isinstance(
                exc,
                (
                    InfrastructureError,
                    OSError,
                    requests.RequestException,
                    KeyboardInterrupt,
                ),
            )
            else "STRUCTURAL_OR_SCIENTIFIC_FAILURE"
        )
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "FAILED_O3A_PRIMARY_SCAN",
            "failure_category": category,
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "error_type": type(exc).__name__,
            "error": str(exc),
            "uncommitted_row_count": len(pending),
        }
        failure["artifact_digest"] = canonical_json_sha256(failure)
        _atomic_json(failure_path, failure)
        _progress(
            run_dir,
            connection=connection,
            contract=contract,
            status="FAILED",
            failure_count=1,
        )
        connection.close()
        raise
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    summary, _ = verify_primary_scan(
        root=root,
        external_root=external_root,
        database_path=run_dir / "primary_scan.sqlite",
        expected_run_key=run_key,
        write_summary=False,
    )
    _atomic_json(summary_path, summary)
    verified, _ = verify_primary_scan(root=root, external_root=external_root)
    connection = sqlite3.connect(run_dir / "primary_scan.sqlite")
    _progress(
        run_dir, connection=connection, contract=contract, status="COMPLETE"
    )
    connection.close()
    return verified, run_dir


def run_primary_scan(
    *,
    root: Path = ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    """Run with a process-wide advisory lock for this immutable run key."""

    import fcntl

    resolved_root = root.resolve()
    resolved_external = external_root.resolve()
    contract = load_scan_contract(root=resolved_root)
    runtime = load_runtime_contract(
        root=resolved_root, require_current=True, device=device
    )
    run_key = _run_key(
        contract,
        environment_digest=runtime["runtime_environment"]["environment_digest"],
    )
    run_dir = resolved_external / f"primary_scan_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = run_dir / "run.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ContractError(
                "another O3a primary-scan process already owns this run key"
            ) from exc
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()) + "\n")
        lock.flush()
        try:
            return _run_primary_scan_locked(
                root=resolved_root,
                raw_root=raw_root,
                external_root=resolved_external,
                device=device,
            )
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def verify_primary_scan(
    *,
    root: Path = ROOT,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    database_path: Path | None = None,
    expected_run_key: str | None = None,
    write_summary: bool = True,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    external_root = external_root.resolve()
    contract = load_scan_contract(root=root)
    runtime = load_runtime_contract(root=root, require_current=True)
    environment_digest = runtime["runtime_environment"]["environment_digest"]
    run_key = _run_key(contract, environment_digest=environment_digest)
    if expected_run_key is not None and run_key != expected_run_key:
        raise ContractError("O3a primary-scan run key changed")
    run_dir = external_root / f"primary_scan_{run_key}"
    if (run_dir / "failure.json").is_file():
        raise ContractError("O3a primary-scan failure artifact is present")
    path = database_path or (run_dir / "primary_scan.sqlite")
    if not path.is_file():
        raise ContractError("O3a primary-scan database is absent")
    preflight = load_primary_scan_preflight(
        contract=contract,
        run_dir=run_dir,
        run_key=run_key,
        environment_digest=environment_digest,
    )
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    identity = _run_identity(
        contract,
        run_key=run_key,
        environment_digest=environment_digest,
        preflight_digest=preflight["preflight_digest"],
    )
    observed = connection.execute(
        "SELECT value FROM metadata WHERE key='run_identity'"
    ).fetchone()
    if observed is None or json.loads(observed[0]) != identity:
        connection.close()
        raise ContractError("O3a primary-scan database identity mismatch")
    thresholds = contract["thresholds"]["values"]
    token_shape = [int(value) for value in preflight["token_shape"]]
    if len(token_shape) != 3 or token_shape[0] != 1:
        raise ContractError("O3a primary-scan preflight token shape changed")
    patch_token_count = token_shape[1]
    embedding_dimension = token_shape[2]
    counts = Counter()
    candidate_counts = Counter()
    rows = iter(
        connection.execute(
            "SELECT detector,gps_start,primary_score,score_float32_hex,"
            "is_candidate,identity_digest,mil_vector,top_k_indices,"
            "patch_anomaly_scores FROM windows ORDER BY detector,gps_start"
        )
    )
    universe = load_identity_universes(root=root)
    for detector, gps in iter_role_identities(
        universe, "primary_scan_geometric_universe"
    ):
        actual = next(rows, None)
        if actual is None:
            connection.close()
            raise ContractError("O3a primary-scan database is truncated")
        (
            actual_detector,
            actual_gps,
            score,
            score_hex,
            is_candidate,
            identity_digest,
            mil,
            topk,
            patch,
        ) = actual
        score = float(score)
        candidate = score > float(thresholds[detector])
        if (
            (actual_detector, int(actual_gps)) != (detector, int(gps))
            or not np.isfinite(score)
            or score_hex != np.float32(score).tobytes().hex()
            or bool(is_candidate) != candidate
            or identity_digest != _identity_digest(detector, int(gps))
            or (candidate and (mil is None or topk is None or patch is None))
            or (not candidate and (mil is not None or topk is not None or patch is not None))
        ):
            connection.close()
            raise ContractError("O3a primary-scan row contract mismatch")
        if candidate:
            if (
                len(mil) != embedding_dimension * 4
                or len(topk) != int(contract["representation"]["top_k"]) * 4
                or len(patch) != patch_token_count * 4
            ):
                connection.close()
                raise ContractError("O3a primary candidate tensor shape changed")
            candidate_counts[detector] += 1
        counts[detector] += 1
    if next(rows, None) is not None:
        connection.close()
        raise ContractError("O3a primary-scan database has extra rows")
    frame_count = int(
        connection.execute("SELECT COUNT(*) FROM raw_frames").fetchone()[0]
    )
    expected_frame_count = int(
        contract["population"]["required_source_frames"]["total_count"]
    )
    connection.close()
    if dict(counts) != contract["population"]["counts_by_detector"]:
        raise ContractError("O3a primary-scan final cardinality changed")
    if frame_count != expected_frame_count:
        raise ContractError("O3a primary-scan raw-frame ledger is incomplete")
    transient_root = run_dir / str(
        contract["storage"]["transient_raw_subdirectory"]
    )
    retained_transient_files = (
        [path for path in transient_root.rglob("*") if path.is_file()]
        if transient_root.is_dir()
        else []
    )
    if retained_transient_files:
        raise ContractError("O3a primary-scan transient raw cache is not empty")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_O3A_PRIMARY_SCAN",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "threshold_artifact_digest": contract["parents"][
            "threshold_artifact"
        ]["artifact_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "window_counts": dict(counts),
        "window_total": sum(counts.values()),
        "candidate_counts": {
            detector: int(candidate_counts[detector])
            for detector in ("H1", "L1")
        },
        "candidate_total": sum(candidate_counts.values()),
        "raw_frame_count": frame_count,
        "database": {
            "filename": path.name,
            "sha256": file_sha256(path),
            "size_bytes": path.stat().st_size,
        },
        "invalid_or_silent_drop_count": 0,
        "ci_asymmetry_annotation": contract["ci_asymmetry_annotation"],
        "scientific_boundary": contract["scientific_boundary"],
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    if write_summary:
        saved = _read_json(run_dir / "primary_scan_summary.json")
        if saved != summary:
            raise ContractError("O3a primary-scan summary is stale")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "DEFAULT_RAW_ROOT",
    "FrameGroupReader",
    "InfrastructureError",
    "build_scan_contract",
    "clear_infrastructure_failure",
    "group_identities_by_target_frame",
    "load_primary_scan_preflight",
    "load_scan_contract",
    "preflight_primary_scan",
    "run_primary_scan",
    "validate_scan_contract",
    "verify_primary_scan",
    "write_scan_contract",
]
