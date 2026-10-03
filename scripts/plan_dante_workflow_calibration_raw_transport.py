"""Public metadata only; does not download or admit raw calibration files."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dante_workflow.calibration_raw_transport import main

if __name__ == "__main__":
    main()
