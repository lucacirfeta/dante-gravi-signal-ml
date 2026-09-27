"""Synthetic numerical-context tests for the separate O4a PEM adapter."""

from __future__ import annotations

import hashlib
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_o4a_common_pem_strain import (
    o4a_context_samples,
    o4a_event_strain,
)
from src.dante_light.o4a_corrected_native_pem import _read_seed_strain


def _cross_frame_case(tmp_path: Path) -> tuple[dict, dict, dict, dict]:
    rate = 64
    frame_a = tmp_path / "first.hdf5"
    frame_b = tmp_path / "second.hdf5"
    grid_a = np.arange(8 * rate, dtype=np.float64) / rate
    grid_b = 8 + np.arange(8 * rate, dtype=np.float64) / rate
    values_a = np.sin(2 * np.pi * 3 * grid_a)
    values_b = np.sin(2 * np.pi * 3 * grid_b)
    for path, values in ((frame_a, values_a), (frame_b, values_b)):
        with h5py.File(path, "w") as handle:
            handle.create_dataset("strain/Strain", data=values)
    raw = np.ascontiguousarray(
        np.concatenate((values_a[6 * rate :], values_b[: 6 * rate]))
    )
    target = {
        "detector": "H1",
        "gps_start": 8,
        "raw_context_sha256": hashlib.sha256(raw.tobytes()).hexdigest(),
        "context_sources": [
            {"used_interval": [6, 8]},
            {"used_interval": [8, 14]},
        ],
    }
    source = {
        "frame_duration_s": 8,
        "sample_rate_hz": rate,
        "context_duration_s": 8,
        "context_lead_s": 2,
    }
    measurement = {"event_window_s": 4, "strain_highpass_hz": 1.0}
    return target, {("H1", 0): frame_a, ("H1", 8): frame_b}, source, measurement


def test_o4a_adapter_reconstructs_cross_frame_context_and_event(tmp_path: Path) -> None:
    target, frames, source, measurement = _cross_frame_case(tmp_path)
    raw = o4a_context_samples(target, frames=frames, source=source)
    assert raw.shape == (8 * source["sample_rate_hz"],)
    series, central_sha = o4a_event_strain(
        target, frames=frames, source=source, measurement=measurement
    )
    central = raw[2 * source["sample_rate_hz"] : 6 * source["sample_rate_hz"]]
    assert central_sha == hashlib.sha256(central.tobytes()).hexdigest()
    assert len(series) == 4 * source["sample_rate_hz"]
    assert float(series.sample_rate.value) == source["sample_rate_hz"]
    assert float(series.t0.value) == target["gps_start"]


def test_o4a_adapter_rejects_changed_historical_context(tmp_path: Path) -> None:
    target, frames, source, _ = _cross_frame_case(tmp_path)
    target["raw_context_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="differs from historical target"):
        o4a_context_samples(target, frames=frames, source=source)


def test_o4a_adapter_rejects_missing_frame(tmp_path: Path) -> None:
    target, frames, source, _ = _cross_frame_case(tmp_path)
    del frames["H1", 8]
    with pytest.raises(ContractError, match="gap"):
        o4a_context_samples(target, frames=frames, source=source)


def test_o4a_adapter_rejects_nonfinite_frame_slice(tmp_path: Path) -> None:
    target, frames, source, _ = _cross_frame_case(tmp_path)
    with h5py.File(frames["H1", 8], "r+") as handle:
        handle["strain/Strain"][0] = np.nan
    with pytest.raises(ContractError, match="invalid"):
        o4a_context_samples(target, frames=frames, source=source)


def test_official_frame_adapter_matches_historical_preprocessing(
    tmp_path: Path,
) -> None:
    rate = 4096
    raw_root = tmp_path / "historical"
    raw_root.mkdir()
    official_root = tmp_path / "official"
    official_root.mkdir()
    context = np.sin(2 * np.pi * 40 * np.arange(40 * rate) / rate).astype(np.float64)
    context += 0.2 * np.sin(2 * np.pi * 5 * np.arange(40 * rate) / rate)
    sources = []
    frames = {}
    for index, start in enumerate((20, 40)):
        values = context[index * 20 * rate : (index + 1) * 20 * rate]
        local_name = f"local_{index}.hdf5"
        local_path = raw_root / local_name
        official_path = official_root / f"frame_{index}.hdf5"
        with h5py.File(local_path, "w") as handle:
            handle.create_dataset("Strain", data=values)
        with h5py.File(official_path, "w") as handle:
            handle.create_dataset("strain/Strain", data=values)
        sources.append(
            {
                "relative_path": local_name,
                "sha256": hashlib.sha256(local_path.read_bytes()).hexdigest(),
                "block_interval": [start, start + 20],
                "used_interval": [start, start + 20],
            }
        )
        frames["H1", start] = official_path
    target = {
        "detector": "H1",
        "gps_start": 24,
        "raw_context_sha256": hashlib.sha256(context.tobytes()).hexdigest(),
        "context_sources": sources,
    }
    historical, historical_sha = _read_seed_strain(target, raw_root)
    replayed, replayed_sha = o4a_event_strain(
        target,
        frames=frames,
        source={
            "sample_rate_hz": rate,
            "frame_duration_s": 20,
            "context_duration_s": 40,
            "context_lead_s": 4,
        },
        measurement={"event_window_s": 32, "strain_highpass_hz": 20},
    )
    assert replayed_sha == historical_sha
    np.testing.assert_array_equal(replayed.value, historical.value)
    assert replayed.t0 == historical.t0
    assert replayed.sample_rate == historical.sample_rate
