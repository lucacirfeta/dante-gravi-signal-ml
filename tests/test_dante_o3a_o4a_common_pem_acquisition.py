"""Synthetic transport-only PEM background acquisition and resume tests."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light import o3a_o4a_common_pem_background as background
from src.dante_light.o3a_o4a_common_pem_acquisition import (
    acquire_frame,
    required_frames,
    verify_frame,
)
from src.dante_light.contracts import ContractError
from scripts.run_dante_o3a_o4a_common_pem_background_acquisition import (
    _single_controller,
)


def _fixture(tmp_path: Path) -> tuple[Path, dict, dict, dict]:
    original = tmp_path / "published.hdf5"
    with h5py.File(original, "w") as handle:
        meta = handle.create_group("meta")
        for key, value in {
            "Detector": "H1",
            "GPSstart": "100",
            "Duration": "4",
            "FrameType": "H1_HOFT_TEST",
            "StrainChannel": "H1:TEST_STRAIN",
        }.items():
            meta.create_dataset(key, data=np.bytes_(value))
        strain = handle.create_dataset(
            "strain/Strain", data=np.arange(8, dtype=np.float64)
        )
        strain.attrs["Xstart"] = 100.0
        strain.attrs["Xspacing"] = 0.5
    filename = "H-H1_GWOSC_O3a_4KHZ_R1-100-4.hdf5"
    frame = {
        "detector": "H1",
        "gps_start": 100,
        "filename": filename,
        "relative_path": f"H1/0/{filename}",
        "md5": hashlib.md5(original.read_bytes()).hexdigest(),  # noqa: S324
    }
    source = {
        "release": "O3a_4KHZ_R1",
        "archive_url_prefix": "https://gwosc.org/archive/data/O3a_4KHZ_R1/",
        "frame_duration_s": 4,
        "sample_rate_hz": 2,
        "metadata": {
            detector: {
                "FrameType": f"{detector}_HOFT_TEST",
                "StrainChannel": f"{detector}:TEST_STRAIN",
            }
            for detector in ("H1", "L1")
        },
    }
    return original, frame, source, {("H1", 100): frame}


def test_required_frames_deduplicates_overlapping_spans(tmp_path: Path) -> None:
    _, frame, _, manifest = _fixture(tmp_path)
    planned = required_frames(
        [
            {"detector": "H1", "interval_gps": [100, 102]},
            {"detector": "H1", "interval_gps": [101, 104]},
        ],
        manifest=manifest,
        frame_duration_s=4,
    )
    assert planned == [frame]
    with pytest.raises(ContractError, match="frames have a gap"):
        required_frames(
            [{"detector": "H1", "interval_gps": [100, 105]}],
            manifest=manifest,
            frame_duration_s=4,
        )


def test_acquire_frame_replays_and_resume_refuses_tamper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original, frame, source, manifest = _fixture(tmp_path)
    calls: list[str] = []

    def download(url: str, destination: Path) -> None:
        calls.append(url)
        destination.parent.mkdir(parents=True)
        shutil.copyfile(original, destination)

    monkeypatch.setattr(background, "_download_official", download)
    run_dir = tmp_path / "run"
    first = acquire_frame(frame, source=source, manifest=manifest, run_dir=run_dir)
    assert first["status"] == "PASS_ACQUIRED_OFFICIAL_FRAME_BYTES_ONLY"
    assert len(calls) == 1
    assert (
        verify_frame(frame, source=source, manifest=manifest, run_dir=run_dir) == first
    )
    assert (
        acquire_frame(frame, source=source, manifest=manifest, run_dir=run_dir) == first
    )
    assert len(calls) == 1
    receipt = run_dir / "receipts" / f"{frame['filename']}.json"
    with receipt.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises((ContractError, ValueError), match="receipt|Extra data"):
        acquire_frame(frame, source=source, manifest=manifest, run_dir=run_dir)
    assert len(calls) == 1


def test_acquisition_controller_refuses_parallel_writer(tmp_path: Path) -> None:
    with _single_controller(tmp_path):
        with pytest.raises(ContractError, match="controller already exists"):
            with _single_controller(tmp_path):
                pass
    assert not (tmp_path / "controller.lock").exists()
