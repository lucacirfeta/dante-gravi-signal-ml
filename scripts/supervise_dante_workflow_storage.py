#!/usr/bin/env python3
"""One isolated mirror, then one gated measurement; no scientific stage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dante_workflow.storage_supervisor import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
