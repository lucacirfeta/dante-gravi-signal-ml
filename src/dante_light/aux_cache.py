"""Provenance-preserving read-through cache for auxiliary channel time series.

The cache is transport-neutral and is not in the synchronous Light scoring
path. A future NDS2 adapter may supply the fetch callback explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Callable

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256


@dataclass(frozen=True, slots=True)
class AuxChannelKey:
    detector: str
    channel: str
    gps_start: float
    gps_end: float
    sample_rate_hz: float
    source: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ContractError("unsupported auxiliary-cache schema")
        if not self.channel or not self.source:
            raise ContractError("auxiliary channel and source are required")
        if not self.gps_end > self.gps_start:
            raise ContractError("invalid auxiliary time interval")
        if not math.isfinite(self.sample_rate_hz) or self.sample_rate_hz <= 0:
            raise ContractError("invalid auxiliary sample rate")

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "detector": self.detector.upper(),
            "channel": self.channel,
            "gps_start": float(self.gps_start),
            "gps_end": float(self.gps_end),
            "sample_rate_hz": float(self.sample_rate_hz),
            "source": self.source,
        }

    @property
    def cache_id(self) -> str:
        return f"aux1-{canonical_json_sha256(self.to_dict())[:32]}"


class AuxChannelCache:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _paths(self, key: AuxChannelKey) -> tuple[Path, Path]:
        return self.root / f"{key.cache_id}.npy", self.root / f"{key.cache_id}.json"

    @staticmethod
    def _validate(key: AuxChannelKey, values: np.ndarray) -> np.ndarray:
        array = np.ascontiguousarray(values, dtype=np.float64)
        expected = int(round((key.gps_end - key.gps_start) * key.sample_rate_hz))
        if array.ndim != 1 or array.size != expected:
            raise ContractError(
                f"auxiliary series length {array.size} does not match {expected}"
            )
        if not np.all(np.isfinite(array)):
            raise ContractError("auxiliary series contains non-finite values")
        return array

    def load(self, key: AuxChannelKey) -> np.ndarray | None:
        data_path, metadata_path = self._paths(key)
        if not data_path.is_file() or not metadata_path.is_file():
            return None
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("key") != key.to_dict():
            raise ContractError("auxiliary cache key mismatch")
        actual_file = hashlib.sha256(data_path.read_bytes()).hexdigest()
        if actual_file != metadata.get("npy_sha256"):
            raise ContractError("auxiliary cache file SHA256 mismatch")
        values = self._validate(key, np.load(data_path, allow_pickle=False))
        value_sha = hashlib.sha256(values.tobytes()).hexdigest()
        if value_sha != metadata.get("values_sha256"):
            raise ContractError("auxiliary cached values SHA256 mismatch")
        return values

    def get_or_fetch(
        self,
        key: AuxChannelKey,
        fetch: Callable[[AuxChannelKey], np.ndarray],
    ) -> tuple[np.ndarray, bool]:
        cached = self.load(key)
        if cached is not None:
            return cached, True
        values = self._validate(key, fetch(key))
        data_path, metadata_path = self._paths(key)
        temporary_data = data_path.with_suffix(".npy.tmp")
        temporary_metadata = metadata_path.with_suffix(".json.tmp")
        with temporary_data.open("wb") as handle:
            np.save(handle, values, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        metadata = {
            "schema_version": 1,
            "cache_id": key.cache_id,
            "key": key.to_dict(),
            "values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
            "npy_sha256": hashlib.sha256(temporary_data.read_bytes()).hexdigest(),
        }
        with temporary_metadata.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_data, data_path)
        os.replace(temporary_metadata, metadata_path)
        return values, False
