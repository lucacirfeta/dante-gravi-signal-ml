"""Resumable, fail-closed cache for O4a v1 parity windows absent locally."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_v1_parity import ROOT, validate_parity_freeze
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path


DEFAULT_CACHE_ROOT = Path("E:/dante_cache/dante_light/o4a_v1_comparison")
DEFAULT_RAW_ROOT = Path("E:/o4a")
CONTRACT_PATH = ROOT / "config/dante_light_o4a_v1_parity_contract.json"
HEADER_PATH = ROOT / "config/dante_light_o4a_v1_parity_manifest.json"
COMPACT_ARTIFACT = ROOT / "artifacts/dante_light/o4a_v1_parity/raw_cache_summary.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_frozen_missing(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    contract = _read_json(root / CONTRACT_PATH.relative_to(ROOT))
    header = _read_json(root / HEADER_PATH.relative_to(ROOT))
    entries = _read_jsonl(root / header["entries_path"])
    missing = _read_jsonl(root / header["missing_path"])
    validate_parity_freeze(contract, header, entries, missing, root=root)
    return contract, header, missing


def _cache_path(cache_root: Path, row: Mapping[str, Any]) -> Path:
    relative = Path(str(row["cache_target"]["relative_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError("invalid parity cache relative path")
    path = (cache_root / relative).resolve()
    if cache_root.resolve() not in path.parents:
        raise ContractError("parity cache path escapes its root")
    return path


def _validate_series(path: Path, row: Mapping[str, Any], sample_rate_hz: int) -> dict[str, Any]:
    from gwpy.timeseries import TimeSeries

    series = TimeSeries.read(path)
    start, end = map(float, row["required_padded_interval_gps"])
    tolerance = 1.0 / sample_rate_hz
    actual_start = float(series.t0.value)
    actual_end = actual_start + float(series.duration.value)
    if (
        int(round(float(series.sample_rate.value))) != sample_rate_hz
        or actual_start > start + tolerance
        or actual_end < end - tolerance
        or not np.isfinite(series.value).all()
    ):
        raise ContractError("cached parity strain has invalid coverage, rate, or samples")
    cropped = series.crop(start, end)
    values = np.ascontiguousarray(cropped.value)
    expected_samples = int(round((end - start) * sample_rate_hz))
    if values.size != expected_samples:
        raise ContractError("cached parity strain has the wrong sample count")
    return {
        "schema_version": 1,
        "case_id": row["case_id"],
        "window_id": row["window"]["window_id"],
        "detector": row["window"]["detector"],
        "required_padded_interval_gps": [start, end],
        "sample_rate_hz": sample_rate_hz,
        "sample_count": int(values.size),
        "cache_relative_path": row["cache_target"]["relative_path"],
        "file_sha256": sha256_path(path),
        "strain_values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "frozen_cbc_cat1": row["data_quality"]["frozen_cbc_cat1"],
        "hardware_injection_overlap": row["data_quality"]["hardware_injection_overlap"],
    }


def _archive_invalid(path: Path, cache_root: Path) -> None:
    resolved = path.resolve()
    if cache_root.resolve() not in resolved.parents:
        raise ContractError("refusing to archive outside the parity cache")
    archive = cache_root / "archive/invalid"
    archive.mkdir(parents=True, exist_ok=True)
    suffix = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    destination = archive / f"{path.name}.{suffix}.invalid"
    if destination.exists():
        destination = archive / f"{path.name}.{suffix}.{time.time_ns()}.invalid"
    path.replace(destination)


def default_fetch(detector: str, start: float, end: float, sample_rate_hz: int) -> object:
    from gwpy.timeseries import TimeSeries

    return TimeSeries.fetch_open_data(
        detector, start, end, sample_rate=sample_rate_hz, cache=True, verbose=False,
    )


def _stitch_local(
    row: Mapping[str, Any], *, raw_root: Path, sample_rate_hz: int,
) -> object | None:
    stitch = row["local_stitch"]
    if not stitch["complete_padded_coverage"]:
        return None
    from gwpy.timeseries import TimeSeries, TimeSeriesList

    paths = []
    for component in stitch["components"]:
        relative = Path(str(component["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ContractError("invalid local-stitch component path")
        path = (raw_root / relative).resolve()
        if raw_root.resolve() not in path.parents:
            raise ContractError("local-stitch component escapes raw root")
        if not path.is_file():
            return None
        if sha256_path(path) != component["file_sha256"]:
            raise ContractError(f"local-stitch source hash mismatch: {relative.as_posix()}")
        paths.append(path)
    series = TimeSeriesList([TimeSeries.read(path) for path in paths]).join(gap="raise")
    start, end = map(float, row["required_padded_interval_gps"])
    cropped = series.crop(start, end)
    if int(round(float(cropped.sample_rate.value))) != sample_rate_hz:
        cropped = cropped.resample(sample_rate_hz)
    return cropped


def ensure_cached(
    row: Mapping[str, Any], *, cache_root: Path, sample_rate_hz: int,
    raw_root: Path, fetch: Callable[[str, float, float, int], object], retries: int,
) -> dict[str, Any]:
    path = _cache_path(cache_root, row)
    if path.is_file():
        try:
            record = _validate_series(path, row, sample_rate_hz)
            record_path = cache_root / "records" / f"{row['case_id']}.json"
            if record_path.is_file():
                stored = _read_json(record_path)
                stored_body = dict(stored)
                stored_digest = stored_body.pop("record_digest", None)
                if stored_digest != canonical_json_sha256(stored_body):
                    raise ContractError("existing parity cache record digest mismatch")
                for key, value in record.items():
                    if stored.get(key) != value:
                        raise ContractError(f"existing parity cache record drift: {key}")
                if stored.get("source") not in {"verified_local_raw_stitch", "gwosc_open_data"}:
                    raise ContractError("existing parity cache record has unknown origin")
                return stored
            raise ContractError("existing parity cache file lacks an origin record")
        except Exception:
            _archive_invalid(path, cache_root)
    last_error: Exception | None = None
    start, end = map(float, row["required_padded_interval_gps"])
    for attempt in range(retries):
        temporary = path.with_suffix(".tmp.hdf5")
        try:
            series = _stitch_local(row, raw_root=raw_root, sample_rate_hz=sample_rate_hz)
            source = "verified_local_raw_stitch"
            if series is None:
                series = fetch(str(row["window"]["detector"]), start, end, sample_rate_hz)
                source = "gwosc_open_data"
            if int(round(float(series.sample_rate.value))) != sample_rate_hz:
                series = series.resample(sample_rate_hz)
            path.parent.mkdir(parents=True, exist_ok=True)
            series.write(temporary, format="hdf5", path="strain")
            os.replace(temporary, path)
            record = _validate_series(path, row, sample_rate_hz)
            body = {**record, "source": source}
            return {**body, "record_digest": canonical_json_sha256(body)}
        except Exception as exc:
            last_error = exc
            if temporary.exists():
                temporary.unlink()
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 30))
    raise ContractError(
        f"parity fetch failed for {row['case_id']} after {retries} attempts: {last_error}"
    )


def _write_record(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def _cache_detector(
    rows: Sequence[Mapping[str, Any]], *, cache_root: Path, sample_rate_hz: int,
    raw_root: Path, fetch: Callable[[str, float, float, int], object], retries: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for row in rows:
        try:
            record = ensure_cached(
                row, cache_root=cache_root, sample_rate_hz=sample_rate_hz,
                raw_root=raw_root, fetch=fetch, retries=retries,
            )
            _write_record(cache_root / "records" / f"{row['case_id']}.json", record)
            records.append(record)
        except Exception as exc:
            failures.append({
                "case_id": row["case_id"],
                "detector": row["window"]["detector"],
                "exception_type": type(exc).__name__,
                "message": str(exc),
            })
    return records, failures


def build_cache(
    *, root: Path = ROOT, cache_root: Path = DEFAULT_CACHE_ROOT, workers: int = 2,
    raw_root: Path = DEFAULT_RAW_ROOT,
    retries: int = 3, fetch: Callable[[str, float, float, int], object] = default_fetch,
    limit: int | None = None,
) -> dict[str, Any]:
    if workers < 1 or workers > 2 or retries < 1 or retries > 5:
        raise ContractError("parity cache workers/retries outside the frozen safety range")
    contract, header, missing = load_frozen_missing(root)
    expected = len(missing)
    if limit is not None:
        if limit < 1:
            raise ContractError("parity cache smoke limit must be positive")
        missing = missing[:limit]
    run_key = canonical_json_sha256({
        "contract_digest": contract["contract_digest"],
        "manifest_digest": header["manifest_digest"],
        "missing_file_sha256": header["missing_file_sha256"],
        "cache_code": repository_reference(root, root / "src/dante_light/o4a_v1_parity_cache.py"),
    })
    groups: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    for row in missing:
        groups[str(row["window"]["detector"])].append(row)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    selected_groups = [rows for rows in groups.values() if rows]
    with ThreadPoolExecutor(max_workers=min(workers, len(selected_groups))) as pool:
        futures = [
            pool.submit(
                _cache_detector, rows, cache_root=cache_root,
                sample_rate_hz=int(contract["representation"]["sample_rate_hz"]),
                raw_root=raw_root, fetch=fetch, retries=retries,
            )
            for rows in selected_groups
        ]
        for future in as_completed(futures):
            group_records, group_failures = future.result()
            records.extend(group_records); failures.extend(group_failures)
    records.sort(key=lambda row: (row["detector"], row["required_padded_interval_gps"][0]))
    failures.sort(key=lambda row: (row["detector"], row["case_id"]))
    record_digests = [row["record_digest"] for row in records]
    body = {
        "schema_version": 1,
        "status": (
            "COMPLETE" if limit is None and not failures and len(records) == expected
            else "SMOKE_COMPLETE" if limit is not None and not failures and len(records) == len(missing)
            else "INCOMPLETE_FAIL_CLOSED"
        ),
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "manifest_digest": header["manifest_digest"],
        "logical_cache_root": "o4a_v1_comparison_cache",
        "expected_missing_count": expected,
        "attempted_count": len(missing),
        "completed_count": len(records),
        "failure_count": len(failures),
        "record_digest_aggregate": canonical_json_sha256(record_digests),
        "records": record_digests,
        "failures": failures,
        "implementation_references": {
            "cache": repository_reference(root, root / "src/dante_light/o4a_v1_parity_cache.py"),
            "freeze": repository_reference(root, root / "src/dante_light/o4a_v1_parity.py"),
        },
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    name = "summary.json" if limit is None else f"smoke_{limit}_summary.json"
    _write_record(cache_root / name, summary)
    if summary["status"] == "INCOMPLETE_FAIL_CLOSED":
        raise ContractError(f"parity raw cache incomplete: {len(records)}/{len(missing)}")
    return summary


def validate_cache(
    *, root: Path = ROOT, cache_root: Path = DEFAULT_CACHE_ROOT,
    require_complete: bool = True,
) -> dict[str, Any]:
    contract, header, missing = load_frozen_missing(root)
    summary = _read_json(cache_root / "summary.json")
    body = dict(summary); digest = body.pop("artifact_digest", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("parity cache summary digest mismatch")
    if require_complete and summary["status"] != "COMPLETE":
        raise ContractError("parity cache is not complete")
    if summary["contract_digest"] != contract["contract_digest"] or summary["manifest_digest"] != header["manifest_digest"]:
        raise ContractError("parity cache belongs to another freeze")
    if (
        int(summary["expected_missing_count"]) != len(missing)
        or int(summary["completed_count"]) != len(missing)
        or int(summary["failure_count"]) != 0
        or len(summary["records"]) != len(missing)
    ):
        raise ContractError("parity cache completion counts are inconsistent")
    expected_references = {
        "cache": repository_reference(root, root / "src/dante_light/o4a_v1_parity_cache.py"),
        "freeze": repository_reference(root, root / "src/dante_light/o4a_v1_parity.py"),
    }
    if summary["implementation_references"] != expected_references:
        raise ContractError("parity cache implementation provenance mismatch")
    expected_run_key = canonical_json_sha256({
        "contract_digest": contract["contract_digest"],
        "manifest_digest": header["manifest_digest"],
        "missing_file_sha256": header["missing_file_sha256"],
        "cache_code": expected_references["cache"],
    })
    if summary["run_key"] != expected_run_key:
        raise ContractError("parity cache run key mismatch")
    records = []
    for row in missing:
        record = _validate_series(
            _cache_path(cache_root, row), row,
            int(contract["representation"]["sample_rate_hz"]),
        )
        stored = _read_json(cache_root / "records" / f"{row['case_id']}.json")
        stored_body = dict(stored); stored_digest = stored_body.pop("record_digest", None)
        if stored_digest != canonical_json_sha256(stored_body):
            raise ContractError("parity cache record digest mismatch")
        for key, value in record.items():
            if stored.get(key) != value:
                raise ContractError(f"parity cache record drift: {row['case_id']} {key}")
        records.append(stored)
    if canonical_json_sha256([row["record_digest"] for row in sorted(records, key=lambda row: (row["detector"], row["required_padded_interval_gps"][0]))]) != summary["record_digest_aggregate"]:
        raise ContractError("parity cache record aggregate mismatch")
    return summary


def compact_cache_artifact(summary: Mapping[str, Any]) -> dict[str, Any]:
    if summary.get("status") != "COMPLETE":
        raise ContractError("cannot publish an incomplete parity cache summary")
    body = {
        "schema_version": 1,
        "status": "COMPLETE_RAW_INPUT_CACHE",
        "run_key": summary["run_key"],
        "contract_digest": summary["contract_digest"],
        "manifest_digest": summary["manifest_digest"],
        "logical_cache_root": summary["logical_cache_root"],
        "expected_missing_count": summary["expected_missing_count"],
        "completed_count": summary["completed_count"],
        "failure_count": summary["failure_count"],
        "record_digest_aggregate": summary["record_digest_aggregate"],
        "external_summary_sha256": None,
        "implementation_references": summary["implementation_references"],
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}
