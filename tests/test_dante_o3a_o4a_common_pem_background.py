"""Synthetic official-frame provenance tests for a PEM background block."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light import o3a_o4a_common_pem_background as background
from src.dante_light.o3a_o4a_common_pem_measurement import _require_complete_series
from src.dante_light.contracts import ContractError


def _frame(path: Path, *, start: int, rate: int, duration: int) -> None:
    values = np.arange(rate * duration, dtype=np.float64) + start
    with h5py.File(path, "w") as handle:
        meta = handle.create_group("meta")
        for key, value in {
            "Detector": "H1",
            "GPSstart": str(start),
            "Duration": str(duration),
            "FrameType": "H1_HOFT_TEST",
            "StrainChannel": "H1:TEST_STRAIN",
        }.items():
            meta.create_dataset(key, data=np.bytes_(value))
        strain = handle.create_dataset("strain/Strain", data=values)
        strain.attrs["Xstart"] = float(start)
        strain.attrs["Xspacing"] = 1 / rate


def _source(rate: int = 2, duration: int = 4) -> dict:
    return {
        "release": "O3a_4KHZ_R1",
        "archive_url_prefix": "https://gwosc.org/archive/data/O3a_4KHZ_R1/",
        "sample_rate_hz": rate,
        "frame_duration_s": duration,
        "metadata": {
            detector: {
                "FrameType": f"{detector}_HOFT_TEST",
                "StrainChannel": f"{detector}:TEST_STRAIN",
            }
            for detector in ("H1", "L1")
        },
    }


def test_background_reader_validates_frames_and_records_numeric_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original = tmp_path / "published.hdf5"
    _frame(original, start=100, rate=2, duration=4)
    filename = "H-H1_GWOSC_O3a_4KHZ_R1-100-4.hdf5"
    manifest = {
        ("H1", 100): {
            "detector": "H1",
            "gps_start": 100,
            "filename": filename,
            "relative_path": f"H1/0/{filename}",
            "md5": hashlib.md5(original.read_bytes()).hexdigest(),  # noqa: S324
        }
    }
    seen: list[str] = []

    def copy_download(url: str, path: Path) -> None:
        seen.append(url)
        path.parent.mkdir(parents=True)
        shutil.copyfile(original, path)

    monkeypatch.setattr(background, "_download_official", copy_download)
    cache = tmp_path / "cache"
    reader = background.OfficialBackgroundReader(
        source=_source(), manifest=manifest, cache_dir=cache
    )
    series = reader("H1", 101, 103)
    assert seen == ["https://gwosc.org/archive/data/O3a_4KHZ_R1/0/" + filename]
    assert series.t0.value == 101
    assert series.t0.value + series.duration.value == 103
    _require_complete_series(
        series, start=101, end=103, minimum_sample_rate=2, label="synthetic"
    )
    np.testing.assert_array_equal(series.value, np.array([102, 103, 104, 105]))
    assert (
        reader.receipts[0]["samples_sha256"]
        == hashlib.sha256(
            np.asarray(series.value, dtype=np.float64).tobytes()
        ).hexdigest()
    )
    assert len(reader.receipts[0]["frames"]) == 1
    verified = background.verify_background_receipt(
        reader.receipts[0],
        source=_source(),
        manifest=manifest,
        cache_dir=cache,
    )
    assert verified["status"] == "PASS_VERIFIED_BACKGROUND_SPAN"
    assert verified["samples_sha256"] == reader.receipts[0]["samples_sha256"]
    altered = {**reader.receipts[0], "samples_sha256": "0" * 64}
    with pytest.raises(ContractError, match="numerical span digest changed"):
        background.verify_background_receipt(
            altered,
            source=_source(),
            manifest=manifest,
            cache_dir=cache,
        )
    with (cache / filename).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ContractError, match="frame bytes changed"):
        background.verify_background_receipt(
            reader.receipts[0],
            source=_source(),
            manifest=manifest,
            cache_dir=cache,
        )
    with pytest.raises(ContractError, match="MD5 differs"):
        reader("H1", 101, 103)


def test_background_source_requires_calibration_metadata(tmp_path: Path) -> None:
    source = _source()
    source.pop("metadata")
    with pytest.raises(ContractError, match="source is invalid"):
        background.OfficialBackgroundReader(
            source=source, manifest={}, cache_dir=tmp_path
        )
