"""Checksum-bound official strain reader for diagnostic PEM background spans.

The caller supplies a validated, versioned source contract and parsed GWOSC
manifest. This reader never falls back to a local unreceipted strain block.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import h5py
import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError
from src.dante_light.o3a_o4a_common_pem_gate import plan_background_frames


def _md5_file(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - published GWOSC transport checksum
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _download_official(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".partial", dir=destination.parent
    )
    try:
        with (
            os.fdopen(descriptor, "wb") as output,
            urlopen(url, timeout=120) as response,
        ):
            for block in iter(lambda: response.read(8 * 1024 * 1024), b""):
                output.write(block)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _require_source(source: Mapping[str, Any]) -> None:
    release = source["release"]
    metadata = source.get("metadata")
    if (
        release not in ("O3a_4KHZ_R1", "O4a_4KHZ_R1")
        or source["archive_url_prefix"] != f"https://gwosc.org/archive/data/{release}/"
        or int(source["sample_rate_hz"]) <= 0
        or int(source["frame_duration_s"]) <= 0
        or not isinstance(metadata, Mapping)
        or set(metadata) != {"H1", "L1"}
        or any(
            not isinstance(metadata[detector], Mapping)
            or set(metadata[detector]) != {"FrameType", "StrainChannel"}
            or not all(metadata[detector].values())
            for detector in ("H1", "L1")
        )
    ):
        raise ContractError("common PEM official background source is invalid")


class OfficialBackgroundReader:
    """Read one CAT1 background block from published 4 kHz R1 HDF5 frames."""

    def __init__(
        self,
        *,
        source: Mapping[str, Any],
        manifest: Mapping[tuple[str, int], Mapping[str, Any]],
        cache_dir: Path,
    ) -> None:
        self.source = source
        self.manifest = manifest
        self.cache_dir = cache_dir
        self.receipts: list[dict[str, Any]] = []
        _require_source(source)

    def __call__(self, detector: str, start: int, end: int) -> Any:
        from gwpy.timeseries import TimeSeries

        pieces = plan_background_frames(
            detector=detector,
            start=start,
            end=end,
            manifest=self.manifest,
            frame_duration_s=int(self.source["frame_duration_s"]),
        )
        rate = int(self.source["sample_rate_hz"])
        values: list[np.ndarray] = []
        frames: list[dict[str, Any]] = []
        for frame in pieces:
            path = self.cache_dir / str(frame["filename"])
            relative = str(frame["relative_path"])
            if path.parent.resolve() != self.cache_dir.resolve():
                raise ContractError("common PEM background frame escaped cache")
            expected_url = self.source["archive_url_prefix"] + relative.split("/", 1)[1]
            if not path.exists():
                _download_official(expected_url, path)
            if not path.is_file() or _md5_file(path) != frame["md5"]:
                raise ContractError(
                    "common PEM background frame MD5 differs from GWOSC"
                )
            with h5py.File(path, "r") as handle:
                dataset = handle.get("strain/Strain")
                meta = handle.get("meta")
                frame_start = int(frame["gps_start"])
                if dataset is None or meta is None:
                    raise ContractError("common PEM background frame structure invalid")

                def metadata(name: str) -> str:
                    item = meta[name][()]
                    return item.decode() if isinstance(item, bytes) else str(item)

                if (
                    metadata("Detector") != detector
                    or metadata("GPSstart") != str(frame_start)
                    or metadata("Duration") != str(self.source["frame_duration_s"])
                    or dataset.dtype != np.dtype("float64")
                    or dataset.shape != (int(self.source["frame_duration_s"]) * rate,)
                    or float(dataset.attrs["Xstart"]) != frame_start
                    or float(dataset.attrs["Xspacing"]) != 1 / rate
                ):
                    raise ContractError("common PEM background frame geometry invalid")
                for name, expected in self.source["metadata"][detector].items():
                    if metadata(name) != expected:
                        raise ContractError(
                            "common PEM background calibration metadata changed"
                        )
                left, right = frame["used_interval_gps"]
                first, last = (left - frame_start) * rate, (right - frame_start) * rate
                part = np.asarray(dataset[first:last], dtype=np.float64)
                if (
                    part.shape != ((right - left) * rate,)
                    or not np.isfinite(part).all()
                ):
                    raise ContractError("common PEM background frame samples invalid")
                values.append(part)
            frames.append(
                {
                    "url": expected_url,
                    "filename": frame["filename"],
                    "used_interval_gps": frame["used_interval_gps"],
                    "md5": frame["md5"],
                    "sha256": sha256_file(path),
                }
            )
        raw = np.ascontiguousarray(np.concatenate(values), dtype=np.float64)
        if raw.shape != ((end - start) * rate,):
            raise ContractError("common PEM background assembled span incomplete")
        self.receipts.append(
            {
                "detector": detector,
                "interval_gps": [start, end],
                "release": self.source["release"],
                "frames": frames,
                "samples_sha256": hashlib.sha256(raw.tobytes()).hexdigest(),
            }
        )
        return TimeSeries(raw, t0=start, sample_rate=rate, name=f"{detector}:STRAIN")


def verify_background_receipt(
    receipt: Mapping[str, Any],
    *,
    source: Mapping[str, Any],
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    cache_dir: Path,
) -> dict[str, Any]:
    """Independently replay a span from existing frame bytes; never download."""
    _require_source(source)
    detector = str(receipt["detector"])
    start, end = (int(value) for value in receipt["interval_gps"])
    if receipt["release"] != source["release"]:
        raise ContractError("common PEM background receipt release changed")
    rate = int(source["sample_rate_hz"])
    duration = int(source["frame_duration_s"])
    expected = plan_background_frames(
        detector=detector,
        start=start,
        end=end,
        manifest=manifest,
        frame_duration_s=duration,
    )
    if len(receipt["frames"]) != len(expected):
        raise ContractError("common PEM background receipt frame count changed")
    digest = hashlib.sha256()
    sample_total = 0
    for planned, recorded in zip(expected, receipt["frames"], strict=True):
        url = (
            source["archive_url_prefix"]
            + str(planned["relative_path"]).split("/", 1)[1]
        )
        if (
            recorded["url"] != url
            or recorded["filename"] != planned["filename"]
            or recorded["used_interval_gps"] != planned["used_interval_gps"]
            or recorded["md5"] != planned["md5"]
        ):
            raise ContractError("common PEM background receipt frame identity changed")
        path = cache_dir / str(planned["filename"])
        if (
            not path.is_file()
            or path.parent.resolve() != cache_dir.resolve()
            or _md5_file(path) != planned["md5"]
            or sha256_file(path) != recorded["sha256"]
        ):
            raise ContractError("common PEM background frame bytes changed")
        frame_start = int(planned["gps_start"])
        left, right = (int(value) for value in planned["used_interval_gps"])
        with h5py.File(path, "r") as handle:
            dataset = handle.get("strain/Strain")
            meta = handle.get("meta")
            if dataset is None or meta is None:
                raise ContractError(
                    "common PEM background frame replay structure invalid"
                )

            def metadata(name: str) -> str:
                value = meta[name][()]
                return value.decode() if isinstance(value, bytes) else str(value)

            if (
                metadata("Detector") != detector
                or metadata("GPSstart") != str(frame_start)
                or metadata("Duration") != str(duration)
                or dataset.dtype != np.dtype("float64")
                or dataset.shape != (duration * rate,)
                or float(dataset.attrs["Xstart"]) != frame_start
                or float(dataset.attrs["Xspacing"]) != 1 / rate
                or any(
                    metadata(name) != value
                    for name, value in source["metadata"][detector].items()
                )
            ):
                raise ContractError(
                    "common PEM background frame replay metadata changed"
                )
            first, last = (left - frame_start) * rate, (right - frame_start) * rate
            samples = np.ascontiguousarray(dataset[first:last], dtype=np.float64)
            if samples.size != (right - left) * rate or not np.isfinite(samples).all():
                raise ContractError(
                    "common PEM background frame replay samples invalid"
                )
            digest.update(samples.tobytes())
            sample_total += samples.size
    if (
        sample_total != (end - start) * rate
        or digest.hexdigest() != receipt["samples_sha256"]
    ):
        raise ContractError("common PEM background numerical span digest changed")
    return {
        "status": "PASS_VERIFIED_BACKGROUND_SPAN",
        "detector": detector,
        "interval_gps": [start, end],
        "frame_count": len(expected),
        "samples_sha256": digest.hexdigest(),
    }
