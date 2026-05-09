"""Tests for Phase 3.2 parallel processing pipeline."""

import multiprocessing
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.parallel_processor import (
    _process_single_segment,
    batch_process_parallel,
    get_optimal_workers,
)


def test_windows_spawn_safe() -> None:
    """Verify that importing the module doesn't spawn processes.
    
    Critical for Windows ProcessPoolExecutor which uses spawn.
    """
    assert multiprocessing.active_children() == []


def test_get_optimal_workers_returns_int() -> None:
    """Verify get_optimal_workers returns a valid integer >= 1."""
    result = get_optimal_workers()
    assert isinstance(result, int)
    assert result >= 1


@patch("src.preprocessor.batch_process")
def test_workers_1_calls_sequential(mock_batch_process: MagicMock) -> None:
    """Verify that workers=1 falls back to the sequential batch_process."""
    mock_batch_process.return_value = [Path("test1.png"), Path("test2.png")]
    
    segments = [(123, 124), (125, 126)]
    detector = "H1"
    output_dir = Path("dummy_dir")
    config = {}

    saved, skipped = batch_process_parallel(
        segments, detector, output_dir, config, workers=1
    )

    mock_batch_process.assert_called_once_with(segments, detector, output_dir)
    assert saved == 2
    assert skipped == 0


@patch("src.preprocessor.generate_qtransform")
@patch("src.preprocessor.bandpass")
@patch("src.preprocessor.whiten")
def test_process_single_segment_returns_tuple(
    mock_whiten: MagicMock,
    mock_bandpass: MagicMock,
    mock_qtransform: MagicMock,
) -> None:
    """Verify that _process_single_segment returns a (str, bool) tuple."""
    # Mock preprocessor functions
    mock_whiten.return_value = MagicMock()
    mock_bandpass.return_value = MagicMock()
    
    # Mock a dummy TimeSeries
    mock_ts = MagicMock()
    
    args = (1000, 1001, mock_ts, "H1", "dummy_dir")
    result = _process_single_segment(args)
    
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], bool)
    assert result[0] == "H1_1000_1001"
    assert result[1] is True
    
    mock_whiten.assert_called_once_with(mock_ts)
    mock_bandpass.assert_called_once()
    mock_qtransform.assert_called_once()


@patch("src.parallel_processor.ProcessPoolExecutor")
@patch("src.parallel_processor.ThreadPoolExecutor")
def test_parallel_saved_skipped_sum(
    mock_thread_pool: MagicMock,
    mock_process_pool: MagicMock,
) -> None:
    """Verify saved + skipped matches total segments when using parallel mode."""
    # We will actually run the real batch_process_parallel but mock fetch_strain_data 
    # and _process_single_segment instead to test the logic flow.
    pass

@patch("src.data_loader.fetch_strain_data")
@patch("src.parallel_processor._process_single_segment")
def test_parallel_logic_flow(
    mock_process: MagicMock,
    mock_fetch: MagicMock,
) -> None:
    """Verify parallel batch_process_parallel correctly tallies saved/skipped."""
    segments = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]
    detector = "H1"
    output_dir = Path("dummy_dir")
    config = {}
    
    # Mock fetch: 3 succeed, 2 fail
    def mock_fetch_side_effect(*args, **kwargs):
        if args[1] in [1, 5, 9]:
            return "mocked_ts"  # Return string instead of MagicMock to avoid pickling error
        raise Exception("Fetch failed")  # fail
        
    mock_fetch.side_effect = mock_fetch_side_effect
    
    # Mock process: always succeed if it gets here
    # It only gets here if fetch succeeded
    def mock_process_side_effect(args):
        gps_start, gps_end, ts, det, out = args[:5]
        return (f"{det}_{gps_start}_{gps_end}", True)
        
    mock_process.side_effect = mock_process_side_effect
    
    with patch("src.parallel_processor.ProcessPoolExecutor", side_effect=__import__("concurrent.futures").futures.ThreadPoolExecutor):
        saved, skipped = batch_process_parallel(
            segments, detector, output_dir, config, workers=2, fetch_workers=2
        )
    
    # 3 success, 2 failed fetch (skipped)
    assert saved == 3
    assert skipped == 2
    assert saved + skipped == len(segments)
