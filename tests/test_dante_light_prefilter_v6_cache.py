from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from src.dante_light.prefilter_v6_cache import (
    build_phase_b_cache,
    cache_path,
    ensure_interval,
    load_phase_b_downloads,
)
from src.dante_light.prefilter_v5_protocol import repository_reference
from scripts.verify_dante_light_prefilter_v6_cache import verify


ROOT = Path(__file__).resolve().parents[1]


def _fake_fetch(detector: str, start: float, end: float, sample_rate_hz: int) -> TimeSeries:
    del detector
    values = np.linspace(-1.0, 1.0, int((end - start) * sample_rate_hz), dtype=np.float64)
    return TimeSeries(values, t0=start, sample_rate=sample_rate_hz)


def test_download_manifest_opens_phase_b_only() -> None:
    contract, identities = load_phase_b_downloads(root=ROOT)
    assert contract["scope"]["phase_c_access_allowed"] is False
    assert len(identities) == 1023
    assert {row["detector"] for row in identities} == {"H1", "L1"}
    assert all(row["gps_end"] - row["gps_start"] == 40.0 for row in identities)


def test_interval_cache_is_atomic_validated_and_resumable(tmp_path: Path) -> None:
    identity = {"detector": "H1", "block_index": 334000, "gps_start": 1368064004.0, "gps_end": 1368064044.0}
    first = ensure_interval(
        identity=identity,
        cache_root=tmp_path,
        sample_rate_hz=4096,
        fetch=_fake_fetch,
        retries=1,
    )
    assert first["source"] == "gwosc_open_data"
    assert cache_path(tmp_path, identity).is_file()
    second = ensure_interval(
        identity=identity,
        cache_root=tmp_path,
        sample_rate_hz=4096,
        fetch=lambda *_: pytest.fail("resumable cache unexpectedly fetched again"),
        retries=1,
    )
    assert second["source"] == "existing_v6_cache"
    assert second["strain_values_sha256"] == first["strain_values_sha256"]


def test_smoke_cache_records_no_sealed_access(tmp_path: Path) -> None:
    references = {
        "cache_implementation": repository_reference(ROOT, ROOT / "src/dante_light/prefilter_v6_cache.py"),
        "test_driver": repository_reference(ROOT, Path(__file__).resolve()),
    }
    summary = build_phase_b_cache(
        root=ROOT,
        cache_root=tmp_path / "cache",
        artifact_path=tmp_path / "summary.json",
        implementation_references=references,
        workers=1,
        retries=1,
        fetch=_fake_fetch,
        limit=2,
    )
    assert summary["status"] == "SMOKE_ONLY"
    assert summary["cached_interval_count"] == 2
    assert summary["phase_c_rows_accessed"] == []
    assert summary["phase_d_rows_accessed"] == []
    assert summary["o4b_rows_accessed"] == []
    checked = verify(
        cache_root=(tmp_path / "cache").resolve(),
        artifact_path=(tmp_path / "summary.json").resolve(),
        deep=True,
        allow_smoke=True,
    )
    assert checked["status"] == "PASS"
    assert checked["cached_interval_count"] == 2
