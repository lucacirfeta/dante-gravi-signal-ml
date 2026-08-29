from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from src.core.patch_producer import (
    IncompleteContextError,
    PatchProducer,
    RawBlockConflictError,
    load_frozen_raw_manifest,
    read_complete_context,
)


def _write(path: Path, *, start: float, duration: float, value: float) -> str:
    TimeSeries(
        np.full(int(duration * 16), value, dtype=np.float64),
        sample_rate=16,
        t0=start,
    ).write(path, format="hdf5", path="strain")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_complete_context_stitches_adjacent_files(tmp_path: Path) -> None:
    first = tmp_path / "H1_1000_1064.hdf5"
    second = tmp_path / "H1_1064_1128.hdf5"
    first_hash = _write(first, start=1000, duration=64, value=1.0)
    second_hash = _write(second, start=1064, duration=64, value=2.0)

    result = read_complete_context(
        [(1000.0, 1064.0, first), (1064.0, 1128.0, second)],
        gps_start=1028.0,
        gps_end=1068.0,
        sample_rate_hz=16,
        expected_sha256={first: first_hash, second: second_hash},
    )

    assert result.series.size == 40 * 16
    assert float(result.series.t0.value) == 1028.0
    assert np.all(result.series.value[: 36 * 16] == 1.0)
    assert np.all(result.series.value[36 * 16 :] == 2.0)
    assert [item.path for item in result.sources] == [first, second]


def test_complete_context_fails_closed_on_gap(tmp_path: Path) -> None:
    first = tmp_path / "L1_1000_1064.hdf5"
    second = tmp_path / "L1_1065_1129.hdf5"
    _write(first, start=1000, duration=64, value=1.0)
    _write(second, start=1065, duration=64, value=2.0)
    with pytest.raises(IncompleteContextError, match="gap"):
        read_complete_context(
            [(1000.0, 1064.0, first), (1065.0, 1129.0, second)],
            gps_start=1028.0,
            gps_end=1068.0,
            sample_rate_hz=16,
        )


def test_complete_context_rejects_conflicting_duplicate_spans(tmp_path: Path) -> None:
    first = tmp_path / "copy_a.hdf5"
    second = tmp_path / "copy_b.hdf5"
    _write(first, start=1000, duration=64, value=1.0)
    _write(second, start=1000, duration=64, value=2.0)
    with pytest.raises(RawBlockConflictError, match="conflicting copies"):
        read_complete_context(
            [(1000.0, 1064.0, first), (1000.0, 1064.0, second)],
            gps_start=1004.0,
            gps_end=1044.0,
            sample_rate_hz=16,
        )


def test_complete_context_accepts_byte_identical_duplicate_spans(tmp_path: Path) -> None:
    first = tmp_path / "copy_a.hdf5"
    second = tmp_path / "copy_b.hdf5"
    _write(first, start=1000, duration=64, value=1.0)
    second.write_bytes(first.read_bytes())
    result = read_complete_context(
        [(1000.0, 1064.0, first), (1000.0, 1064.0, second)],
        gps_start=1004.0,
        gps_end=1044.0,
        sample_rate_hz=16,
    )
    assert result.sources[0].path == min(first, second)


def test_complete_context_rejects_manifest_hash_mismatch(tmp_path: Path) -> None:
    block = tmp_path / "H1_1000_1064.hdf5"
    _write(block, start=1000, duration=64, value=1.0)
    with pytest.raises(RawBlockConflictError, match="SHA-256 mismatch"):
        read_complete_context(
            [(1000.0, 1064.0, block)],
            gps_start=1004.0,
            gps_end=1044.0,
            sample_rate_hz=16,
            expected_sha256={block: "0" * 64},
        )


