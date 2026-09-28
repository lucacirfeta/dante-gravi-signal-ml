"""Stream frozen full background spans from acquired GWOSC frame bytes.

This producer never downloads and never evaluates auxiliary channels or PEM
outcomes. The separate frozen background verifier replays each receipt.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError
from src.dante_light.o3a_o4a_common_pem_background import _md5_file, _require_source
from src.dante_light.o3a_o4a_common_pem_gate import plan_background_frames


def produce_span_receipt(
    *,
    detector: str,
    start: int,
    end: int,
    source: Mapping[str, Any],
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    cache_dir: Path,
) -> dict[str, Any]:
    """Hash every used sample without materializing a four-hour array."""
    _require_source(source)
    frames = plan_background_frames(
        detector=detector,
        start=start,
        end=end,
        manifest=manifest,
        frame_duration_s=int(source["frame_duration_s"]),
    )
    rate = int(source["sample_rate_hz"])
    duration = int(source["frame_duration_s"])
    digest = hashlib.sha256()
    recorded: list[dict[str, Any]] = []
    total = 0
    for frame in frames:
        filename = str(frame["filename"])
        if Path(filename).name != filename or not filename.endswith(".hdf5"):
            raise ContractError("common PEM span frame filename is invalid")
        path = cache_dir / filename
        if (
            not path.is_file()
            or path.parent.resolve() != cache_dir.resolve()
            or _md5_file(path) != frame["md5"]
        ):
            raise ContractError("common PEM span requires verified local frame bytes")
        frame_start = int(frame["gps_start"])
        left, right = (int(value) for value in frame["used_interval_gps"])
        with h5py.File(path, "r") as handle:
            dataset = handle.get("strain/Strain")
            meta = handle.get("meta")
            if dataset is None or meta is None:
                raise ContractError("common PEM span frame structure invalid")

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
                    metadata(name) != expected
                    for name, expected in source["metadata"][detector].items()
                )
            ):
                raise ContractError("common PEM span frame metadata changed")
            first = (left - frame_start) * rate
            last = (right - frame_start) * rate
            while first < last:
                stop = min(last, first + (1 << 18))
                samples = np.ascontiguousarray(dataset[first:stop], dtype=np.float64)
                if samples.size != stop - first or not np.isfinite(samples).all():
                    raise ContractError("common PEM span samples invalid")
                digest.update(samples.tobytes())
                total += samples.size
                first = stop
        recorded.append(
            {
                "url": source["archive_url_prefix"]
                + str(frame["relative_path"]).split("/", 1)[1],
                "filename": filename,
                "used_interval_gps": frame["used_interval_gps"],
                "md5": frame["md5"],
                "sha256": sha256_file(path),
            }
        )
    if total != (end - start) * rate:
        raise ContractError("common PEM span sample count changed")
    return {
        "detector": detector,
        "interval_gps": [start, end],
        "release": source["release"],
        "frames": recorded,
        "samples_sha256": digest.hexdigest(),
    }
