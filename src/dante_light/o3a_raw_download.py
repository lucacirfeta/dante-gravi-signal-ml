"""Resumable downloader for the frozen O3a raw acquisition plan."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Callable, Mapping, Sequence

import h5py
import requests

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import ROOT
from src.dante_light.o3a_raw_acquisition import (
    ACQUISITION_REL,
    SAMPLE_RATE_HZ,
    TARGET_WINDOWS_ROOT,
    load_acquisition_plan,
)


IMPLEMENTATION_REL = "src/dante_light/o3a_raw_download.py"
ENTRYPOINT_REL = "scripts/run_dante_o3a_raw_download.py"
SCHEMA_VERSION = 1
DEFAULT_WORKERS = 4
DEFAULT_RETRIES = 5
DEFAULT_RESERVE_BYTES = 16 * 1024**3
CHUNK_BYTES = 8 * 1024**2

HeadFetcher = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _source_hashes(root: Path) -> dict[str, str]:
    return {
        IMPLEMENTATION_REL: file_sha256(root / IMPLEMENTATION_REL),
        ENTRYPOINT_REL: file_sha256(root / ENTRYPOINT_REL),
    }


def _all_frames(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for detector in plan["detectors"]:
        for item in plan["detector_plans"][detector]["source_frames"]:
            rows.append({"detector": detector, **dict(item)})
    rows.sort(key=lambda row: (row["detector"], row["gps_start"], row["filename"]))
    if len(rows) != len(
        {(row["detector"], row["filename"]) for row in rows}
    ):
        raise ContractError("O3a raw acquisition frames are duplicated")
    return rows


def _run_key(plan: Mapping[str, Any], root: Path) -> str:
    return canonical_json_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "acquisition_digest": plan["acquisition_digest"],
            "acquisition_file_sha256": file_sha256(root / ACQUISITION_REL),
            "implementation_sources": _source_hashes(root),
        }
    )


def _safe_target(raw_root: Path, relative_path: str) -> Path:
    relative = Path(relative_path)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ContractError(f"unsafe O3a raw target path: {relative_path!r}")
    root = raw_root.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise ContractError(f"O3a raw target escapes root: {relative_path!r}")
    return target


def _existing_parent(path: Path) -> Path:
    current = path.resolve()
    while not current.exists():
        if current.parent == current:
            raise ContractError(f"no existing parent for raw root: {path}")
        current = current.parent
    return current


def _default_head(item: Mapping[str, Any]) -> Mapping[str, Any]:
    last_error: Exception | None = None
    for attempt in range(DEFAULT_RETRIES):
        try:
            response = requests.head(
                str(item["url"]), allow_redirects=True, timeout=(15, 90)
            )
            response.raise_for_status()
            length = int(response.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ContractError(f"missing Content-Length for {item['url']}")
            return {
                "content_length_bytes": length,
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "resolved_url": response.url,
            }
        except Exception as exc:
            last_error = exc
            if attempt + 1 < DEFAULT_RETRIES:
                time.sleep(min(2**attempt, 15))
    raise ContractError(f"HEAD failed for {item['url']}: {last_error}")


def build_preflight(
    *,
    root: Path = ROOT,
    raw_root: Path = Path(TARGET_WINDOWS_ROOT),
    workers: int = DEFAULT_WORKERS,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    head_fetcher: HeadFetcher = _default_head,
) -> dict[str, Any]:
    if workers < 1 or workers > 16:
        raise ContractError("O3a HEAD worker count must be in [1,16]")
    if reserve_bytes < 0:
        raise ContractError("O3a disk reserve cannot be negative")
    plan = load_acquisition_plan(root=root)
    frames = _all_frames(plan)
    metadata: dict[tuple[str, str], dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(head_fetcher, item): item for item in frames}
        for future in as_completed(futures):
            item = futures[future]
            key = (str(item["detector"]), str(item["filename"]))
            try:
                value = dict(future.result())
                length = int(value["content_length_bytes"])
                if length <= 0:
                    raise ContractError("non-positive content length")
                metadata[key] = {
                    "detector": key[0],
                    "filename": key[1],
                    "content_length_bytes": length,
                    "etag": value.get("etag"),
                    "last_modified": value.get("last_modified"),
                    "resolved_url": str(value.get("resolved_url", item["url"])),
                }
            except Exception as exc:
                failures.append(
                    {
                        "detector": key[0],
                        "filename": key[1],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
    if failures:
        raise ContractError(f"O3a raw HEAD preflight failed: {failures[:3]}")
    ordered = [metadata[(row["detector"], row["filename"])] for row in frames]
    expected_bytes = sum(int(row["content_length_bytes"]) for row in ordered)
    free_bytes = shutil.disk_usage(_existing_parent(raw_root)).free
    required_free_bytes = expected_bytes + reserve_bytes
    if free_bytes < required_free_bytes:
        raise ContractError(
            "O3a raw download does not fit: "
            f"free={free_bytes}, required={required_free_bytes}"
        )
    run_key = _run_key(plan, root)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_O3A_RAW_DOWNLOAD_PREFLIGHT",
        "run": "O3A",
        "run_key": run_key,
        "acquisition_digest": plan["acquisition_digest"],
        "acquisition_file_sha256": file_sha256(root / ACQUISITION_REL),
        "implementation_sources": _source_hashes(root),
        "raw_root": str(raw_root),
        "workers": workers,
        "reserve_bytes": reserve_bytes,
        "expected_file_count": len(ordered),
        "expected_download_bytes": expected_bytes,
        "free_bytes_at_preflight": free_bytes,
        "required_free_bytes": required_free_bytes,
        "source_metadata": ordered,
        "execution_boundary": {
            "head_requests_only": True,
            "hdf5_bytes_downloaded": 0,
            "strain_data_accessed": False,
            "scoring_executed": False,
        },
    }
    return {**body, "preflight_digest": canonical_json_sha256(body)}


def write_preflight(
    *,
    root: Path = ROOT,
    raw_root: Path = Path(TARGET_WINDOWS_ROOT),
    workers: int = DEFAULT_WORKERS,
    reserve_bytes: int = DEFAULT_RESERVE_BYTES,
    head_fetcher: HeadFetcher = _default_head,
) -> tuple[dict[str, Any], Path]:
    plan = load_acquisition_plan(root=root)
    run_key = _run_key(plan, root)
    run_dir = raw_root / "runs" / f"raw_download_{run_key}"
    path = run_dir / "preflight.json"
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing_body = {
            key: value
            for key, value in existing.items()
            if key != "preflight_digest"
        }
        if existing.get("preflight_digest") != canonical_json_sha256(existing_body):
            raise ContractError("existing O3a raw preflight digest mismatch")
        expected_identity = {
            "run_key": run_key,
            "acquisition_digest": plan["acquisition_digest"],
            "acquisition_file_sha256": file_sha256(root / ACQUISITION_REL),
            "implementation_sources": _source_hashes(root),
            "raw_root": str(raw_root),
            "workers": workers,
            "reserve_bytes": reserve_bytes,
        }
        observed_identity = {
            key: existing.get(key) for key in expected_identity
        }
        if observed_identity != expected_identity:
            raise ContractError("existing O3a raw preflight identity mismatch")
        if (
            existing.get("status") != "PASS_O3A_RAW_DOWNLOAD_PREFLIGHT"
            or int(existing.get("expected_file_count", -1))
            != len(_all_frames(plan))
        ):
            raise ContractError("existing O3a raw preflight is incomplete")
        return existing, path
    value = build_preflight(
        root=root,
        raw_root=raw_root,
        workers=workers,
        reserve_bytes=reserve_bytes,
        head_fetcher=head_fetcher,
    )
    _atomic_json(path, value)
    return value, path


def validate_hdf5_metadata(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    if not h5py.is_hdf5(path):
        raise ContractError(f"download is not HDF5: {path}")
    with h5py.File(path, "r") as handle:
        if "strain/Strain" not in handle:
            raise ContractError(f"GWOSC strain dataset is absent: {path}")
        dataset = handle["strain/Strain"]
        expected_samples = int(item["duration_s"]) * SAMPLE_RATE_HZ
        if dataset.ndim != 1 or int(dataset.shape[0]) != expected_samples:
            raise ContractError(f"GWOSC strain shape mismatch: {path}")
        spacing = float(dataset.attrs.get("Xspacing", 0.0))
        if abs(spacing - 1.0 / SAMPLE_RATE_HZ) > 1e-15:
            raise ContractError(f"GWOSC strain sample spacing mismatch: {path}")
    return {
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "sample_count": expected_samples,
        "metadata_only_validation": True,
    }


def build_raw_manifest_rows(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for record in sorted(
        records, key=lambda row: (row["detector"], row["gps_start"])
    ):
        digest = str(record["sha256"])
        rows.append(
            {
                "copy_count": 1,
                "detector": str(record["detector"]),
                "duration_s": int(record["duration_s"]),
                "gps_end": int(record["gps_end"]),
                "gps_start": int(record["gps_start"]),
                "physical_copies": [
                    {
                        "relative_path": str(record["target_relative_path"]),
                        "sha256": digest,
                        "size_bytes": int(record["size_bytes"]),
                    }
                ],
                "sha256": digest,
            }
        )
    return rows


def _record_base(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in item.items()
        if key not in {"content_length_bytes", "content_sha256", "download_status"}
    }


def _canonical_verified_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Remove attempt-local transport details from immutable verification evidence."""
    return {key: value for key, value in record.items() if key != "source"}


