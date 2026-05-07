"""Tests for src.data_loader — GWOSC data fetching and segment management.

These tests use mocking to avoid network dependencies in CI.
No internet connection is required to run this test suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.data_loader import (
    _validate_detector,
    fetch_o4a_segments,
    fetch_strain_data,
)


# ---------------------------------------------------------------------------
# Detector validation
# ---------------------------------------------------------------------------


class TestValidateDetector:
    """Tests for _validate_detector."""

    def test_valid_detectors(self) -> None:
        """All supported detectors should pass validation."""
        for det in ("H1", "L1", "V1"):
            _validate_detector(det)  # Should not raise

    def test_invalid_detector_raises(self) -> None:
        """An unsupported detector should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported detector"):
            _validate_detector("X1")


# ---------------------------------------------------------------------------
# fetch_strain_data (mocked)
# ---------------------------------------------------------------------------


class TestFetchStrainData:
    """Tests for fetch_strain_data with mocked gwpy calls."""

    @patch("src.data_loader.TimeSeries.fetch_open_data")
    def test_returns_timeseries(self, mock_fetch: MagicMock) -> None:
        """fetch_strain_data should return whatever gwpy returns."""
        mock_ts = MagicMock()
        mock_ts.__len__ = MagicMock(return_value=131072)
        mock_ts.duration.value = 32.0
        mock_fetch.return_value = mock_ts

        result = fetch_strain_data("H1", 1126259446, 1126259478)

        mock_fetch.assert_called_once_with(
            "H1", 1126259446, 1126259478,
            sample_rate=4096, verbose=False, cache=True,
        )
        assert result is mock_ts

    def test_invalid_detector_raises(self) -> None:
        """fetch_strain_data should reject unsupported detectors."""
        with pytest.raises(ValueError, match="Unsupported detector"):
            fetch_strain_data("Z9", 0, 32)

    @patch("src.data_loader.TimeSeries.fetch_open_data")
    def test_network_error_wrapped(self, mock_fetch: MagicMock) -> None:
        """Network errors should be wrapped in RuntimeError."""
        mock_fetch.side_effect = ConnectionError("timeout")

        with pytest.raises(RuntimeError, match="Failed to fetch strain data"):
            fetch_strain_data("H1", 1126259446, 1126259478)


# ---------------------------------------------------------------------------
# fetch_o4a_segments
# ---------------------------------------------------------------------------


class TestFetchO4aSegments:
    """Tests for fetch_o4a_segments."""

    def test_returns_list_of_tuples(self) -> None:
        """Output should be a list of (start, end) integer tuples."""
        segments = fetch_o4a_segments("H1", duration_hours=0.01)

        assert isinstance(segments, list)
        for seg in segments:
            assert isinstance(seg, tuple)
            assert len(seg) == 2
            start, end = seg
            assert isinstance(start, int)
            assert isinstance(end, int)
            assert end > start

    def test_segment_length_default(self) -> None:
        """Each segment should be exactly 32 seconds by default."""
        segments = fetch_o4a_segments("H1", duration_hours=0.01)
        for start, end in segments:
            assert end - start == 32

    def test_custom_segment_length(self) -> None:
        """Custom segment_length should be respected."""
        segments = fetch_o4a_segments(
            "L1", duration_hours=0.01, segment_length=64
        )
        for start, end in segments:
            assert end - start == 64

    def test_invalid_duration_raises(self) -> None:
        """Non-positive duration should raise ValueError."""
        with pytest.raises(ValueError, match="duration_hours must be positive"):
            fetch_o4a_segments("H1", duration_hours=-1)

    def test_segments_within_o4a_window(self) -> None:
        """All segments should fall within the O4a GPS window."""
        from src.data_loader import _O4A_START, _O4A_END

        segments = fetch_o4a_segments("H1", duration_hours=0.5)
        for start, end in segments:
            assert start >= _O4A_START
            assert end <= _O4A_END
