"""Read-only metadata feasibility for the candidate local L1 follow-up."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.dante_light.o3a_l1_local_followup import metadata_preflight  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(metadata_preflight(), indent=2))