class _Progress:
    def __init__(self, path: Path, expected_files: int, expected_bytes: int):
        self.path = path
        self.expected_files = expected_files
        self.expected_bytes = expected_bytes
        self.network_bytes = 0
        self.completed_files = 0
        self.failed_files = 0
        self._lock = threading.Lock()
        self._last_write = 0.0

    def add_bytes(self, count: int) -> None:
        with self._lock:
            self.network_bytes += count
            now = time.monotonic()
            if now - self._last_write >= 2.0:
                self._write("RUNNING")
                self._last_write = now

    def finish_file(self, *, failed: bool = False) -> None:
        with self._lock:
            if failed:
                self.failed_files += 1
            else:
                self.completed_files += 1
            self._write("RUNNING")

    def finalize(self, status: str) -> None:
        with self._lock:
            self._write(status)

    def _write(self, status: str) -> None:
        fraction = (
            (self.completed_files + self.failed_files) / self.expected_files
            if self.expected_files
            else 0.0
        )
        _atomic_json(
            self.path,
            {
                "status": status,
                "expected_files": self.expected_files,
                "completed_files": self.completed_files,
                "failed_files": self.failed_files,
                "expected_bytes": self.expected_bytes,
                "network_bytes_this_run": self.network_bytes,
                "processed_file_fraction": fraction,
                "verified_file_fraction": (
                    self.completed_files / self.expected_files
                    if self.expected_files
                    else 0.0
                ),
            },
        )


