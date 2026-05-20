"""Tests for cmd_fetch_raw and continue/resume modes in main.py."""
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from main import cmd_fetch_raw, build_parser


@pytest.fixture
def temp_raw_dir(tmp_path):
    """Fixture that yields a clean temp path for raw data."""
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    yield raw_dir
    if raw_dir.exists():
        shutil.rmtree(raw_dir)


@patch("main._fetch_single_block")
@patch("main.load_config")
@patch("main._run_start_gps")
def test_cmd_fetch_raw_fresh(
    mock_run_start_gps, mock_load_config, mock_fetch_block, temp_raw_dir
):
    """Verify that a fresh fetch-raw starts at the run start GPS and aligned to 4096."""
    mock_load_config.return_value = {}
    mock_run_start_gps.return_value = 1000000  # Will be aligned to (1000000 // 4096) * 4096 = 999424
    mock_fetch_block.return_value = (True, "Fetched block")

    parser = build_parser()
    args = parser.parse_args([
        "fetch-raw",
        "--detector", "H1",
        "--hours", "1.0",
        "--output-dir", str(temp_raw_dir),
        "--segment-duration", "4096",
        "--no-cache-raw", "False"
    ])

    cmd_fetch_raw(args)

    # Output dir should be temp_raw_dir / "999424"
    expected_out_dir = temp_raw_dir / "999424"
    assert expected_out_dir.exists()
    assert expected_out_dir.is_dir()

    # Verify that mock_fetch_block was called
    assert mock_fetch_block.called


@patch("main._fetch_single_block")
@patch("main.load_config")
@patch("main._run_start_gps")
def test_cmd_fetch_raw_continue(
    mock_run_start_gps, mock_load_config, mock_fetch_block, temp_raw_dir
):
    """Verify that fetch-raw --continue detects last directory and files to resume."""
    mock_load_config.return_value = {}
    mock_fetch_block.return_value = (True, "Fetched block")

    # Create dummy folders and files
    folder_1 = temp_raw_dir / "1003520" # 245 * 4096
    folder_1.mkdir(parents=True)
    (folder_1 / "H1_1003520_1007616.hdf5").touch()

    folder_2 = temp_raw_dir / "2007040" # 490 * 4096
    folder_2.mkdir(parents=True)
    # This is the highest folder GPS, and we put a dummy file representing H1 download progress up to 2011136
    (folder_2 / "H1_2007040_2011136.hdf5").touch()
    (folder_2 / "H1_2011136_2015232.hdf5").touch()

    parser = build_parser()
    args = parser.parse_args([
        "fetch-raw",
        "--detector", "H1",
        "--hours", "2.28",  # 2.28 hours is 8208 seconds
        "--output-dir", str(temp_raw_dir),
        "--segment-duration", "4096",
        "--no-cache-raw", "False",
        "--continue"
    ])

    cmd_fetch_raw(args)

    # It should have found folder_2 (2007040), read the highest end GPS (2015232),
    # which is already a multiple of 4096 (492 * 4096 = 2015232),
    # and created a new folder at temp_raw_dir / "2015232"
    expected_out_dir = temp_raw_dir / "2015232"
    assert expected_out_dir.exists()
    assert expected_out_dir.is_dir()

    # The fetch should have started at 2015232
    first_call_args = mock_fetch_block.call_args_list[0][0]
    # args: (detector, start, end, output_dir, retry_delays, base_delay, cache_raw)
    assert first_call_args[0] == "H1"
    assert first_call_args[1] == 2015232
    assert first_call_args[2] == 2015232 + 4096
    assert first_call_args[3] == expected_out_dir
