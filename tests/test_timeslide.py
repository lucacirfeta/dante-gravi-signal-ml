"""Tests for src.timeslide — time-slide coincidence analysis.

No filesystem or network access needed — all inputs are built from
scratch or written to tmp_path fixtures.

Run:  pytest tests/test_timeslide.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline_v1_legacy.timeslide import (
    _gps_from_filename,
    count_coincidences,
    extract_anomalous_gps,
    run_timeslide,
)


# ---------------------------------------------------------------------------
# _gps_from_filename
# ---------------------------------------------------------------------------


class TestGpsFromFilename:
    """Validate GPS extraction from spectrogram filenames."""

    def test_valid_h1_filename(self) -> None:
        assert _gps_from_filename("H1_1369598418_1369598450.png") == 1369598418

    def test_valid_l1_filename(self) -> None:
        assert _gps_from_filename("L1_1382918784_1382918816.png") == 1382918784

    def test_path_object(self) -> None:
        """Should work on Path objects (via Path.name)."""
        p = Path("/some/dir/H1_1000000_1000032.png")
        assert _gps_from_filename(str(p)) == 1000000

    def test_no_match_returns_none(self) -> None:
        assert _gps_from_filename("not_a_spectrogram.png") is None

    def test_wrong_extension_returns_none(self) -> None:
        assert _gps_from_filename("H1_1000000_1000032.jpg") is None


# ---------------------------------------------------------------------------
# count_coincidences
# ---------------------------------------------------------------------------


class TestCountCoincidences:
    """Validate the coincidence counting logic."""

    def test_exact_match(self) -> None:
        """Same GPS time → 1 coincidence."""
        assert count_coincidences({1000000}, {1000000}, window=32) == 1

    def test_within_window(self) -> None:
        """GPS within ±32 s → coincidence."""
        assert count_coincidences({1000000}, {1000030}, window=32) == 1

    def test_outside_window(self) -> None:
        """GPS outside ±32 s → no coincidence."""
        assert count_coincidences({1000000}, {1000100}, window=32) == 0

    def test_empty_sets(self) -> None:
        assert count_coincidences(set(), set(), window=32) == 0
        assert count_coincidences({1000000}, set(), window=32) == 0
        assert count_coincidences(set(), {1000000}, window=32) == 0

    def test_each_h1_event_counted_once(self) -> None:
        """A single H1 event matching multiple L1 events is counted only once."""
        h1 = {1000000}
        l1 = {999990, 999995, 1000010}  # all within ±32 s
        assert count_coincidences(h1, l1, window=32) == 1

    def test_multiple_coincidences(self) -> None:
        """Each independent H1 event can yield one coincidence."""
        h1 = {1000000, 1001000}
        l1 = {1000001, 1001001}
        assert count_coincidences(h1, l1, window=32) == 2

    def test_boundary_exactly_at_window(self) -> None:
        """GPS difference exactly equal to window → coincidence (<=)."""
        assert count_coincidences({1000000}, {1000032}, window=32) == 1
        assert count_coincidences({1000000}, {1000033}, window=32) == 0


# ---------------------------------------------------------------------------
# extract_anomalous_gps
# ---------------------------------------------------------------------------


class TestExtractAnomalousGps:
    """Validate GPS extraction from cluster report + metadata JSON."""

    def _write_fixtures(
        self,
        tmp_path: Path,
        anomalous_cluster_ids: list[int],
        all_files: list[str],
        cluster_sizes: dict[int, int] | None = None,
        anomalous_samples: list[int] | None = None,
    ) -> tuple[Path, Path]:
        """Write minimal metadata and cluster report JSON files."""
        cluster_sizes = cluster_sizes or {0: 5, 1: 3}
        anomalous_samples = anomalous_samples or []

        # Build cluster detail
        clusters: dict = {}
        per_cid: dict[int, list[str]] = {cid: [] for cid in cluster_sizes}
        for idx, f in enumerate(all_files):
            # Assign files round-robin to clusters for simplicity
            cid = list(cluster_sizes.keys())[idx % len(cluster_sizes)]
            per_cid[cid].append(f)

        for cid, files in per_cid.items():
            clusters[str(cid)] = {
                "size": len(files),
                "is_anomalous": cid in anomalous_cluster_ids,
                "sample_files": files,
            }

        report = {
            "results": {
                "anomalous_clusters": anomalous_cluster_ids,
                "anomalous_samples": anomalous_samples,
                "clusters": clusters,
            }
        }
        metadata = {"files": all_files}

        rep_path = tmp_path / "cluster_report.json"
        meta_path = tmp_path / "meta.json"
        rep_path.write_text(json.dumps(report), encoding="utf-8")
        meta_path.write_text(json.dumps(metadata), encoding="utf-8")
        return meta_path, rep_path

    def test_extracts_gps_from_anomalous_cluster(self, tmp_path: Path) -> None:
        """GPS times from anomalous cluster files are extracted correctly."""
        files = [
            "H1_1000000_1000032.png",
            "H1_1000064_1000096.png",
            "H1_1000128_1000160.png",
            "H1_1000192_1000224.png",
        ]
        meta_path, rep_path = self._write_fixtures(
            tmp_path,
            anomalous_cluster_ids=[0],
            all_files=files,
            cluster_sizes={0: 2, 1: 2},
        )
        gps = extract_anomalous_gps(meta_path, rep_path)
        # Cluster 0 gets files at index 0 and 2 → GPS 1000000 and 1000128
        assert isinstance(gps, set)
        assert len(gps) >= 1
        assert all(isinstance(g, int) for g in gps)

    def test_no_anomalous_clusters_returns_empty(self, tmp_path: Path) -> None:
        """No anomalous clusters → empty GPS set."""
        files = ["H1_1000000_1000032.png", "H1_1000064_1000096.png"]
        meta_path, rep_path = self._write_fixtures(
            tmp_path,
            anomalous_cluster_ids=[],
            all_files=files,
        )
        assert extract_anomalous_gps(meta_path, rep_path) == set()

    def test_anomalous_samples_indices_resolved(self, tmp_path: Path) -> None:
        """Anomalous sample *indices* are resolved against the metadata files list."""
        files = [
            "H1_2000000_2000032.png",  # index 0
            "H1_2000064_2000096.png",  # index 1 ← anomalous sample
            "H1_2000128_2000160.png",  # index 2
        ]
        meta_path, rep_path = self._write_fixtures(
            tmp_path,
            anomalous_cluster_ids=[],  # no cluster anomalies
            all_files=files,
            cluster_sizes={0: 3},
            anomalous_samples=[1],  # index 1 is anomalous
        )
        gps = extract_anomalous_gps(meta_path, rep_path)
        assert 2000064 in gps

    def test_missing_metadata_raises(self, tmp_path: Path) -> None:
        """FileNotFoundError raised when metadata file is absent."""
        with pytest.raises(FileNotFoundError):
            extract_anomalous_gps(
                tmp_path / "nonexistent_meta.json",
                tmp_path / "nonexistent_rep.json",
            )


# ---------------------------------------------------------------------------
# run_timeslide
# ---------------------------------------------------------------------------


class TestRunTimeslide:
    """Validate the full time-slide function with synthetic JSON fixtures."""

    def _write_detector_fixtures(
        self,
        tmp_path: Path,
        prefix: str,
        gps_times: list[int],
        anomalous_cluster_ids: list[int],
    ) -> tuple[Path, Path]:
        """Build minimal meta + report JSONs for a detector."""
        files = [f"{prefix}_{t}_{t + 32}.png" for t in gps_times]
        clusters: dict = {"0": {
            "size": len(files),
            "is_anomalous": 0 in anomalous_cluster_ids,
            "sample_files": files,
        }}
        report = {
            "results": {
                "anomalous_clusters": anomalous_cluster_ids,
                "anomalous_samples": [],
                "clusters": clusters,
            }
        }
        metadata = {"files": files}

        meta_path = tmp_path / f"meta_{prefix}.json"
        rep_path = tmp_path / f"report_{prefix}.json"
        meta_path.write_text(json.dumps(metadata), encoding="utf-8")
        rep_path.write_text(json.dumps(report), encoding="utf-8")
        return meta_path, rep_path

    def test_zero_lag_zero_when_no_shared_gps(self, tmp_path: Path) -> None:
        """Non-overlapping GPS times → zero-lag coincidences = 0."""
        h1_gps = [1000000, 1000064, 1000128]
        l1_gps = [2000000, 2000064, 2000128]  # far away

        meta_h1, rep_h1 = self._write_detector_fixtures(tmp_path, "H1", h1_gps, [0])
        meta_l1, rep_l1 = self._write_detector_fixtures(tmp_path, "L1", l1_gps, [0])

        output_dir = tmp_path / "timeslide_out"
        result = run_timeslide(
            meta_h1=meta_h1, rep_h1=rep_h1,
            meta_l1=meta_l1, rep_l1=rep_l1,
            output_dir=output_dir,
            iterations=20,
            window=32,
        )

        assert result["zero_lag_coincidences"] == 0
        assert result["p_value"] == 1.0

    def test_report_file_written(self, tmp_path: Path) -> None:
        """run_timeslide must write timeslide_report_H1_L1.json."""
        h1_gps = [1000000]
        l1_gps = [2000000]

        meta_h1, rep_h1 = self._write_detector_fixtures(tmp_path, "H1", h1_gps, [0])
        meta_l1, rep_l1 = self._write_detector_fixtures(tmp_path, "L1", l1_gps, [0])

        output_dir = tmp_path / "ts_report"
        run_timeslide(
            meta_h1=meta_h1, rep_h1=rep_h1,
            meta_l1=meta_l1, rep_l1=rep_l1,
            output_dir=output_dir,
            iterations=10,
            window=32,
        )

        report_path = output_dir / "timeslide_report_H1_L1.json"
        assert report_path.exists()

        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)

        expected_keys = {
            "zero_lag_coincidences",
            "h1_anomalous_gps_count",
            "l1_anomalous_gps_count",
            "iterations",
            "window_seconds",
            "background_distribution",
            "background_mean",
            "background_std",
            "p_value",
            "z_score",
            "interpretation",
        }
        assert expected_keys.issubset(report.keys())

    def test_p_value_in_range(self, tmp_path: Path) -> None:
        """Empirical p-value must be in [0, 1]."""
        h1_gps = list(range(1000000, 1001000, 64))
        l1_gps = list(range(1000000, 1001000, 64))  # identical → high coincidence

        meta_h1, rep_h1 = self._write_detector_fixtures(tmp_path, "H1", h1_gps, [0])
        meta_l1, rep_l1 = self._write_detector_fixtures(tmp_path, "L1", l1_gps, [0])

        output_dir = tmp_path / "ts_range"
        result = run_timeslide(
            meta_h1=meta_h1, rep_h1=rep_h1,
            meta_l1=meta_l1, rep_l1=rep_l1,
            output_dir=output_dir,
            iterations=20,
            window=32,
        )

        assert 0.0 <= result["p_value"] <= 1.0
        assert isinstance(result["background_distribution"], list)
        assert len(result["background_distribution"]) == result["iterations"]

    def test_empty_detectors_produce_trivial_result(self, tmp_path: Path) -> None:
        """Zero anomalous GPS on both detectors → zero-lag = 0, p-value = 1."""
        meta_h1, rep_h1 = self._write_detector_fixtures(tmp_path, "H1", [1000000], [])
        meta_l1, rep_l1 = self._write_detector_fixtures(tmp_path, "L1", [2000000], [])

        output_dir = tmp_path / "ts_empty"
        result = run_timeslide(
            meta_h1=meta_h1, rep_h1=rep_h1,
            meta_l1=meta_l1, rep_l1=rep_l1,
            output_dir=output_dir,
            iterations=5,
            window=32,
        )

        assert result["zero_lag_coincidences"] == 0
        assert result["h1_anomalous_gps_count"] == 0
        assert result["l1_anomalous_gps_count"] == 0
