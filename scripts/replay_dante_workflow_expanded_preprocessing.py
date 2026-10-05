"""Isolated full calibration preprocessing, no scientific scoring."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dante_workflow.expanded_preprocessing_replay import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
