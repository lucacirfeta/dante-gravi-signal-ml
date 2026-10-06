#!/usr/bin/env python3
"""Explicit new-only mirror and I/O measurement; no calibration launch."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dante_workflow.storage_probe import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
