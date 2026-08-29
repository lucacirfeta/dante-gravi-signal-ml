from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from gwpy.timeseries import TimeSeries

from src.dante_light.o4a_corrected_execution import (
    _CorrectedContextReader,
    _find_reusable_acquired_input,
    _missing_intervals,
    _ScanIdentityLookup,
    _validate_calibration_shard,
    acquire_missing_calibration_inputs,
    validate_acquisition_manifest,
)
from src.dante_light.o4a_corrected_protocol import OUTPUT_REL, ROOT, validate_corrected_protocol


def test_corrected_missing_calibration_identities_are_frozen() -> None:
    rows = _missing_intervals(ROOT)
    assert len(rows) == 28
    assert sum(row["detector"] == "H1" for row in rows) == 18
    assert sum(row["detector"] == "L1" for row in rows) == 10
    assert len({(row["detector"], row["gps_start"], row["gps_end"]) for row in rows}) == 28


def test_prior_acquisition_reuse_is_content_verified(tmp_path: Path) -> None:
    from src.dante_light.contracts import canonical_json_sha256
    from src.dante_light.o4a_corrected_execution import _strain_record

    old_run = tmp_path / "inputs_old"
    data_dir = old_run / "missing_calibration"
    data_dir.mkdir(parents=True)
    path = data_dir / "H1_100_140_pending.hdf5"
    TimeSeries(
        np.arange(40 * 4096, dtype=np.float64),
        t0=100,
        sample_rate=4096,
        name="H1:STRAIN",
    ).write(path, format="hdf5")
    record = {
        **_strain_record(path, detector="H1", start=100, end=140),
        "relative_path": path.relative_to(old_run).as_posix(),
        "source": "GWOSC_OPEN_DATA_VIA_GWPY_FETCH_OPEN_DATA",
    }
    body = {
        "schema_version": 1,
        "status": "COMPLETE_CONTENT_ADDRESSED_INPUTS",
        "protocol_digest": "old",
        "protocol_reference": {"path": "old", "sha256": "0" * 64},
        "record_count": 1,
        "records": [record],
        "record_digest": canonical_json_sha256([record]),
        "network_fetch_was_outcome_blind": True,
        "scores_or_labels_accessed_during_fetch": [],
    }
    manifest = {**body, "manifest_digest": canonical_json_sha256(body)}
    (old_run / "acquisition_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    reusable = _find_reusable_acquired_input(
        external_root=tmp_path,
        current_run_dir=tmp_path / "inputs_new",
        detector="H1",
        start=100,
        end=140,
    )
    assert reusable is not None
    assert reusable[0] == path
    assert reusable[1]["origin_manifest_digest"] == manifest["manifest_digest"]


def test_calibration_slice_reader_matches_canonical_stitch(tmp_path: Path) -> None:
    import hashlib
    import h5py

    from src.core.patch_producer import load_frozen_raw_manifest, read_complete_context

    raw_root = tmp_path / "raw"
    session = raw_root / "session"
    session.mkdir(parents=True)
    entries = []
    for start, offset in ((1000, 0.0), (1064, 1.0)):
        path = session / f"H1_{start}_{start + 64}.hdf5"
        values = np.arange(64 * 4096, dtype=np.float64) + offset
        with h5py.File(path, "w") as handle:
            dataset = handle.create_dataset("Strain", data=values)
            dataset.attrs.update(
                {
                    "dx": 1.0 / 4096.0,
                    "name": "Strain",
                    "unit": "",
                    "x0": start,
                    "xunit": "s",
                }
            )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(
            {
                "copy_count": 1,
                "detector": "H1",
                "duration_s": 64,
                "gps_end": start + 64,
                "gps_start": start,
                "physical_copies": [
                    {
                        "relative_path": f"session/{path.name}",
                        "sha256": digest,
                        "size_bytes": path.stat().st_size,
                    }
                ],
                "sha256": digest,
            }
        )
    manifest_path = tmp_path / "manifest.jsonl"
    manifest_path.write_text(
        "".join(json.dumps(row) + "\n" for row in entries), encoding="utf-8"
    )
    frozen = load_frozen_raw_manifest(
        manifest_path, raw_root=raw_root, detector="H1"
    )
    reader = object.__new__(_CorrectedContextReader)
    reader.base = {"H1": frozen}
    sliced = reader._read_manifest_slice(detector="H1", start=1060, end=1100)
    canonical = read_complete_context(
        frozen.entries,
        gps_start=1060,
        gps_end=1100,
        sample_rate_hz=4096,
        expected_sha256=frozen.expected_sha256,
    )
    np.testing.assert_array_equal(sliced.series.value, canonical.series.value)
    assert [(row.used_start, row.used_end) for row in sliced.sources] == [
        (1060.0, 1064.0),
        (1064.0, 1100.0),
    ]


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
    assert len(calls) == 28
    assert manifest["record_count"] == 28
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
        {
            "session_id": 1,
            "detector": "H1",
            "catalog_gps_start": float(index),
            "analysis_gps_start": float(index) + 4.0,
            "required_padded_interval": [float(index), float(index) + 40.0],
            "historical_context_disposition": "HISTORICAL_FULL_SYMMETRIC_4S",
            "historical_context_interval": [float(index), float(index) + 40.0],
            "historical_source_span": [0.0, 100.0],
            "replay_disposition": "REQUIRE_EXACT_REPLAY",
        }
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


def test_scan_lookup_preserves_overlapping_session_memberships() -> None:
    lookup = _ScanIdentityLookup(root=ROOT)
    row = lookup.lookup("L1", 1369489440.0)
    assert row["overlapping_source_count"] == 2
    assert len(row["historical_session_ids"]) >= 1
    assert row["context_disposition"] == "COMPLETE_SYMMETRIC_4S_VALID_RAW"
    assert row["exclusion_reasons"] == []
    edge = lookup.lookup("H1", 1369569504.0)
    assert edge["context_disposition"] == "EXCLUDED_COMPONENT_EDGE"
    assert edge["exclusion_reasons"] == ["INCOMPLETE_SYMMETRIC_4S_CONTEXT"]
    invalid_edge = lookup.lookup("H1", 1368977408.0)
    assert (
        invalid_edge["context_disposition"]
        == "EXCLUDED_INVALID_RAW_OR_WHITENING_CONTEXT"
    )
    assert "INCOMPLETE_SYMMETRIC_4S_CONTEXT" in invalid_edge["exclusion_reasons"]
    assert "TARGET_NONFINITE" in invalid_edge["exclusion_reasons"]