def _download_one(
    *,
    item: Mapping[str, Any],
    source: Mapping[str, Any],
    raw_root: Path,
    retries: int,
    progress: _Progress,
) -> dict[str, Any]:
    target = _safe_target(raw_root, str(item["target_relative_path"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_size = int(source["content_length_bytes"])
    if target.exists():
        if not target.is_file() or target.stat().st_size != expected_size:
            raise ContractError(f"divergent existing O3a raw target: {target}")
        metadata = validate_hdf5_metadata(target, item)
        return {
            **_record_base(item),
            **metadata,
            "size_bytes": expected_size,
            "sha256": file_sha256(target),
            "source": "VERIFIED_EXISTING_FINAL",
        }
    partial = target.with_suffix(target.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            existing = partial.stat().st_size if partial.is_file() else 0
            if existing > expected_size:
                raise ContractError(f"partial file exceeds source length: {partial}")
            if existing == expected_size:
                metadata = validate_hdf5_metadata(partial, item)
                digest = file_sha256(partial)
                os.replace(partial, target)
                return {
                    **_record_base(item),
                    **metadata,
                    "size_bytes": expected_size,
                    "sha256": digest,
                    "source": "VERIFIED_COMPLETE_PARTIAL",
                }
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            with requests.get(
                str(item["url"]),
                headers=headers,
                stream=True,
                timeout=(20, 180),
            ) as response:
                response.raise_for_status()
                append = existing > 0 and response.status_code == 206
                if existing > 0 and response.status_code not in {200, 206}:
                    raise ContractError(
                        f"invalid range response {response.status_code}: {item['url']}"
                    )
                if append:
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {existing}-"):
                        raise ContractError(
                            f"invalid Content-Range for {item['filename']}: "
                            f"{content_range!r}"
                        )
                mode = "ab" if append else "wb"
                with partial.open(mode) as stream:
                    for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
                        if chunk:
                            stream.write(chunk)
                            progress.add_bytes(len(chunk))
            if partial.stat().st_size != expected_size:
                raise ContractError(
                    f"download size mismatch for {item['filename']}: "
                    f"{partial.stat().st_size} != {expected_size}"
                )
            metadata = validate_hdf5_metadata(partial, item)
            digest = file_sha256(partial)
            os.replace(partial, target)
            return {
                **_record_base(item),
                **metadata,
                "size_bytes": expected_size,
                "sha256": digest,
                "source": "GWOSC_HTTPS",
            }
        except Exception as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 30))
    raise ContractError(f"download failed for {item['filename']}: {last_error}")


def execute_download(
    *,
    root: Path = ROOT,
    raw_root: Path = Path(TARGET_WINDOWS_ROOT),
    workers: int = DEFAULT_WORKERS,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any]:
    if workers < 1 or workers > 8 or retries < 1 or retries > 8:
        raise ContractError("O3a download workers/retries outside safety range")
    plan = load_acquisition_plan(root=root)
    run_key = _run_key(plan, root)
    run_dir = raw_root / "runs" / f"raw_download_{run_key}"
    preflight_path = run_dir / "preflight.json"
    if not preflight_path.is_file():
        raise ContractError("O3a raw preflight is absent")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if (
        preflight.get("run_key") != run_key
        or preflight.get("preflight_digest")
        != canonical_json_sha256(
            {key: value for key, value in preflight.items() if key != "preflight_digest"}
        )
    ):
        raise ContractError("O3a raw preflight provenance mismatch")
    frames = _all_frames(plan)
    sources = {
        (row["detector"], row["filename"]): row
        for row in preflight["source_metadata"]
    }
    progress = _Progress(
        run_dir / "progress.json",
        len(frames),
        int(preflight["expected_download_bytes"]),
    )
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    ledger_path = run_dir / "verified_files.jsonl"
    failures_path = run_dir / "failures.json"
    ledger_lock = threading.Lock()

    def persist(record: dict[str, Any]) -> None:
        with ledger_lock:
            records.append(_canonical_verified_record(record))
            records.sort(key=lambda row: (row["detector"], row["gps_start"]))
            _atomic_jsonl(ledger_path, records)

    progress.finalize("RUNNING")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _download_one,
                item=item,
                source=sources[(item["detector"], item["filename"])],
                raw_root=raw_root,
                retries=retries,
                progress=progress,
            ): item
            for item in frames
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                persist(future.result())
                progress.finish_file()
            except Exception as exc:
                failure = {
                    "detector": item["detector"],
                    "filename": item["filename"],
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                with ledger_lock:
                    failures.append(failure)
                    failures.sort(
                        key=lambda row: (row["detector"], row["filename"])
                    )
                    _atomic_json(
                        failures_path,
                        {"status": "RUNNING_WITH_FAILURES", "failures": failures},
                    )
                progress.finish_file(failed=True)
    status = "PASS_VERIFIED_RAW_DOWNLOAD" if not failures else "FAILED_INCOMPLETE"
    manifest_path = raw_root / "manifests" / f"o3a_raw_{run_key}.jsonl"
    if not failures:
        _atomic_jsonl(manifest_path, build_raw_manifest_rows(records))
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run_key": run_key,
        "acquisition_digest": plan["acquisition_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "expected_file_count": len(frames),
        "verified_file_count": len(records),
        "failure_count": len(failures),
        "failures": sorted(
            failures, key=lambda row: (row["detector"], row["filename"])
        ),
        "verified_ledger": {
            "path": str(ledger_path),
            "sha256": file_sha256(ledger_path),
        },
        "raw_manifest": (
            {"path": str(manifest_path), "sha256": file_sha256(manifest_path)}
            if not failures
            else None
        ),
        "strain_values_inspected": False,
        "scoring_executed": False,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "summary.json", summary)
    progress.finalize(status)
    if failures:
        raise ContractError(f"O3a raw download incomplete: {len(failures)} failures")
    return summary


__all__ = [
    "build_preflight",
    "build_raw_manifest_rows",
    "execute_download",
    "file_sha256",
    "validate_hdf5_metadata",
    "write_preflight",
]