def test_frozen_raw_manifest_binds_available_copies(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    block = raw_root / "session" / "H1_1000_1064.hdf5"
    block.parent.mkdir()
    digest = _write(block, start=1000, duration=64, value=1.0)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "copy_count": 1,
                "detector": "H1",
                "duration_s": 64,
                "gps_end": 1064,
                "gps_start": 1000,
                "physical_copies": [
                    {
                        "relative_path": "session/H1_1000_1064.hdf5",
                        "sha256": digest,
                        "size_bytes": block.stat().st_size,
                    }
                ],
                "sha256": digest,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    frozen = load_frozen_raw_manifest(
        manifest, raw_root=raw_root, detector="H1"
    )
    assert frozen.target_files == (block.resolve(),)
    assert frozen.expected_sha256[block.resolve()] == digest
    assert len(frozen.entries) == 1


def test_frozen_raw_manifest_rejects_missing_declared_copy(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "copy_count": 1,
                "detector": "L1",
                "duration_s": 64,
                "gps_end": 1064,
                "gps_start": 1000,
                "physical_copies": [
                    {
                        "relative_path": "session/L1_1000_1064.hdf5",
                        "sha256": "0" * 64,
                        "size_bytes": 1,
                    }
                ],
                "sha256": "0" * 64,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(IncompleteContextError, match="no physical copy"):
        load_frozen_raw_manifest(manifest, raw_root=raw_root, detector="L1")


def test_patch_producer_uses_adjacent_file_for_boundary_padding(
    tmp_path: Path, monkeypatch
) -> None:
    first = tmp_path / "H1_1000_1064.hdf5"
    second = tmp_path / "H1_1064_1128.hdf5"
    _write(first, start=1000, duration=64, value=1.0)
    _write(second, start=1064, duration=64, value=2.0)
    captured = []

    class ImmediateFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    class ImmediateExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def submit(self, function, *args, **kwargs):
            return ImmediateFuture(function(*args, **kwargs))

    def capture_worker(values, t0, dt, name, seg_start, seg_end):
        captured.append(
            {
                "values": np.asarray(values),
                "t0": float(t0),
                "seg_start": float(seg_start),
                "seg_end": float(seg_end),
            }
        )
        return int(seg_start), np.zeros((2, 2, 3), dtype=np.uint8)

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr("src.core.patch_producer._worker_preprocess", capture_worker)
    producer = PatchProducer(
        tmp_path,
        "H1",
        segment_duration=32.0,
        sample_rate=16,
        workers=1,
        batch_size=1,
    )
    producer.resume_gps = 1031.0
    gps, images = next(iter(producer))
    assert gps == [1032]
    assert len(images) == 1
    boundary = captured[0]
    assert boundary["t0"] == 1028.0
    assert boundary["seg_start"] == 1032.0
    assert boundary["seg_end"] == 1064.0
    assert boundary["values"].size == 40 * 16
    assert np.all(boundary["values"][: 36 * 16] == 1.0)
    assert np.all(boundary["values"][36 * 16 :] == 2.0)


def test_manifest_producer_records_unscorable_component_edges(
    tmp_path: Path, monkeypatch
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    block = raw_root / "session" / "H1_1000_1064.hdf5"
    block.parent.mkdir()
    digest = _write(block, start=1000, duration=64, value=1.0)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "copy_count": 1,
                "detector": "H1",
                "duration_s": 64,
                "gps_end": 1064,
                "gps_start": 1000,
                "physical_copies": [
                    {
                        "relative_path": "session/H1_1000_1064.hdf5",
                        "sha256": digest,
                        "size_bytes": block.stat().st_size,
                    }
                ],
                "sha256": digest,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class ImmediateFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    class ImmediateExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def submit(self, function, *args, **kwargs):
            return ImmediateFuture(function(*args, **kwargs))

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(
        "src.core.patch_producer._worker_preprocess",
        lambda values, t0, dt, name, start, end: (
            int(start),
            np.zeros((2, 2, 3), dtype=np.uint8),
        ),
    )
    producer = PatchProducer(
        raw_root,
        "H1",
        segment_duration=32,
        sample_rate=16,
        workers=1,
        batch_size=1,
        raw_manifest=manifest,
        raw_root=raw_root,
        manifest_targets=True,
        incomplete_context_policy="record_and_skip",
    )
    assert list(producer) == []
    assert [row["gps_start"] for row in producer.excluded_incomplete_context] == [
        1000.0,
        1032.0,
    ]


def test_manifest_producer_applies_frozen_explicit_exclusions(
    tmp_path: Path, monkeypatch
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    block = raw_root / "session" / "H1_1000_1096.hdf5"
    block.parent.mkdir()
    digest = _write(block, start=1000, duration=96, value=1.0)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "copy_count": 1,
                "detector": "H1",
                "duration_s": 96,
                "gps_end": 1096,
                "gps_start": 1000,
                "physical_copies": [
                    {
                        "relative_path": "session/H1_1000_1096.hdf5",
                        "sha256": digest,
                        "size_bytes": block.stat().st_size,
                    }
                ],
                "sha256": digest,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class ImmediateFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

    class ImmediateExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def submit(self, function, *args, **kwargs):
            return ImmediateFuture(function(*args, **kwargs))

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", ImmediateExecutor)
    monkeypatch.setattr(
        "src.core.patch_producer._worker_preprocess",
        lambda values, t0, dt, name, start, end: (
            int(start),
            np.zeros((2, 2, 3), dtype=np.uint8),
        ),
    )
    producer = PatchProducer(
        raw_root,
        "H1",
        segment_duration=32,
        sample_rate=16,
        workers=1,
        batch_size=1,
        raw_manifest=manifest,
        raw_root=raw_root,
        manifest_targets=True,
        incomplete_context_policy="record_and_skip",
        excluded_gps_starts=[1032.0],
    )
    assert list(producer) == []
    assert [row["gps_start"] for row in producer.excluded_explicit] == [1032.0]
    assert {row["gps_start"] for row in producer.excluded_incomplete_context} == {
        1000.0,
        1064.0,
    }


def test_manifest_bound_worker_failure_is_fail_closed(
    tmp_path: Path, monkeypatch
) -> None:
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    block = raw_root / "session" / "H1_1000_1096.hdf5"
    block.parent.mkdir()
    digest = _write(block, start=1000, duration=96, value=1.0)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "copy_count": 1,
                "detector": "H1",
                "duration_s": 96,
                "gps_end": 1096,
                "gps_start": 1000,
                "physical_copies": [
                    {
                        "relative_path": "session/H1_1000_1096.hdf5",
                        "sha256": digest,
                        "size_bytes": block.stat().st_size,
                    }
                ],
                "sha256": digest,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class ImmediateFuture:
        def result(self):
            return 1032, None

    class ImmediateExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def submit(self, function, *args, **kwargs):
            return ImmediateFuture()

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", ImmediateExecutor)
    producer = PatchProducer(
        raw_root,
        "H1",
        segment_duration=32,
        sample_rate=16,
        workers=1,
        batch_size=1,
        raw_manifest=manifest,
        raw_root=raw_root,
        manifest_targets=True,
        incomplete_context_policy="record_and_skip",
        worker_failure_policy="raise",
    )
    with pytest.raises(RuntimeError, match="preprocessing failed"):
        list(producer)
    assert block.is_file()
