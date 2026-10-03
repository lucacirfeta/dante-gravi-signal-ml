"""Opt-in calibration-only native input recovery, verification and admission."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dante_workflow.calibration_expanded_admission import main

if __name__ == "__main__":
    main()
