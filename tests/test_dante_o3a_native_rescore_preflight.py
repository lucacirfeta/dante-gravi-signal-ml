"""Outcome-minimal native-rescore work-list tests."""

from __future__ import annotations

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light import o3a_native_rescore_preflight as preflight


def _fixture(monkeypatch):
    sources = {
        ("H1", 1000): [{"detector": "H1", "filename": "h.hdf5", "sha256": "a" * 64, "size_bytes": 7}],
        ("L1", 1000): [{"detector": "L1", "filename": "l.hdf5", "sha256": "b" * 64, "size_bytes": 11}],
        ("H1", 2000): [{"detector": "H1", "filename": "h.hdf5", "sha256": "a" * 64, "size_bytes": 7}],
    }
    monkeypatch.setattr(
        preflight,
        "_source_rows_for_context",
        lambda *, detector, gps, **_kwargs: sources[(detector, gps)],
    )
    scan = {
        key: {
            "detector": key[0],
            "gps_start": key[1],
            "is_candidate": key == ("H1", 2000),
            "identity_digest": "c" * 64,
            "expected_image_sha256": "d" * 64,
        }
        for key in sources
    }
    calibration = [
        {
            "detector": detector,
            "gps_start": 1000,
            "context_sources": sources[(detector, 1000)],
            "context_sources_digest": canonical_json_sha256(sources[(detector, 1000)]),
        }
        for detector in ("H1", "L1")
    ]
    frames = {detector: [{"gps_start": 0}] for detector in ("H1", "L1")}
    kwargs = dict(
        scan_rows=scan,
        calibration_rows=calibration,
        frames_by_detector=frames,
        raw_frame_rows={},
        expected_calibration_rows_by_detector={"H1": 1, "L1": 1},
    )
    return kwargs


def test_exact_work_manifest_and_no_outcome(monkeypatch):
    rows, audit = preflight.assemble_work_rows(**_fixture(monkeypatch))
    assert audit["calibration_rows_by_detector"] == {"H1": 1, "L1": 1}
    assert audit["candidate_rows_by_detector"] == {"H1": 1, "L1": 0}
    assert audit["row_total"] == 3
    assert audit["unique_source_frames"] == 2
    assert audit["unique_source_bytes"] == 18
    assert audit["score_or_class_read"] is False
    assert all("score" not in row and "class" not in row for row in rows)


def test_changed_calibration_context_is_rejected(monkeypatch):
    kwargs = _fixture(monkeypatch)
    kwargs["calibration_rows"][0]["context_sources_digest"] = "0" * 64
    with pytest.raises(ContractError, match="sources changed"):
        preflight.assemble_work_rows(**kwargs)


def test_calibration_seed_overlap_is_rejected(monkeypatch):
    kwargs = _fixture(monkeypatch)
    kwargs["scan_rows"][("H1", 1000)]["is_candidate"] = True
    with pytest.raises(ContractError, match="calibration identity"):
        preflight.assemble_work_rows(**kwargs)


def test_duplicate_calibration_identity_is_rejected(monkeypatch):
    kwargs = _fixture(monkeypatch)
    kwargs["calibration_rows"].append(kwargs["calibration_rows"][0])
    with pytest.raises(ContractError, match="calibration identity"):
        preflight.assemble_work_rows(**kwargs)


def test_divergent_frame_identity_is_rejected(monkeypatch):
    kwargs = _fixture(monkeypatch)
    # The candidate points at a frame with the same detector/name but a
    # different digest; it must not be silently treated as a cache hit.
    original = preflight._source_rows_for_context

    def divergent(*, detector, gps, **rest):
        value = original(detector=detector, gps=gps, **rest)
        if (detector, gps) == ("H1", 2000):
            return [{**value[0], "sha256": "e" * 64}]
        return value

    monkeypatch.setattr(preflight, "_source_rows_for_context", divergent)
    with pytest.raises(ContractError, match="divergent identity"):
        preflight.assemble_work_rows(**kwargs)
