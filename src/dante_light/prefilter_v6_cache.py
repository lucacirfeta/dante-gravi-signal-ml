"""Resumable raw-window cache for the frozen DANTE-Light v6 Phase B."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_partitions import file_sha256, load_partition_contract
from src.dante_light.prefilter_v6_phase_b import load_phase_b_contract


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOWNLOADS = ROOT / "config" / "dante_light_prefilter_v6_download_manifest.jsonl"
DEFAULT_PARTITION_HEADER = ROOT / "config" / "dante_light_prefilter_v6_partitions.json"


def _repository_reference_matches(
    root: Path, path: Path, expected_sha256: str
) -> bool:
    """Accept the worktree bytes or the canonical tracked Git blob.

    ``repository_reference`` deliberately records the canonical blob for an
    unchanged tracked file so references remain portable across checkout line
    endings.  Requiring only the worktree-byte digest here would reject that
    valid reference on Windows.
    """
    if not path.is_file():
        return False
    candidates = {file_sha256(path)}
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        blob = subprocess.check_output(
            ["git", "show", f"HEAD:{relative}"],
            cwd=root,
            stderr=subprocess.DEVNULL,
        )
        candidates.add(hashlib.sha256(blob).hexdigest())
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return expected_sha256 in candidates


def load_phase_b_downloads(
    *,
    root: Path = ROOT,
    downloads_path: Path = DEFAULT_DOWNLOADS,
    header_path: Path = DEFAULT_PARTITION_HEADER,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contract = load_phase_b_contract(root=root)
    partition_contract = load_partition_contract(root=root)
    header = json.loads(header_path.read_text(encoding="utf-8"))
    if header["contract_digest"] != partition_contract["contract_digest"]:
        raise ContractError("v6 partition header uses the wrong partition contract")
    if Path(header["download_reference"]["path"]) != downloads_path.relative_to(root):
        raise ContractError("v6 partition header points to a different download manifest")
    if file_sha256(downloads_path) != header["download_reference"]["sha256"]:
        raise ContractError("v6 download manifest file hash mismatch")
    rows = [
        json.loads(line)
        for line in downloads_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    phase_b = [row for row in rows if row["partitions"] == ["phase_b"]]
    if not phase_b or any(row["partitions"] != ["phase_b"] for row in phase_b):
        raise ContractError("v6 Phase-B download selection is empty or contaminated")
    identities = []
    for row in phase_b:
        if len(row["fetch_intervals"]) != int(row["missing_padded_window_count"]):
            raise ContractError("v6 Phase-B download interval count mismatch")
        for interval in row["fetch_intervals"]:
            start = float(interval["gps_start"])
            end = float(interval["gps_end"])
            if not math.isfinite(start) or not math.isfinite(end) or end - start != 40.0:
                raise ContractError("v6 Phase-B fetch interval is not a finite padded 40 s window")
            identities.append(
                {
                    "detector": row["detector"],
                    "block_index": int(row["block_index"]),
                    "gps_start": start,
                    "gps_end": end,
                }
            )
    if len(identities) != len(
        {(row["detector"], row["gps_start"], row["gps_end"]) for row in identities}
    ):
        raise ContractError("v6 Phase-B download intervals are duplicated")
    identities.sort(key=lambda row: (row["detector"], row["block_index"], row["gps_start"]))
    return contract, identities


def cache_path(cache_root: Path, identity: Mapping[str, Any]) -> Path:
    start = int(float(identity["gps_start"]))
    end = int(float(identity["gps_end"]))
    return (
        cache_root
        / str(identity["detector"])
        / str(int(identity["block_index"]))
        / f"{identity['detector']}_{start}_{end}.hdf5"
    )


def _timeseries_record(path: Path, identity: Mapping[str, Any], *, sample_rate_hz: int) -> dict[str, Any]:
    from gwpy.timeseries import TimeSeries

    strain = TimeSeries.read(path)
    start = float(identity["gps_start"])
    end = float(identity["gps_end"])
    tolerance = 1.0 / float(sample_rate_hz)
    actual_start = float(strain.t0.value)
    actual_end = actual_start + float(strain.duration.value)
    if (
        int(round(float(strain.sample_rate.value))) != sample_rate_hz
        or actual_start > start + tolerance
        or actual_end < end - tolerance
        or not np.isfinite(strain.value).all()
    ):
        raise ContractError("cached v6 Phase-B strain has invalid coverage or samples")
    cropped = strain.crop(start, end)
    values = np.ascontiguousarray(cropped.value)
    if len(values) != int(round((end - start) * sample_rate_hz)):
        raise ContractError("cached v6 Phase-B strain has the wrong sample count")
    return {
        "detector": identity["detector"],
        "block_index": int(identity["block_index"]),
        "gps_start": start,
        "gps_end": end,
        "sample_rate_hz": sample_rate_hz,
        "sample_count": len(values),
        "relative_path": path.as_posix(),
        "file_sha256": file_sha256(path),
        "strain_values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
    }


def _archive_invalid(path: Path, *, cache_root: Path) -> None:
    resolved_root = cache_root.resolve()
    resolved_path = path.resolve()
    if resolved_root not in resolved_path.parents:
        raise ContractError("refusing to archive a cache file outside the v6 root")
    archive = cache_root / "archive" / "invalid"
    archive.mkdir(parents=True, exist_ok=True)
    suffix = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    destination = archive / f"{path.name}.{suffix}.invalid"
    if destination.exists():
        destination = archive / f"{path.name}.{suffix}.{time.time_ns()}.invalid"
    path.replace(destination)


def ensure_interval(
    *,
    identity: Mapping[str, Any],
    cache_root: Path,
    sample_rate_hz: int,
    fetch: Callable[[str, float, float, int], object],
    retries: int,
) -> dict[str, Any]:
    path = cache_path(cache_root, identity)
    if path.is_file():
        try:
            record = _timeseries_record(path, identity, sample_rate_hz=sample_rate_hz)
            record["source"] = "existing_v6_cache"
            record["record_digest"] = canonical_json_sha256(record)
            return record
        except Exception:
            _archive_invalid(path, cache_root=cache_root)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            strain = fetch(
                str(identity["detector"]),
                float(identity["gps_start"]),
                float(identity["gps_end"]),
                sample_rate_hz,
            )
            if int(round(float(strain.sample_rate.value))) != sample_rate_hz:
                strain = strain.resample(sample_rate_hz)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp.hdf5")
            strain.write(temporary, format="hdf5", path="strain")
            os.replace(temporary, path)
            record = _timeseries_record(path, identity, sample_rate_hz=sample_rate_hz)
            record["source"] = "gwosc_open_data"
            record["record_digest"] = canonical_json_sha256(record)
            return record
        except Exception as exc:  # network and HDF5 failures are recorded uniformly
            last_error = exc
            temporary = path.with_suffix(".tmp.hdf5")
            if temporary.exists():
                temporary.unlink()
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 30))
    raise ContractError(
        f"v6 Phase-B fetch failed for {identity['detector']} "
        f"[{identity['gps_start']},{identity['gps_end']}]: {last_error}"
    )


def default_fetch(detector: str, start: float, end: float, sample_rate_hz: int) -> object:
    from gwpy.timeseries import TimeSeries

    return TimeSeries.fetch_open_data(
        detector,
        start,
        end,
        sample_rate=sample_rate_hz,
        cache=True,
        verbose=False,
    )


def _cache_block_group(
    identities: Sequence[Mapping[str, Any]],
    *,
    cache_root: Path,
    sample_rate_hz: int,
    fetch: Callable[[str, float, float, int], object],
    retries: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch one detector/block sequentially to avoid shared GWOSC-cache races."""
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for identity in identities:
        try:
            records.append(
                ensure_interval(
                    identity=identity,
                    cache_root=cache_root,
                    sample_rate_hz=sample_rate_hz,
                    fetch=fetch,
                    retries=retries,
                )
            )
        except Exception as exc:
            failures.append(
                {
                    **identity,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    return records, failures


def build_phase_b_cache(
    *,
    root: Path,
    cache_root: Path,
    artifact_path: Path,
    implementation_references: Mapping[str, Mapping[str, str]],
    workers: int,
    retries: int,
    fetch: Callable[[str, float, float, int], object] = default_fetch,
    limit: int | None = None,
) -> dict[str, Any]:
    if workers < 1 or workers > 8 or retries < 1 or retries > 5:
        raise ContractError("v6 cache workers/retries are outside the frozen safety range")
    contract, identities = load_phase_b_downloads(root=root)
    expected_interval_count = len(identities)
    if limit is not None:
        if limit < 1:
            raise ContractError("v6 cache smoke limit must be positive")
        identities = identities[:limit]
    for name, reference in implementation_references.items():
        path = root / reference["path"]
        if not _repository_reference_matches(root, path, str(reference["sha256"])):
            raise ContractError(f"v6 cache implementation reference mismatch: {name}")
    header = json.loads(DEFAULT_PARTITION_HEADER.read_text(encoding="utf-8"))
    run_key = canonical_json_sha256(
        {
            "phase_b_contract_digest": contract["contract_digest"],
            "partition_manifest_digest": header["manifest_digest"],
            "download_manifest_sha256": file_sha256(DEFAULT_DOWNLOADS),
            "implementation_references": implementation_references,
            "sample_rate_hz": 4096,
        }
    )
    run_dir = cache_root / f"raw_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for identity in identities:
        grouped.setdefault(
            (str(identity["detector"]), int(identity["block_index"])), []
        ).append(identity)
    groups = [
        sorted(values, key=lambda row: float(row["gps_start"]))
        for _key, values in sorted(grouped.items())
    ]
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _cache_block_group,
                group,
                cache_root=run_dir,
                sample_rate_hz=4096,
                fetch=fetch,
                retries=retries,
            ): group
            for group in groups
        }
        for future in as_completed(futures):
            try:
                group_records, group_failures = future.result()
                failures.extend(group_failures)
                for record in group_records:
                    path = Path(record["relative_path"])
                    record["relative_path"] = path.relative_to(run_dir).as_posix()
                    record["record_digest"] = canonical_json_sha256(
                        {key: value for key, value in record.items() if key != "record_digest"}
                    )
                    records.append(record)
            except Exception as exc:
                group = futures[future]
                for identity in group:
                    failures.append(
                        {
                            **identity,
                            "exception_type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
    records.sort(key=lambda row: (row["detector"], row["block_index"], row["gps_start"]))
    failures.sort(key=lambda row: (row["detector"], row["block_index"], row["gps_start"]))
    ledger_path = run_dir / "cache_manifest_v6.jsonl"
    ledger_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in records),
        encoding="utf-8",
        newline="\n",
    )
    status = "SMOKE_ONLY" if limit is not None and not failures else (
        "NOT_READY_INCOMPLETE_CACHE" if failures else "COMPLETE"
    )
    body = {
        "schema_version": 1,
        "status": status,
        "run_key": run_key,
        "phase_b_contract_digest": contract["contract_digest"],
        "partition_manifest_digest": header["manifest_digest"],
        "download_manifest_sha256": file_sha256(DEFAULT_DOWNLOADS),
        "expected_interval_count": expected_interval_count,
        "processed_interval_count": len(identities),
        "cached_interval_count": len(records),
        "failure_count": len(failures),
        "failures": failures,
        "cache_manifest": {
            "path": ledger_path.name,
            "sha256": file_sha256(ledger_path),
            "records_digest": canonical_json_sha256(records),
        },
        "cache_location": {
            "environment_alias": "DANTE_V6_RAW_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
        },
        "implementation_references": dict(implementation_references),
        "phase_c_rows_accessed": [],
        "phase_d_rows_accessed": [],
        "o4b_rows_accessed": [],
        "teacher_scores_accessed": [],
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    summary_path = run_dir / "cache_summary_v6.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, artifact_path)
    if failures:
        raise ContractError(f"v6 Phase-B raw cache incomplete: {len(failures)} failures")
    return summary
