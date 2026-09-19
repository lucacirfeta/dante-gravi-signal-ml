from __future__ import annotations

import hashlib
import json
from pathlib import Path

import h5py
import pytest

from src.core.patch_producer import load_frozen_raw_manifest
from src.dante_light.o3a_raw_download import (
    _Progress,
    _canonical_verified_record,
    _download_one,
    build_preflight,
    build_raw_manifest_rows,
    validate_hdf5_metadata,
    write_preflight,
)
from src.dante_light.contracts import ContractError


ROOT = Path(__file__).resolve().parents[1]


def _small_gwosc_file(path: Path, *, duration_s: int = 1) -> bytes:
    with h5py.File(path, "w") as handle:
        strain = handle.create_dataset(
            "strain/Strain", shape=(duration_s * 4096,), dtype="f8"
        )
        strain.attrs["Xspacing"] = 1.0 / 4096
    return path.read_bytes()


def test_preflight_binds_all_frames_and_checks_disk(tmp_path: Path) -> None:
    size = 123_456

    def fake_head(item: dict) -> dict:
        return {
            "content_length_bytes": size,
            "etag": '"test"',
            "last_modified": None,
            "resolved_url": item["url"],
        }

    value = build_preflight(
        root=ROOT,
        raw_root=tmp_path,
        workers=4,
        reserve_bytes=0,
        head_fetcher=fake_head,
    )
    assert value["status"] == "PASS_O3A_RAW_DOWNLOAD_PREFLIGHT"
    assert value["expected_file_count"] == 726
    assert value["expected_download_bytes"] == 726 * size
    assert value["execution_boundary"]["hdf5_bytes_downloaded"] == 0
    assert value["execution_boundary"]["strain_data_accessed"] is False


def test_preflight_is_immutable_and_reused_for_same_run(tmp_path: Path) -> None:
    calls = 0

    def fake_head(item: dict) -> dict:
        nonlocal calls
        calls += 1
        return {
            "content_length_bytes": 1,
            "etag": None,
            "last_modified": None,
            "resolved_url": item["url"],
        }

    first, path = write_preflight(
        root=ROOT,
        raw_root=tmp_path,
        workers=4,
        reserve_bytes=0,
        head_fetcher=fake_head,
    )
    first_bytes = path.read_bytes()
    assert calls == 726

    def forbidden_head(item: dict) -> dict:
        raise AssertionError(f"unexpected repeated HEAD request for {item['url']}")

    second, second_path = write_preflight(
        root=ROOT,
        raw_root=tmp_path,
        workers=4,
        reserve_bytes=0,
        head_fetcher=forbidden_head,
    )
    assert second_path == path
    assert second == first
    assert path.read_bytes() == first_bytes


def test_verified_ledger_ignores_attempt_local_transport_source() -> None:
    base = {"detector": "H1", "gps_start": 1000, "sha256": "a" * 64}
    downloaded = _canonical_verified_record({**base, "source": "GWOSC_HTTPS"})
    replayed = _canonical_verified_record(
        {**base, "source": "VERIFIED_EXISTING_FINAL"}
    )
    assert downloaded == replayed == base


def test_hdf5_metadata_and_raw_manifest_are_patch_producer_compatible(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    target = raw_root / "H1" / "frame.hdf5"
    target.parent.mkdir(parents=True)
    payload = _small_gwosc_file(target)
    item = {
        "detector": "H1",
        "duration_s": 1,
        "gps_start": 1000,
        "gps_end": 1001,
        "target_relative_path": "H1/frame.hdf5",
    }
    assert validate_hdf5_metadata(target, item) == {
        "sample_rate_hz": 4096,
        "sample_count": 4096,
        "metadata_only_validation": True,
    }
    digest = hashlib.sha256(payload).hexdigest()
    rows = build_raw_manifest_rows(
        [{**item, "size_bytes": len(payload), "sha256": digest}]
    )
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    frozen = load_frozen_raw_manifest(
        manifest, raw_root=raw_root, detector="H1"
    )
    assert frozen.target_files == (target.resolve(),)
    assert frozen.expected_sha256[target.resolve()] == digest


def test_interrupted_download_resumes_with_valid_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.hdf5"
    payload = _small_gwosc_file(source)
    raw_root = tmp_path / "raw"
    target = raw_root / "L1" / "frame.hdf5"
    target.parent.mkdir(parents=True)
    split = len(payload) // 2
    partial = target.with_suffix(".hdf5.part")
    partial.write_bytes(payload[:split])
    observed_headers: list[dict[str, str]] = []

    class FakeResponse:
        status_code = 206
        headers = {"Content-Range": f"bytes {split}-{len(payload) - 1}/{len(payload)}"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def raise_for_status(self) -> None:
            return None

        def iter_content(self, chunk_size: int):
            del chunk_size
            yield payload[split:]

    def fake_get(url: str, **kwargs):
        del url
        observed_headers.append(dict(kwargs["headers"]))
        return FakeResponse()

    monkeypatch.setattr("src.dante_light.o3a_raw_download.requests.get", fake_get)
    progress = _Progress(tmp_path / "progress.json", 1, len(payload))
    item = {
        "detector": "L1",
        "duration_s": 1,
        "filename": "frame.hdf5",
        "gps_start": 2000,
        "gps_end": 2001,
        "target_relative_path": "L1/frame.hdf5",
        "url": "https://data.gwosc.org/frame.hdf5",
        "content_length_bytes": None,
        "content_sha256": None,
        "download_status": "NOT_DOWNLOADED",
    }
    record = _download_one(
        item=item,
        source={"content_length_bytes": len(payload)},
        raw_root=raw_root,
        retries=1,
        progress=progress,
    )
    assert observed_headers == [{"Range": f"bytes={split}-"}]
    assert target.read_bytes() == payload
    assert not partial.exists()
    assert record["source"] == "GWOSC_HTTPS"
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert "content_sha256" not in record
    assert "download_status" not in record


def test_download_refuses_to_overwrite_divergent_final(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    target = raw_root / "H1" / "frame.hdf5"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"divergent")
    progress = _Progress(tmp_path / "progress.json", 1, 100)
    item = {
        "detector": "H1",
        "duration_s": 1,
        "filename": "frame.hdf5",
        "gps_start": 1000,
        "gps_end": 1001,
        "target_relative_path": "H1/frame.hdf5",
        "url": "https://data.gwosc.org/frame.hdf5",
    }
    with pytest.raises(ContractError, match="divergent existing"):
        _download_one(
            item=item,
            source={"content_length_bytes": 100},
            raw_root=raw_root,
            retries=1,
            progress=progress,
        )
    assert target.read_bytes() == b"divergent"
