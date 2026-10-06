"""One-shot required-input byte snapshot; no scientific stage."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.dante_workflow.linux_workspace import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
