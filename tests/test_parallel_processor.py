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
    # batch_process is expected to return a tuple (saved, skipped) now or a list?
    # Wait, the fallback in original batch_process_parallel was:
    # saved_paths = batch_process(segments, detector, output_dir)
    # return len(saved_paths), len(segments) - len(saved_paths)
    # BUT the user's new batch_process_parallel does:
    # return batch_process(segments, detector, output_dir, config)
    # So we assume batch_process returns (saved, skipped). We'll mock it to return (2, 0)
    mock_batch_process.return_value = (2, 0)
    
    segments = [(123, 124), (125, 126)]
    detector = "H1"
    output_dir = Path("dummy_dir")
    config = {}

    saved, skipped = batch_process_parallel(
        segments, detector, output_dir, config, workers=1
    )

    mock_batch_process.assert_called_once_with(segments, detector, output_dir, config)
    assert saved == 2
    assert skipped == 0


@patch("src.preprocessor.generate_qtransform")
@patch("src.preprocessor.bandpass")
@patch("src.preprocessor.whiten")
@patch("src.data_loader.fetch_strain_data")
def test_process_single_segment_returns_tuple(
    mock_fetch: MagicMock,
    mock_whiten: MagicMock,
    mock_bandpass: MagicMock,
    mock_qtransform: MagicMock,
) -> None:
    """Verify that _process_single_segment returns a (str, bool) tuple."""
    # Mock preprocessor functions
    mock_fetch.return_value = MagicMock()
    mock_whiten.return_value = MagicMock()
    mock_bandpass.return_value = MagicMock()
    
    args = (1000, 1001, "H1", "dummy_dir", {}, True)
    result = _process_single_segment(args)
    
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], bool)
    assert result[0] == "H1_1000_1001"
    assert result[1] is True
    
    mock_fetch.assert_called_once_with("H1", 1000, 1001, sample_rate=4096, cache_raw=True)
    mock_whiten.assert_called_once()
    mock_bandpass.assert_called_once()
    mock_qtransform.assert_called_once()


@patch("src.parallel_processor._process_single_segment")
def test_parallel_saved_skipped_sum(
    mock_process: MagicMock,
) -> None:
    """Verify saved + skipped matches total segments when using parallel mode."""
    segments = [(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)]
    detector = "H1"
    output_dir = Path("dummy_dir")
    config = {}
    
    def mock_process_side_effect(args):
        gps_start, gps_end, det, out, cfg, cache_raw = args
        success = gps_start not in [5, 9]
        return (f"{det}_{gps_start}_{gps_end}", success)
        
    mock_process.side_effect = mock_process_side_effect
    
    # Run with workers=3 so it uses ProcessPoolExecutor
    # We patch ProcessPoolExecutor with ThreadPoolExecutor to make patching _process_single_segment easier across threads
    with patch("src.parallel_processor.ProcessPoolExecutor", side_effect=__import__("concurrent.futures").futures.ThreadPoolExecutor):
        saved, skipped = batch_process_parallel(
            segments, detector, output_dir, config, workers=3, fetch_workers=2
        )
    
    assert saved == 3
    assert skipped == 2
    assert saved + skipped == len(segments)

