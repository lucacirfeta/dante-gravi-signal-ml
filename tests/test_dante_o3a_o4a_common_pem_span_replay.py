"""Synthetic full-span streaming and independent frozen-reader replay."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_o4a_common_pem_acquisition import _atomic_json
from src.dante_light.o3a_o4a_common_pem_background import (
    OfficialBackgroundReader,
    verify_background_receipt,
)
from src.dante_light.o3a_o4a_common_pem_span_replay import produce_span_receipt
from tests.test_dante_o3a_o4a_common_pem_background import _frame, _source
from scripts import run_dante_o3a_o4a_common_pem_span_replay as runner


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    cache = tmp_path / "frames"
    cache.mkdir()
    manifest: dict = {}
    for start in (100, 104):
        filename = f"H-H1_GWOSC_O3a_4KHZ_R1-{start}-4.hdf5"
        path = cache / filename
        _frame(path, start=start, rate=2, duration=4)
        manifest["H1", start] = {
            "detector": "H1",
            "gps_start": start,
            "filename": filename,
            "relative_path": f"H1/0/{filename}",
            "md5": hashlib.md5(path.read_bytes()).hexdigest(),  # noqa: S324
        }
    return cache, manifest


def test_streamed_span_matches_independent_reader(tmp_path: Path) -> None:
    cache, manifest = _fixture(tmp_path)
    receipt = produce_span_receipt(
        detector="H1",
        start=101,
        end=107,
        source=_source(),
        manifest=manifest,
        cache_dir=cache,
    )
    verified = verify_background_receipt(
        receipt, source=_source(), manifest=manifest, cache_dir=cache
    )
    assert verified["status"] == "PASS_VERIFIED_BACKGROUND_SPAN"
    assert verified["frame_count"] == 2
    reader = OfficialBackgroundReader(
        source=_source(), manifest=manifest, cache_dir=cache
    )
    reader("H1", 101, 107)
    assert reader.receipts == [receipt]


def test_streamed_span_rejects_missing_or_changed_frame(tmp_path: Path) -> None:
    cache, manifest = _fixture(tmp_path)
    second = cache / manifest["H1", 104]["filename"]
    backup = tmp_path / "backup.hdf5"
    shutil.copyfile(second, backup)
    second.unlink()
    with pytest.raises(ContractError, match="verified local frame bytes"):
        produce_span_receipt(
            detector="H1",
            start=101,
            end=107,
            source=_source(),
            manifest=manifest,
            cache_dir=cache,
        )
    shutil.copyfile(backup, second)
    with h5py.File(second, "r+") as handle:
        handle["strain/Strain"][2] = np.nan
    manifest["H1", 104]["md5"] = hashlib.md5(second.read_bytes()).hexdigest()  # noqa: S324
    with pytest.raises(ContractError, match="samples invalid"):
        produce_span_receipt(
            detector="H1",
            start=101,
            end=107,
            source=_source(),
            manifest=manifest,
            cache_dir=cache,
        )


def test_streamed_span_ignores_samples_outside_frozen_interval(tmp_path: Path) -> None:
    cache, manifest = _fixture(tmp_path)
    first = cache / manifest["H1", 100]["filename"]
    with h5py.File(first, "r+") as handle:
        handle["strain/Strain"][:2] = np.nan
    manifest["H1", 100]["md5"] = hashlib.md5(first.read_bytes()).hexdigest()  # noqa: S324
    receipt = produce_span_receipt(
        detector="H1",
        start=101,
        end=107,
        source=_source(),
        manifest=manifest,
        cache_dir=cache,
    )
    assert (
        verify_background_receipt(
            receipt, source=_source(), manifest=manifest, cache_dir=cache
        )["status"]
        == "PASS_VERIFIED_BACKGROUND_SPAN"
    )


def test_runner_receipt_replays_frozen_target_identity(tmp_path: Path) -> None:
    cache, manifest = _fixture(tmp_path)
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    shutil.move(str(cache), str(parent_dir / "frames"))
    span = {"detector": "H1", "gps_start": 123, "interval_gps": [101, 107]}
    background_receipt = produce_span_receipt(
        detector="H1",
        start=101,
        end=107,
        source=_source(),
        manifest=manifest,
        cache_dir=parent_dir / "frames",
    )
    run_dir = tmp_path / "run"
    path = runner._receipt_path(run_dir, "O3a", span)
    body = {
        "status": "PASS_BACKGROUND_SPAN_REPLAY_ONLY",
        "run": "O3a",
        "target_gps": 123,
        "background": background_receipt,
    }
    _atomic_json(path, runner._seal(body))
    parent_hashes = {
        frame["filename"]: frame["sha256"] for frame in background_receipt["frames"]
    }
    assert (
        runner._verify_one(
            run_dir,
            "O3a",
            span,
            source=_source(),
            manifest=manifest,
            parent_dir=parent_dir,
            frame_sha256=parent_hashes,
        )["background"]
        == background_receipt
    )
    with pytest.raises(ContractError, match="identity changed"):
        runner._verify_one(
            run_dir,
            "O3a",
            {**span, "interval_gps": [100, 107]},
            source=_source(),
            manifest=manifest,
            parent_dir=parent_dir,
            frame_sha256=parent_hashes,
        )
    with pytest.raises(ContractError, match="differs from parent"):
        runner._verify_one(
            run_dir,
            "O3a",
            span,
            source=_source(),
            manifest=manifest,
            parent_dir=parent_dir,
            frame_sha256={name: "0" * 64 for name in parent_hashes},
        )
