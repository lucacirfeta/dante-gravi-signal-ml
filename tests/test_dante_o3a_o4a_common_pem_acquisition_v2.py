"""The v2 transport probe is inside, not before, the frozen span."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light import o3a_o4a_common_pem_background as background
from src.dante_light.contracts import ContractError
from src.dante_light.o3a_o4a_common_pem_acquisition_v2 import (
    acquire_frame_v2,
    required_frames_with_probes,
    verify_frame_v2,
)
from tests.test_dante_o3a_o4a_common_pem_acquisition import _fixture


def test_v2_probe_is_earliest_planned_overlap_not_frame_start(tmp_path: Path) -> None:
    _, frame, _, manifest = _fixture(tmp_path)
    selected = required_frames_with_probes(
        [
            {"detector": "H1", "interval_gps": [102, 104]},
            {"detector": "H1", "interval_gps": [101, 103]},
        ],
        manifest=manifest,
        frame_duration_s=4,
    )
    assert selected == [{**frame, "probe_interval_gps": [101, 102]}]


def test_v2_acquisition_accepts_invalid_samples_outside_planned_span(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original, frame, source, manifest = _fixture(tmp_path)
    with h5py.File(original, "r+") as handle:
        handle["strain/Strain"][:2] = np.nan
    frame["md5"] = hashlib.md5(original.read_bytes()).hexdigest()  # noqa: S324
    selected = required_frames_with_probes(
        [{"detector": "H1", "interval_gps": [101, 104]}],
        manifest=manifest,
        frame_duration_s=4,
    )[0]

    calls: list[str] = []

    def download(url: str, destination: Path) -> None:
        calls.append(url)
        destination.parent.mkdir(parents=True)
        shutil.copyfile(original, destination)

    monkeypatch.setattr(background, "_download_official", download)
    run_dir = tmp_path / "run_v2"
    receipt = acquire_frame_v2(
        selected, source=source, manifest=manifest, run_dir=run_dir
    )
    assert receipt["probe"]["interval_gps"] == [101, 102]
    assert receipt["status"] == "PASS_ACQUIRED_OFFICIAL_FRAME_BYTES_V2_ONLY"
    assert (
        verify_frame_v2(selected, source=source, manifest=manifest, run_dir=run_dir)
        == receipt
    )
    assert (
        acquire_frame_v2(selected, source=source, manifest=manifest, run_dir=run_dir)
        == receipt
    )
    assert len(calls) == 1

    wrong_position = {**selected, "probe_interval_gps": [102, 103]}
    with pytest.raises(ContractError, match="identity changed"):
        verify_frame_v2(
            wrong_position, source=source, manifest=manifest, run_dir=run_dir
        )
