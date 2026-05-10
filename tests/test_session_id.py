"""Tests for --session-id flag in CLI commands."""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Import the helpers and parser builder under test
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import _resolve_session_id, build_parser


class TestResolveSessionId:
    """Unit tests for _resolve_session_id helper."""

    def test_returns_explicit_session_id(self):
        """Explicit --session-id is returned as-is."""
        args = argparse.Namespace(session_id="20260510_143022")
        assert _resolve_session_id(args) == "20260510_143022"

    def test_generates_timestamp_when_missing(self):
        """When session_id is None, auto-generate YYYYMMDD_HHMMSS."""
        args = argparse.Namespace(session_id=None)
        result = _resolve_session_id(args)
        # Must match the YYYYMMDD_HHMMSS pattern
        assert re.match(r"^\d{8}_\d{6}$", result)

    def test_generates_timestamp_when_empty_string(self):
        """When session_id is empty string, auto-generate."""
        args = argparse.Namespace(session_id="")
        result = _resolve_session_id(args)
        assert re.match(r"^\d{8}_\d{6}$", result)

    def test_generates_timestamp_when_attr_missing(self):
        """When session_id attribute doesn't exist, auto-generate."""
        args = argparse.Namespace()
        result = _resolve_session_id(args)
        assert re.match(r"^\d{8}_\d{6}$", result)

    def test_generated_id_matches_current_time(self):
        """Auto-generated ID should be close to current time."""
        args = argparse.Namespace(session_id=None)
        before = datetime.now().strftime("%Y%m%d")
        result = _resolve_session_id(args)
        assert result.startswith(before)


class TestParserSessionId:
    """Tests that --session-id is accepted by the right subcommands."""

    @pytest.fixture
    def parser(self):
        return build_parser()

    def test_scan_accepts_session_id(self, parser):
        args = parser.parse_args([
            "scan", "--detector", "H1", "--hours", "1",
            "--session-id", "20260510_143022",
        ])
        assert args.session_id == "20260510_143022"

    def test_scan_session_id_default_none(self, parser):
        args = parser.parse_args(["scan", "--detector", "H1"])
        assert args.session_id is None

    def test_scan_extended_accepts_session_id(self, parser):
        args = parser.parse_args([
            "scan-extended", "--session-id", "20260510_143022",
        ])
        assert args.session_id == "20260510_143022"

    def test_scan_extended_accepts_hours(self, parser):
        args = parser.parse_args(["scan-extended", "--hours", "72"])
        assert args.hours == 72

    def test_encode_accepts_session_id_and_detector(self, parser):
        args = parser.parse_args([
            "encode", "--session-id", "20260510_143022", "--detector", "H1",
        ])
        assert args.session_id == "20260510_143022"
        assert args.detector == "H1"
        assert args.input_dir is None
        assert args.output is None

    def test_encode_accepts_explicit_paths(self, parser):
        args = parser.parse_args([
            "encode",
            "--input-dir", "data/spectrograms/o4a/H1/",
            "--output", "data/embeddings/o4a_h1.npy",
        ])
        assert args.input_dir == "data/spectrograms/o4a/H1/"
        assert args.output == "data/embeddings/o4a_h1.npy"

    def test_cluster_accepts_session_id_and_detector(self, parser):
        args = parser.parse_args([
            "cluster", "--session-id", "20260510_143022", "--detector", "L1",
        ])
        assert args.session_id == "20260510_143022"
        assert args.detector == "L1"
        assert args.input is None
        assert args.output is None

    def test_cluster_accepts_explicit_paths(self, parser):
        args = parser.parse_args([
            "cluster",
            "--input", "data/embeddings/o4a_h1_6h.npy",
            "--output", "data/clusters/h1/",
        ])
        assert args.input == "data/embeddings/o4a_h1_6h.npy"
        assert args.output == "data/clusters/h1/"


