from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from gwpy.timeseries import TimeSeries

from src.dante_light.o4a_corrected_execution import (
    _missing_intervals,
    _validate_calibration_shard,
    acquire_missing_calibration_inputs,
    validate_acquisition_manifest,
)
from src.dante_light.o4a_corrected_protocol import OUTPUT_REL, ROOT, validate_corrected_protocol


def test_corrected_missing_calibration_identities_are_frozen() -> None:
    rows = _missing_intervals(ROOT)
    assert len(rows) == 15
    assert sum(row["detector"] == "H1" for row in rows) == 11
    assert sum(row["detector"] == "L1" for row in rows) == 4
    assert len({(row["detector"], row["gps_start"], row["gps_end"]) for row in rows}) == 15


def test_corrected_acquisition_is_content_addressed_and_reusable(tmp_path: Path) -> None:
    calls = []

    def fetcher(detector: str, start: int, end: int) -> TimeSeries:
        calls.append((detector, start, end))
        offset = 1.0 if detector == "H1" else 2.0
        values = np.arange((end - start) * 4096, dtype=np.float64) + offset
        return TimeSeries(values, t0=start, sample_rate=4096, name=f"{detector}:STRAIN")

    manifest, run_dir = acquire_missing_calibration_inputs(
        root=ROOT,
        external_root=tmp_path,
        fetcher=fetcher,
        compact_path=tmp_path / "compact.json",
    )
    assert len(calls) == 15
    assert manifest["record_count"] == 15
    protocol = validate_corrected_protocol(
        json.loads((ROOT / OUTPUT_REL).read_text(encoding="utf-8")), ROOT
    )
    validate_acquisition_manifest(manifest, run_dir=run_dir, protocol=protocol)
    repeated, repeated_dir = acquire_missing_calibration_inputs(
        root=ROOT,
        external_root=tmp_path,
        fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("unexpected refetch")),
        compact_path=tmp_path / "compact.json",
    )
    assert repeated_dir == run_dir
    assert repeated == manifest
    assert (tmp_path / "compact.json").is_file()


def test_corrected_calibration_shard_uses_exact_empirical_p99() -> None:
    expected = [
        {"session_id": 1, "detector": "H1", "catalog_gps_start": float(index)}
        for index in range(4)
    ]
    rows = [
        {
            **identity,
            "corrected_primary_score": float(index) / 10.0,
            "corrected_score_float32_hex": np.float32(float(index) / 10.0).tobytes().hex(),
        }
        for index, identity in enumerate(expected)
    ]
    body = {
        "schema_version": 1,
        "status": "COMPLETE",
        "run_key": "frozen",
        "session_id": 1,
        "detector": "H1",
        "row_count": 4,
        "empirical_p99": float(np.percentile([0.0, 0.1, 0.2, 0.3], 99.0)),
        "threshold_rule": "numpy.percentile(scores, 99.0)",
        "rows": rows,
    }
    from src.dante_light.contracts import canonical_json_sha256

    shard = {**body, "shard_digest": canonical_json_sha256(body)}
    assert _validate_calibration_shard(
        shard, expected_rows=expected, run_key="frozen"
    ) == shard
