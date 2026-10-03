"""Explicit opt-in productive calibration preflight; no legacy CLI changes."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.dante_workflow.production_calibration import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
