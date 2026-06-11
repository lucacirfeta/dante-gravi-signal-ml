"""Tests for src.gravity_spy_checker — Gravity Spy cross-check (Phase 3.1).

All tests are offline/mocked — no real Gravity Spy queries in CI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.pipeline_v1_legacy.gravity_spy_checker import (
    cross_check_anomalous_clusters,
    get_anomalous_gps_windows,
    query_gravity_spy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_cluster_report(tmp_path: Path) -> Path:
    """Create a minimal cluster_report.json with 2 anomalous clusters."""
    report = {
        "results": {
            "n_clusters": 4,
            "anomalous_clusters": [2, 3],
            "clusters": {
                "0": {
                    "size": 100,
                    "is_anomalous": False,
                    "sample_files": [
                        "data/spectrograms/o4a/H1/H1_1369598418_1369598450.png",
                    ],
                },
                "2": {
                    "size": 3,
                    "is_anomalous": True,
                    "sample_files": [
                        "data/spectrograms/o4a/H1/H1_1369599346_1369599378.png",
                        "data/spectrograms/o4a/H1/H1_1369599762_1369599794.png",
                    ],
                },
                "3": {
                    "size": 2,
                    "is_anomalous": True,
                    "sample_files": [
                        "data/spectrograms/o4a/H1/H1_1369601202_1369601234.png",
                    ],
                },
            },
        }
    }
    path = tmp_path / "cluster_report.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def mock_metadata(tmp_path: Path) -> Path:
    """Create a minimal encoder metadata JSON."""
    metadata = {
        "model": "dinov2_vits14_reg",
        "files": [
            "data/spectrograms/o4a/H1/H1_1369599346_1369599378.png",
            "data/spectrograms/o4a/H1/H1_1369599762_1369599794.png",
            "data/spectrograms/o4a/H1/H1_1369601202_1369601234.png",
        ],
    }
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# test_get_anomalous_gps_windows
# ---------------------------------------------------------------------------


class TestGetAnomalousGpsWindows:
    """Tests for GPS window extraction from cluster reports."""

    def test_extracts_correct_gps(
        self,
        mock_cluster_report: Path,
        mock_metadata: Path,
    ) -> None:
        """GPS start/end should be correctly parsed from filenames."""
        windows = get_anomalous_gps_windows(
            mock_cluster_report,
            anomalous_cluster_ids=[2, 3],
            metadata_path=mock_metadata,
        )

        assert len(windows) == 3  # 2 from cluster 2 + 1 from cluster 3

        # Check cluster 2 entries
        c2_windows = [w for w in windows if w["cluster_id"] == 2]
        assert len(c2_windows) == 2
        assert c2_windows[0]["gps_start"] == 1369599346
        assert c2_windows[0]["gps_end"] == 1369599378

        assert c2_windows[1]["gps_start"] == 1369599762
        assert c2_windows[1]["gps_end"] == 1369599794

        # Check cluster 3 entry
        c3_windows = [w for w in windows if w["cluster_id"] == 3]
        assert len(c3_windows) == 1
        assert c3_windows[0]["gps_start"] == 1369601202
        assert c3_windows[0]["gps_end"] == 1369601234


# ---------------------------------------------------------------------------
# test_query_gravity_spy
# ---------------------------------------------------------------------------


class TestQueryGravitySpy:
    """Tests for Gravity Spy database queries (mocked)."""

    @patch("gwpy.table.GravitySpyTable")
    def test_returns_empty_list(self, mock_et_cls: MagicMock) -> None:
        """An empty GravitySpyTable should produce an empty result list."""
        mock_table = MagicMock()
        mock_table.__iter__ = MagicMock(return_value=iter([]))
        mock_et_cls.fetch.return_value = mock_table

        result = query_gravity_spy(1369599346, 1369599378, detector="H1")

        assert isinstance(result, list)
        assert len(result) == 0

    @patch("gwpy.table.GravitySpyTable")
    def test_connection_failure_returns_empty(
        self, mock_et_cls: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """ConnectionError should be caught — returns [] and logs warning."""
        mock_et_cls.fetch.side_effect = ConnectionError("timeout")

        with caplog.at_level(logging.WARNING):
            result = query_gravity_spy(1369599346, 1369599378)

        assert result == []
        assert any("failed" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# test_cross_check_anomalous_clusters
# ---------------------------------------------------------------------------


class TestCrossCheckAnomalousClusters:
    """Tests for the full cross-check orchestration."""

    @patch("src.gravity_spy_checker.query_gravity_spy")
    def test_all_unclassified(
        self,
        mock_query: MagicMock,
        mock_cluster_report: Path,
        mock_metadata: Path,
    ) -> None:
        """When Gravity Spy returns no matches, all should be UNCLASSIFIED."""
        mock_query.return_value = []

        results = cross_check_anomalous_clusters(
            mock_cluster_report, mock_metadata, detector="H1"
        )

        assert results["total_anomalous"] == 3
        assert results["unclassified"] == 3
        assert results["classified"] == 0
        assert results["low_confidence"] == 0
        assert all(d["status"] == "UNCLASSIFIED" for d in results["details"])

    @patch("src.gravity_spy_checker.query_gravity_spy")
    def test_all_classified(
        self,
        mock_query: MagicMock,
        mock_cluster_report: Path,
        mock_metadata: Path,
    ) -> None:
        """High-confidence matches should produce status=CLASSIFIED."""
        mock_query.return_value = [
            {
                "peakGPS": 1369599360.0,
                "label": "Blip",
                "confidence": 0.98,
                "snr": 12.5,
                "peak_frequency": 100.0,
                "ifo": "H1",
            }
        ]

        results = cross_check_anomalous_clusters(
            mock_cluster_report, mock_metadata, detector="H1"
        )

        assert results["classified"] == 3
        assert results["unclassified"] == 0
        assert results["low_confidence"] == 0
        assert all(d["status"] == "CLASSIFIED" for d in results["details"])
        assert all(d["gs_label"] == "Blip" for d in results["details"])

    @patch("src.gravity_spy_checker.query_gravity_spy")
    def test_low_confidence(
        self,
        mock_query: MagicMock,
        mock_cluster_report: Path,
        mock_metadata: Path,
    ) -> None:
        """Matches with confidence < 0.95 should be LOW_CONFIDENCE."""
        mock_query.return_value = [
            {
                "peakGPS": 1369599360.0,
                "label": "Blip",
                "confidence": 0.70,
                "snr": 8.0,
                "peak_frequency": 50.0,
                "ifo": "H1",
            }
        ]

        results = cross_check_anomalous_clusters(
            mock_cluster_report, mock_metadata, detector="H1"
        )

        assert results["low_confidence"] == 3
        assert results["classified"] == 0
        assert results["unclassified"] == 0
        assert all(d["status"] == "LOW_CONFIDENCE" for d in results["details"])
