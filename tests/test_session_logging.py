"""Tests for session-specific essential logging."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Insert workspace root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import set_session_log_file, close_session_log, setup_logger, session_path
from main import main


@pytest.fixture
def temp_session_log_path(tmp_path):
    """Fixture returning a path for a temporary session log file."""
    return tmp_path / "data" / "runs" / "o4a" / "test_session" / "logs" / "session.log"


def test_session_logging_creates_file_and_filters_correctly(temp_session_log_path):
    """Verify that set_session_log_file creates the log file and filters messages properly."""
    # Ensure it's clean
    close_session_log()

    # Initialize a test logger
    logger = setup_logger("test_session_logging_module")
    
    # Configure session logging
    set_session_log_file(temp_session_log_path)
    
    assert temp_session_log_path.parent.exists()
    assert temp_session_log_path.exists()
    
    # Log different levels
    logger.debug("This is a debug message - should be filtered")
    logger.info("This is an info message - should be filtered")
    logger.warning("This is a warning message - MUST be included")
    logger.error("This is an error message - MUST be included")
    
    # Special session boundary logs
    logger.info("=== COMMAND START: test ===", extra={"session_key": True})
    
    # Clean up
    close_session_log()
    
    # Read the log file contents
    log_content = temp_session_log_path.read_text(encoding="utf-8")
    
    assert "This is a debug message" not in log_content
    assert "This is an info message" not in log_content
    assert "This is a warning message" in log_content
    assert "This is an error message" in log_content
    assert "=== COMMAND START: test ===" in log_content


def test_close_session_log_removes_handler(temp_session_log_path):
    """Verify that close_session_log properly detaches the handler and stops logging to the file."""
    close_session_log()
    
    logger = setup_logger("test_session_cleanup")
    
    set_session_log_file(temp_session_log_path)
    logger.warning("Message 1 - should be in log")
    
    close_session_log()
    
    logger.warning("Message 2 - should NOT be in log")
    
    log_content = temp_session_log_path.read_text(encoding="utf-8")
    assert "Message 1" in log_content
    assert "Message 2" not in log_content


@patch("main.build_parser")
@patch("sys.argv", ["main.py", "scan", "--detector", "H1"])
def test_main_wrapper_session_logging(mock_build_parser, temp_session_log_path):
    """Test that main() correctly wraps subcommands in session logging if they support session_id."""
    close_session_log()
    
    # Set up mock parser and arguments
    mock_parser = MagicMock()
    mock_build_parser.return_value = mock_parser
    
    mock_func = MagicMock()
    mock_args = argparse.Namespace(
        session_id="test_session_123",
        run="O4a",
        func=mock_func
    )
    mock_parser.parse_args.return_value = mock_args
    
    # Run main() which should trigger wrapper
    with patch("main.session_path", return_value=temp_session_log_path.parent.parent):
        main()
        
    assert mock_func.called
    
    # Check that session log file was created and contains command start/end
    assert temp_session_log_path.exists()
    log_content = temp_session_log_path.read_text(encoding="utf-8")
    
    assert "=== COMMAND START: scan ===" in log_content
    assert "=== COMMAND END: scan (SUCCESS) ===" in log_content
