#!/usr/bin/env python3
"""Checkout wrapper for :mod:`src.dante_workflow.ui.cli`."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.ui.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(default_repository_root=ROOT))
