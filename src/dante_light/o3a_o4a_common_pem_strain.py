"""Strain input adapters for the diagnostic common-channel PEM follow-up.

The historical O4a PEM reader is immutable and requires local HDF5 file-byte
identity. This separate adapter uses the independently verified public-frame
replay and still requires exact historical *numerical-context* identity.
No coherence, null or verdict is computed here.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_pem_raw_replay import (
    _coverage,
    load_targets,
    parse_manifest,
    required_frames,
)
from src.dante_light.o4a_pem_raw_replay_v2 import load_contract, verify_replay


def verified_o4a_frames(
    run_dir: Path, *, root: Path
) -> tuple[dict[str, Any], dict[tuple[str, int], Path]]:
    """Reverify the complete frozen replay before exposing its frame paths."""
    run_dir = run_dir.resolve()
    verified = verify_replay(root=root, run_dir=run_dir)
    contract = load_contract(root)
    targets = load_targets(contract)
    manifest = parse_manifest(
        (run_dir / "gwosc_strain_hdf_md5.txt").read_bytes(),
        str(contract["source"]["release"]),
    )
    frames = required_frames(targets, manifest)
    if verified["frame_count"] != len(frames) or verified["target_count"] != len(
        targets
    ):
        raise ContractError("O4a PEM raw replay counts changed after verification")
    paths: dict[tuple[str, int], Path] = {}
    frame_root = (run_dir / "frames").resolve()
    for frame in frames:
        path = (frame_root / str(frame["relative_path"])).resolve()
        if frame_root not in path.parents or not path.is_file():
            raise ContractError("O4a PEM verified frame path is missing or escaped")
        paths[str(frame["detector"]), int(frame["gps_start"])] = path
    return contract, paths


def o4a_context_samples(
    target: Mapping[str, Any],
    *,
    frames: Mapping[tuple[str, int], Path],
    source: Mapping[str, Any],
) -> np.ndarray:
    """Reconstruct one frozen O4a 40-s context from verified official frames."""
    detector = str(target["detector"])
    rate = int(source["sample_rate_hz"])
    duration = int(source["frame_duration_s"])
    parts: list[np.ndarray] = []
    for item in target["context_sources"]:
        for key, used_start, used_end in _coverage(
            detector,
            float(item["used_interval"][0]),
            float(item["used_interval"][1]),
            frames,
            duration,
        ):
            path = frames[key]
            first = int(round((used_start - key[1]) * rate))
            last = int(round((used_end - key[1]) * rate))
            with h5py.File(path, "r") as handle:
                values = np.asarray(
                    handle["strain/Strain"][first:last], dtype=np.float64
                )
            if len(values) != last - first or not np.isfinite(values).all():
                raise ContractError("O4a PEM event context frame slice is invalid")
            parts.append(values)
    if not parts:
        raise ContractError("O4a PEM event has no official-frame context")
    raw = np.ascontiguousarray(np.concatenate(parts), dtype=np.float64)
    expected = int(source["context_duration_s"]) * rate
    if raw.shape != (expected,):
        raise ContractError("O4a PEM event context length changed")
    if hashlib.sha256(raw.tobytes()).hexdigest() != target["raw_context_sha256"]:
        raise ContractError("O4a PEM event context differs from historical target")
    return raw


def o4a_event_strain(
    target: Mapping[str, Any],
    *,
    frames: Mapping[tuple[str, int], Path],
    source: Mapping[str, Any],
    measurement: Mapping[str, Any],
) -> tuple[Any, str]:
    """Apply the frozen event crop/high-pass after exact context replay."""
    from gwpy.timeseries import TimeSeries

    raw = o4a_context_samples(target, frames=frames, source=source)
    rate = int(source["sample_rate_hz"])
    lead = int(source["context_lead_s"]) * rate
    end = lead + int(measurement["event_window_s"]) * rate
    if end > len(raw):
        raise ContractError("O4a PEM event crop exceeds verified context")
    central = np.ascontiguousarray(raw[lead:end], dtype=np.float64)
    central_sha = hashlib.sha256(central.tobytes()).hexdigest()
    series = TimeSeries(
        central,
        t0=float(target["gps_start"]),
        sample_rate=rate,
        name=f"{target['detector']}:STRAIN",
    )
    return series.highpass(float(measurement["strain_highpass_hz"])), central_sha
