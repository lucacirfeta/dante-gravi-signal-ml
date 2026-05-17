"""Tests for the synchronized continuous run loop feature."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from astropy.time import Time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import build_parser, parse_stop_date_to_gps, _run_continue_loop


class TestContinueRunCLIArgs:
    """Verify that continuous run arguments are correctly registered and parsed."""

    @pytest.fixture
    def parser(self):
        return build_parser()

    def test_full_analysis_accepts_continue_run_defaults(self, parser):
        args = parser.parse_args(["full-analysis", "--session-id", "20260510_143022"])
        assert args.continue_run is False
        assert args.max_iterations == 10
        assert args.stop_date is None

    def test_full_analysis_accepts_continue_run_explicit(self, parser):
        args = parser.parse_args([
            "full-analysis",
            "--session-id", "20260510_143022",
            "--continue-run",
            "--max-iterations", "5",
            "--stop-date", "2023-06-01 12:00:00"
        ])
        assert args.continue_run is True
        assert args.max_iterations == 5
        assert args.stop_date == "2023-06-01 12:00:00"

    def test_scan_extended_accepts_continue_run_and_start_gps(self, parser):
        args = parser.parse_args([
            "scan-extended",
            "--continue-run",
            "--max-iterations", "3",
            "--start-gps", "1234567890"
        ])
        assert args.continue_run is True
        assert args.max_iterations == 3
        assert args.start_gps == 1234567890


class TestStopDateParsing:
    """Verify that various stop date formats are parsed correctly."""

    def test_parse_gps_directly(self):
        gps = 1369598418
        assert parse_stop_date_to_gps(str(gps)) == gps

    def test_parse_iso_string(self):
        iso_str = "2023-05-24 15:00:00"
        expected_gps = int(Time(iso_str, format="iso", scale="utc").gps)
        assert parse_stop_date_to_gps(iso_str) == expected_gps

    def test_invalid_date_raises_error(self):
        with pytest.raises(ValueError):
            parse_stop_date_to_gps("not-a-date")


class TestOrchestrationLoop:
    """Verify the orchestration loop behavior, iteration limits, and stop dates."""

    @patch("main._find_last_gps")
    @patch("main.cmd_scan_extended")
    @patch("src.full_analysis.run_full_analysis")
    @patch("main.load_config")
    def test_loop_executes_max_iterations(self, mock_load_config, mock_full_analysis, mock_scan_ext, mock_find_gps):
        # Setup mocks
        mock_load_config.return_value = {
            "run_config": {
                "O4a": {"start_date": "2023-05-24 15:00:00", "hours_per_detector": 48}
            }
        }
        # H1 and L1 last GPS times
        mock_find_gps.side_effect = lambda session_id, detector, run: 1000000 + 3600 if detector == "H1" else 1000000 + 7200
        mock_full_analysis.return_value = {"status": {"H1": "OK", "L1": "OK", "timeslide": "OK"}, "reports": {}}

        args = argparse.Namespace(
            workers=2,
            no_cache_raw=True,
            skip_timeslide=False,
            n_runs=20,
            sequential=False
        )

        # Call with max_iterations = 2
        with patch("time.sleep", MagicMock()):
            _run_continue_loop(
                initial_session_id="20260510_143022",
                run="O4a",
                max_iterations=2,
                stop_date_str=None,
                args=args
            )

        # Assertions
        # _find_last_gps should be called for H1 and L1 for each of the 2 iterations
        assert mock_find_gps.call_count == 4
        
        # cmd_scan_extended should be called twice (for the new session IDs)
        assert mock_scan_ext.call_count == 2
        
        # run_full_analysis should be called twice (for the new session IDs)
        assert mock_full_analysis.call_count == 2

        # Verify synchronized start GPS in scan arguments
        # Synchronized GPS is min(ultimo_H1, ultimo_L1) = 1003600
        # Start GPS must be 1003600 + 1 = 1003601
        for call in mock_scan_ext.call_args_list:
            called_args = call[0][0]
            assert called_args.start_gps == 1003601
            assert called_args.hours == 48

    @patch("main._find_last_gps")
    @patch("main.cmd_scan_extended")
    @patch("src.full_analysis.run_full_analysis")
    @patch("main.load_config")
    def test_loop_respects_stop_date(self, mock_load_config, mock_full_analysis, mock_scan_ext, mock_find_gps):
        # Setup mocks
        mock_load_config.return_value = {
            "run_config": {
                "O4a": {"start_date": "2023-05-24 15:00:00", "hours_per_detector": 48}
            }
        }
        # Synchronized GPS ends at 1003600
        mock_find_gps.return_value = 1003600
        
        args = argparse.Namespace()

        # Stop GPS is set to 1003600 (equal to synchronized end)
        # So next iteration start (1003601) will be >= stop_gps, causing it to stop immediately
        with patch("time.sleep", MagicMock()):
            _run_continue_loop(
                initial_session_id="20260510_143022",
                run="O4a",
                max_iterations=5,
                stop_date_str="1003600",
                args=args
            )

        # Should not launch any new scans since the stop condition was met immediately
        assert mock_scan_ext.call_count == 0
        assert mock_full_analysis.call_count == 0
