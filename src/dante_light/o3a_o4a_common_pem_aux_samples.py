"""Lossless native-rate auxiliary transport for the paired diagnostic PEM.

No coherence, null or scientific verdict is computed here. The independent
replay verifies local sample files, not a second fetch from the NDS2 source.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256


class InfrastructureError(RuntimeError):
    """Exhausted NDS2 transport retries; existing receipts remain immutable."""


def sample_specs(
    requirements: list[dict], rates: Mapping[str, Mapping[str, int]]
) -> list[dict]:
    """Deduplicate shared spans without changing any target's frozen input."""
    found: dict[str, dict] = {}
    for row in requirements:
        run, detector = row["run"], row["detector"]
        if run not in ("O3a", "O4a") or detector not in ("H1", "L1"):
            raise ContractError("common PEM auxiliary sample identity changed")
        channels = row["channels"]
        if len(channels) != len(set(channels)) or set(channels) != set(rates[detector]):
            raise ContractError("common PEM auxiliary native channel set changed")
        for role in ("event", "background"):
            left, right = (int(x) for x in row[f"{role}_interval_gps"])
            if right <= left:
                raise ContractError("common PEM auxiliary sample interval invalid")
            for channel in channels:
                rate = rates[detector][channel]
                if not isinstance(rate, int) or rate <= 0:
                    raise ContractError("common PEM auxiliary native rate invalid")
                identity = {
                    "run": run,
                    "detector": detector,
                    "channel": channel,
                    "interval_gps": [left, right],
                }
                key = canonical_json_sha256(identity)
                if key not in found:
                    found[key] = {
                        "key": key,
                        **identity,
                        "sample_rate_hz": rate,
                        "sample_count": (right - left) * rate,
                        "uses": [],
                    }
                found[key]["uses"].append(
                    {"target_gps": row["target_gps"], "role": role}
                )
    return list(found.values())


def data_path(run_dir: Path, spec: Mapping[str, Any]) -> Path:
    return run_dir / "data" / f"{spec['key']}.npy"


def _validate_chunk(
    series: Any, spec: Mapping[str, Any], left: int, right: int
) -> tuple[np.ndarray, str]:
    try:
        start = float(series.t0.value)
        end = start + float(series.duration.value)
        rate = float(series.sample_rate.value)
        data = np.asarray(series.value)
        unit = str(series.unit)
        name = str(series.name)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractError(
            "common PEM auxiliary native chunk metadata absent"
        ) from exc
    if (
        start != left
        or end != right
        or rate != spec["sample_rate_hz"]
        or name != spec["channel"]
        or data.dtype != np.dtype("float32")
        or data.ndim != 1
        or data.size != (right - left) * rate
        or not np.isfinite(data).all()
    ):
        raise ContractError("common PEM auxiliary native chunk changed or incomplete")
    return data, unit


def acquire_series(
    spec: Mapping[str, Any],
    *,
    run_dir: Path,
    nds_host: str,
    chunk_seconds: int,
    retries: int,
    backoff_base_s: float,
    fetch: Callable[..., Any],
) -> dict:
    """Fetch exact native float32 chunks and atomically publish one NPY file."""
    if chunk_seconds <= 0 or retries < 1 or backoff_base_s < 1:
        raise ContractError("common PEM auxiliary transport policy invalid")
    path = data_path(run_dir, spec)
    partial = path.with_suffix(".partial.npy")
    if path.exists() or partial.exists():
        raise ContractError("common PEM auxiliary sample has an unreceipted file")
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.lib.format.open_memmap(
        partial, mode="w+", dtype=np.dtype("float32"), shape=(spec["sample_count"],)
    )
    digest = hashlib.sha256()
    unit: str | None = None
    left, end = spec["interval_gps"]
    try:
        while left < end:
            right = min(left + chunk_seconds, end)
            series = None
            for attempt in range(retries):
                try:
                    series = fetch(
                        spec["channel"], start=left, end=right, host=nds_host
                    )
                    break
                except Exception as exc:
                    if attempt + 1 == retries:
                        raise InfrastructureError(
                            f"NDS2 auxiliary transport exhausted: {spec['key']}"
                        ) from exc
                    time.sleep(backoff_base_s**attempt)
            data, chunk_unit = _validate_chunk(series, spec, left, right)
            if unit is None:
                unit = chunk_unit
            elif chunk_unit != unit:
                raise ContractError("common PEM auxiliary native unit changed")
            offset = (left - spec["interval_gps"][0]) * spec["sample_rate_hz"]
            samples[offset : offset + data.size] = data
            digest.update(data.tobytes(order="C"))
            left = right
        samples.flush()
    finally:
        del samples
    os.replace(partial, path)
    return {
        "status": "PASS_AUX_NATIVE_SAMPLES_ONLY",
        "spec": dict(spec),
        "nds_host": nds_host,
        "dtype": "float32",
        "unit": unit,
        "file": path.name,
        "file_sha256": sha256_file(path),
        "samples_sha256": digest.hexdigest(),
        "file_size_bytes": path.stat().st_size,
    }


def verify_series(
    spec: Mapping[str, Any],
    receipt: Mapping[str, Any],
    *,
    run_dir: Path,
    chunk_seconds: int,
) -> None:
    """Independently replay every retained native sample without NDS2 access."""
    path = data_path(run_dir, spec)
    if (
        receipt.get("status") != "PASS_AUX_NATIVE_SAMPLES_ONLY"
        or receipt.get("spec") != dict(spec)
        or receipt.get("file") != path.name
        or not isinstance(receipt.get("unit"), str)
        or receipt.get("dtype") != "float32"
        or not path.is_file()
        or sha256_file(path) != receipt.get("file_sha256")
        or path.stat().st_size != receipt.get("file_size_bytes")
    ):
        raise ContractError("common PEM auxiliary native file or receipt changed")
    data = np.load(path, mmap_mode="r", allow_pickle=False)
    if data.dtype != np.dtype("float32") or data.shape != (spec["sample_count"],):
        raise ContractError("common PEM auxiliary native array geometry changed")
    digest = hashlib.sha256()
    if chunk_seconds <= 0:
        raise ContractError("common PEM auxiliary replay chunk invalid")
    stride = spec["sample_rate_hz"] * chunk_seconds
    for offset in range(0, data.size, stride):
        chunk = np.asarray(data[offset : offset + stride])
        if not np.isfinite(chunk).all():
            raise ContractError("common PEM auxiliary native samples nonfinite")
        digest.update(chunk.tobytes(order="C"))
    if digest.hexdigest() != receipt.get("samples_sha256"):
        raise ContractError("common PEM auxiliary native numerical digest changed")