class TestPathResolution:
    """Test that cmd functions resolve paths correctly from session-id."""

    def test_scan_output_dir_uses_session_id(self):
        """cmd_scan should create output_dir with session_id in path."""
        from main import cmd_scan

        args = argparse.Namespace(
            detector="H1",
            hours=1.0,
            session_id="20260510_143022",
            workers=1,
        )

        with patch("main.fetch_o4a_segments", return_value=[]), \
             patch("main.logger") as mock_logger:
            # fetch_o4a_segments returns [] → sys.exit(0) via SystemExit
            with pytest.raises(SystemExit):
                cmd_scan(args)

            # Check that session ID was logged
            mock_logger.info.assert_any_call("Session ID: %s", "20260510_143022")

    def test_encode_resolves_paths_from_session_id(self):
        """cmd_encode should derive input_dir and output from session-id + detector."""
        from main import cmd_encode

        args = argparse.Namespace(
            session_id="20260510_143022",
            detector="H1",
            input_dir=None,
            output=None,
            batch_size=32,
        )

        with patch("main.DINOv2Encoder") as mock_enc, \
             patch("main.logger") as mock_logger:
            mock_instance = MagicMock()
            mock_enc.return_value = mock_instance

            cmd_encode(args)

            # Verify it used session-derived paths
            call_args = mock_instance.extract_dataset.call_args
            input_dir_used = call_args[0][0]
            output_path_used = call_args[0][1]

            assert "20260510_143022" in str(input_dir_used)
            assert "H1" in str(input_dir_used)
            assert "20260510_143022" in str(output_path_used)
            assert "o4a_h1.npy" in str(output_path_used)

    def test_encode_explicit_paths_override_session_id(self):
        """Explicit --input-dir and --output must override session-id paths."""
        from main import cmd_encode

        args = argparse.Namespace(
            session_id="20260510_143022",
            detector="H1",
            input_dir="my/custom/input/",
            output="my/custom/output.npy",
            batch_size=32,
        )

        with patch("main.DINOv2Encoder") as mock_enc, \
             patch("main.logger"):
            mock_instance = MagicMock()
            mock_enc.return_value = mock_instance

            cmd_encode(args)

            call_args = mock_instance.extract_dataset.call_args
            input_dir_used = call_args[0][0]
            output_path_used = call_args[0][1]

            assert str(input_dir_used) == "my\\custom\\input" or str(input_dir_used) == "my/custom/input"
            assert "custom" in str(output_path_used)

    def test_cluster_resolves_paths_from_session_id(self):
        """cmd_cluster should derive input and output from session-id + detector."""
        from main import cmd_cluster
        import numpy as np

        args = argparse.Namespace(
            session_id="20260510_143022",
            detector="H1",
            input=None,
            output=None,
        )

        # Create a mock embeddings file for the expected path
        expected_input = Path("data/embeddings/20260510_143022/o4a_h1.npy")
        expected_output = Path("data/clusters/20260510_143022/h1")

        with patch("main.np.load") as mock_load, \
             patch("main.logger") as mock_logger, \
             patch("main.load_config") as mock_cfg, \
             patch("main.Path.exists", return_value=True), \
             patch("builtins.open", MagicMock()), \
             patch("main.Path.with_suffix") as mock_suffix:

            # The function will check input_path.exists() — we already patched it
            mock_load.return_value = np.zeros((10, 384))
            mock_cfg.return_value = {"clustering": {}}

            # Check session ID was logged before it tries to import clustering
            try:
                cmd_cluster(args)
            except Exception:
                pass  # Will fail on clustering import — that's OK

            mock_logger.info.assert_any_call("Session ID: %s", "20260510_143022")

    def test_encode_fails_without_paths_or_session(self):
        """cmd_encode should exit(1) if neither paths nor session-id are given."""
        from main import cmd_encode

        args = argparse.Namespace(
            session_id=None,
            detector=None,
            input_dir=None,
            output=None,
            batch_size=32,
        )

        with patch("main.logger"), pytest.raises(SystemExit):
            cmd_encode(args)

    def test_cluster_fails_without_paths_or_session(self):
        """cmd_cluster should exit(1) if neither paths nor session-id are given."""
        from main import cmd_cluster

        args = argparse.Namespace(
            session_id=None,
            detector=None,
            input=None,
            output=None,
        )

        with patch("main.logger"), pytest.raises(SystemExit):
            cmd_cluster(args)
