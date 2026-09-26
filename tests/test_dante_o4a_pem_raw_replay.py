from __future__ import annotations

import hashlib
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o4a_pem_raw_replay import (
    _coverage,
    context_digest,
    parse_manifest,
    required_frames,
    validate_frame,
)


def _manifest_row(detector: str, start: int) -> bytes:
    initial = detector[0]
    filename = f"{initial}-{detector}_GWOSC_O4a_4KHZ_R1-{start}-4096.hdf5"
    return f"{'a' * 32}  {detector}/1234567890/{filename}\n".encode()


def test_manifest_and_coverage_handle_unaligned_historical_blocks() -> None:
    manifest = parse_manifest(
        _manifest_row("L1", 1000) + _manifest_row("L1", 5096),
        "O4a_4KHZ_R1",
    )
    target = {
        "detector": "L1",
        "context_sources": [
            {
                "relative_path": "legacy/L1_5000_9096.hdf5",
                "sha256": "b" * 64,
                "used_interval": [5094.0, 5098.0],
            }
        ],
    }
    frames = required_frames([target], manifest)
    assert [row["gps_start"] for row in frames] == [1000, 5096]
    assert [span[1:] for span in _coverage("L1", 5094, 5098, manifest, 4096)] == [
        (5094, 5096),
        (5096, 5098),
    ]


def test_coverage_fails_closed_on_official_gap() -> None:
    manifest = parse_manifest(
        _manifest_row("L1", 1000) + _manifest_row("L1", 6000),
        "O4a_4KHZ_R1",
    )
    with pytest.raises(ContractError, match="gap"):
        _coverage("L1", 5094, 6002, manifest, 4096)


def test_manifest_rejects_duplicate_frame() -> None:
    line = _manifest_row("H1", 1000)
    with pytest.raises(ContractError, match="duplicated"):
        parse_manifest(line + line, "O4a_4KHZ_R1")


def test_context_replay_exact_across_official_boundary(tmp_path: Path) -> None:
    left = tmp_path / "left.hdf5"
    right = tmp_path / "right.hdf5"
    with h5py.File(left, "w") as handle:
        handle.create_dataset("strain/Strain", data=np.arange(32, dtype=np.float64))
    with h5py.File(right, "w") as handle:
        handle.create_dataset("strain/Strain", data=np.arange(32, 64, dtype=np.float64))
    expected = np.concatenate(
        (np.arange(24, 32, dtype=np.float64), np.arange(32, 40, dtype=np.float64))
    )
    digest = hashlib.sha256(expected.tobytes()).hexdigest()
    target = {
        "detector": "L1",
        "context_sources": [{"used_interval": [6.0, 10.0]}],
        "raw_context_sha256": digest,
    }
    source = {"sample_rate_hz": 4, "frame_duration_s": 8, "context_duration_s": 4}
    paths = {("L1", 0): left, ("L1", 8): right}
    assert context_digest(target, paths, source) == digest
    target["raw_context_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="differs"):
        context_digest(target, paths, source)


def test_frame_validation_rejects_calibration_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "frame.hdf5"
    with h5py.File(path, "w") as handle:
        meta = handle.create_group("meta")
        meta.create_dataset("Detector", data=b"L1")
        meta.create_dataset("GPSstart", data=1000)
        meta.create_dataset("Duration", data=8)
        meta.create_dataset("FrameType", data=b"L1_HOFT_C00_AR")
        meta.create_dataset("StrainChannel", data=b"L1:GDS-CALIB_STRAIN_AR")
        dataset = handle.create_dataset("strain/Strain", data=np.zeros(32, dtype=np.float64))
        dataset.attrs["Xstart"] = 1000
        dataset.attrs["Xspacing"] = 0.25
    frame = {"detector": "L1", "gps_start": 1000, "md5": hashlib.md5(path.read_bytes()).hexdigest()}
    source = {
        "frame_duration_s": 8,
        "sample_rate_hz": 4,
        "frame_type": {"L1": "L1_HOFT_C00_AR"},
        "strain_channel": {"L1": "L1:GDS-CALIB_STRAIN_CLEAN_AR"},
    }
    with pytest.raises(ContractError, match="calibration metadata"):
        validate_frame(path, frame, source)
