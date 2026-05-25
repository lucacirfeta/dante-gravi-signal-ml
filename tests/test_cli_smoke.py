import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from main import build_parser

def test_all_commands_help():
    """Test that every registered command can parse --help without crashing."""
    parser = build_parser()
    
    # Extract all subparsers from the main parser
    subparsers_actions = [
        action for action in parser._actions 
        if isinstance(action, getattr(argparse, '_SubParsersAction', type(parser._actions[1])))
    ]
    
    if not subparsers_actions:
        # Fallback if we can't find subparsers
        commands = [
            "fetch", "scan", "scan-extended", "full-analysis", "full-analysis-report",
            "last-gps", "fetch-raw", "reprocess-spectrograms", "encode", "cluster",
            "report", "stability", "ablation", "crosscheck", "build-reference",
            "morphcheck", "timeslide", "build-indomain-reference", "validate-reference",
            "benchmark-clustering", "benchmark-methods", "calibrate-threshold",
            "calibrate-loglikelihood", "scan-live", "analyze-similarity"
        ]
    else:
        commands = list(subparsers_actions[0].choices.keys())
        
    for cmd in commands:
        result = subprocess.run(
            [sys.executable, "main.py", cmd, "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, f"Command '{cmd} --help' failed with output:\n{result.stderr}"
        assert f"usage: gravi-signal-ml {cmd}" in result.stdout or f"usage: main.py {cmd}" in result.stdout

