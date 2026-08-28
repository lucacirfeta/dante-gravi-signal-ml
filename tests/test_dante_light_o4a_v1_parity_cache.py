from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_v1_parity_cache import (
    _cache_path, ensure_cached, load_frozen_missing,
)
from src.dante_light.prefilter_v5_protocol import sha256_path


ROOT = Path(__file__).resolve().parents[1]


def test_missing_cache_targets_are_portable_and_data_loader_discoverable() -> None:
    _contract, header, missing = load_frozen_missing(ROOT)
    assert len(missing) == header["counts"]["missing_from_raw_mirror"] == 169
    assert sum(row["local_stitch"]["complete_padded_coverage"] for row in missing) == 162
    for row in missing:
        relative = row["cache_target"]["relative_path"]
        start, end = map(int, row["required_padded_interval_gps"])
        detector = row["window"]["detector"]
        assert relative == f"raw/{detector}/{detector}_{start}_{end}.hdf5"
        assert row["data_quality"] == {
            "frozen_cbc_cat1": True,
            "hardware_injection_overlap": False,
            "snapshot_path": "config/dante_light_prefilter_v4_segments.json",
        }


def test_cache_fetch_writes_and_revalidates_exact_padded_strain(tmp_path: Path) -> None:
    TimeSeries = pytest.importorskip("gwpy.timeseries").TimeSeries
    _contract, _header, missing = load_frozen_missing(ROOT)
    row = missing[0]
    start, end = map(float, row["required_padded_interval_gps"])

    def fetch(_detector: str, got_start: float, got_end: float, rate: int):
        assert (got_start, got_end, rate) == (start, end, 4096)
        return TimeSeries(np.zeros(int((end - start) * rate)), sample_rate=rate, t0=start)

    first = ensure_cached(row, cache_root=tmp_path, raw_root=tmp_path / "absent", sample_rate_hz=4096, fetch=fetch, retries=1)
    second = ensure_cached(
        row, cache_root=tmp_path, raw_root=tmp_path / "absent", sample_rate_hz=4096,
        fetch=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected fetch")), retries=1,
    )
    assert first["source"] == "gwosc_open_data"
    assert second["source"] == "existing_parity_cache"
    assert first["file_sha256"] == second["file_sha256"]
    assert first["strain_values_sha256"] == second["strain_values_sha256"]
    body = dict(second); digest = body.pop("record_digest")
    assert digest == canonical_json_sha256(body)
    assert _cache_path(tmp_path, row).is_file()


def test_cache_stitches_verified_adjacent_local_files_without_network(tmp_path: Path) -> None:
    TimeSeries = pytest.importorskip("gwpy.timeseries").TimeSeries
    _contract, _header, missing = load_frozen_missing(ROOT)
    row = json.loads(json.dumps(next(item for item in missing if item["local_stitch"]["complete_padded_coverage"])))
    start, end = map(float, row["required_padded_interval_gps"])
    boundary = start + 36.0
    raw_root = tmp_path / "raw-root"
    components = []
    for index, (left, right) in enumerate(((start - 32.0, boundary), (boundary, end + 32.0))):
        relative = Path("session") / f"part-{index}.hdf5"
        path = raw_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        TimeSeries(np.zeros(int((right - left) * 4096)), sample_rate=4096, t0=left).write(path, format="hdf5", path="strain")
        components.append({"relative_path": relative.as_posix(), "file_sha256": sha256_path(path), "file_interval_gps": [left, right]})
    row["local_stitch"] = {"complete_padded_coverage": True, "components": components}
    record = ensure_cached(
        row, cache_root=tmp_path / "cache", raw_root=raw_root, sample_rate_hz=4096,
        fetch=lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected network")), retries=1,
    )
    assert record["source"] == "verified_local_raw_stitch"
    assert record["sample_count"] == 40 * 4096


def test_cache_path_rejects_escape(tmp_path: Path) -> None:
    _contract, _header, missing = load_frozen_missing(ROOT)
    row = json.loads(json.dumps(missing[0]))
    row["cache_target"]["relative_path"] = "../escape.hdf5"
    with pytest.raises(ContractError, match="invalid parity cache"):
        _cache_path(tmp_path, row)
