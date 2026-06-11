"""Tests for src.preprocessor — signal preprocessing pipeline.

These tests use synthetic data to verify correctness without requiring
real GWOSC downloads.  Focus is on output shapes, value ranges, and
crash-freedom.
"""

from __future__ import annotations

import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from src.core.preprocessor import bandpass, whiten
from src.core.utils import normalize_spectrogram


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_synthetic_timeseries(
    duration: float = 4.0,
    sample_rate: int = 4096,
) -> TimeSeries:
    """Create a synthetic white-noise TimeSeries for testing.

    Args:
        duration: Duration in seconds.
        sample_rate: Sample rate in Hz.

    Returns:
        A gwpy TimeSeries filled with Gaussian white noise, with
        proper sample rate metadata for filter operations.
    """
    n_samples = int(duration * sample_rate)
    rng = np.random.default_rng(seed=42)
    data = rng.standard_normal(n_samples)
    return TimeSeries(
        data,
        sample_rate=sample_rate,
        t0=0,
        channel="TEST:STRAIN",
    )


# ---------------------------------------------------------------------------
# Whitening
# ---------------------------------------------------------------------------


class TestWhiten:
    """Tests for the whiten() function."""

    def test_whiten_does_not_crash(self) -> None:
        """Whitening synthetic data should not raise."""
        ts = _make_synthetic_timeseries(duration=4.0)
        result = whiten(ts)
        assert isinstance(result, TimeSeries)

    def test_whiten_preserves_length(self) -> None:
        """Output length should match input length."""
        ts = _make_synthetic_timeseries(duration=4.0)
        result = whiten(ts)
        assert len(result) == len(ts)

    def test_whiten_too_short_raises(self) -> None:
        """TimeSeries shorter than 1 second should raise ValueError."""
        ts = _make_synthetic_timeseries(duration=0.5)
        with pytest.raises(ValueError, match="too short for whitening"):
            whiten(ts)


# ---------------------------------------------------------------------------
# Bandpass
# ---------------------------------------------------------------------------


class TestBandpass:
    """Tests for the bandpass() function."""

    def test_output_shape_matches_input(self) -> None:
        """Bandpass output should have the same number of samples."""
        ts = _make_synthetic_timeseries(duration=4.0)
        result = bandpass(ts, f_low=20.0, f_high=2000.0)
        assert len(result) == len(ts)

    def test_bandpass_returns_timeseries(self) -> None:
        """Output should be a gwpy TimeSeries."""
        ts = _make_synthetic_timeseries(duration=4.0)
        result = bandpass(ts)
        assert isinstance(result, TimeSeries)


# ---------------------------------------------------------------------------
# Spectrogram normalization
# ---------------------------------------------------------------------------


class TestNormalizeSpectrogram:
    """Tests for normalize_spectrogram in utils."""

    def test_output_in_unit_range(self) -> None:
        """Normalized output should have values in [0, 1]."""
        arr = np.random.default_rng(0).random((64, 64)) * 100 - 30
        result = normalize_spectrogram(arr)
        assert result.min() >= 0.0
        assert result.max() <= 1.0

    def test_output_shape_preserved(self) -> None:
        """Output shape should match input shape."""
        arr = np.random.default_rng(0).random((128, 256))
        result = normalize_spectrogram(arr)
        assert result.shape == arr.shape

    def test_constant_array_returns_zeros(self) -> None:
        """A constant array (max == min) should normalize to all zeros."""
        arr = np.full((32, 32), fill_value=42.0)
        result = normalize_spectrogram(arr)
        np.testing.assert_array_equal(result, np.zeros((32, 32)))

    def test_output_dtype_float32(self) -> None:
        """Output should be float32 for memory efficiency."""
        arr = np.random.default_rng(0).random((64, 64))
        result = normalize_spectrogram(arr)
        assert result.dtype == np.float32
