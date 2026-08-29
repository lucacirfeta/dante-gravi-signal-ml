from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from src.dante_light.evidence import SCORE_ATOL
from src.dante_light import o4a_corrected_performance as performance
from src.dante_light.o4a_corrected_performance import stage_verified_raw_file


def test_verified_staging_is_bounded_and_exact(tmp_path: Path) -> None:
    source = tmp_path / "source.hdf5"
    source.write_bytes(b"raw-strain" * 1024)
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    staging = tmp_path / "stage"
    with stage_verified_raw_file(
        source, staging_dir=staging, expected_sha256=expected
    ) as staged:
        assert staged.read_bytes() == source.read_bytes()
        assert staged.parent == staging.resolve()
        assert list(staging.iterdir()) == [staged]
    assert list(staging.iterdir()) == []


def test_verified_staging_refuses_wrong_hash_and_cleans_up(tmp_path: Path) -> None:
    source = tmp_path / "source.hdf5"
    source.write_bytes(b"immutable")
    staging = tmp_path / "stage"
    with pytest.raises(performance.ContractError, match="SHA-256 mismatch"):
        with stage_verified_raw_file(
            source, staging_dir=staging, expected_sha256="0" * 64
        ):
            pass
    assert list(staging.iterdir()) == []


def test_performance_canary_selection_is_outcome_blind_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_rows = []
    scan_rows = []
    for detector in ("H1", "L1"):
        for span_index in range(3):
            start = float(100_000 + span_index * 4096 + (0 if detector == "H1" else 20_000))
            end = start + 4096.0
            digest = hashlib.sha256(f"{detector}-{start}".encode()).hexdigest()
            raw_rows.append(
                {
                    "detector": detector,
                    "gps_start": start,
                    "gps_end": end,
                    "duration_s": 4096,
                    "sha256": digest,
                    "physical_copies": [
                        {
                            "relative_path": f"{detector}/{start:.0f}.hdf5",
                            "sha256": digest,
                            "size_bytes": 120_000_000,
                        }
                    ],
                }
            )
            for offset in range(32, 32 * 121, 32):
                scan_rows.append(
                    {
                        "detector": detector,
                        "analysis_gps_start": start + offset,
                        "source_span": [start, end],
                        "source_sha256": digest,
                        "overlapping_source_count": 1,
                    }
                )
    monkeypatch.setattr(performance, "_raw_manifest_rows", lambda _root: raw_rows)
    monkeypatch.setattr(
        performance, "iter_scan_identities", lambda _root: iter(scan_rows)
    )
    first = performance._canary_spans(
        Path.cwd(), protocol_digest="a" * 64, spans_per_detector=2, windows_per_span=96
    )
    second = performance._canary_spans(
        Path.cwd(), protocol_digest="a" * 64, spans_per_detector=2, windows_per_span=96
    )
    assert first == second
    assert len(first) == 4
    assert {row["detector"] for row in first} == {"H1", "L1"}
    assert all(len(row["expected_gps_starts"]) == 96 for row in first)
    assert all("score" not in str(row).lower() for row in first)


def test_performance_matrix_preserves_scientific_tolerance() -> None:
    assert SCORE_ATOL == 2.0e-7
    assert [row["id"] for row in performance.CONFIGURATIONS] == [
        "baseline_2x8_direct",
        "mid_4x16_direct",
        "v1_8x32_direct",
        "v1_8x32_ephemeral_stage",
    ]
    assert performance.DB_COMMIT_ROWS == (32, 256, 1024)
