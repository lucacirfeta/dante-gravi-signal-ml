"""Verify the frozen DANTE-Light v7 contract, identities, and seal."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_freeze import verify_freeze


if __name__ == "__main__":
    print(json.dumps(verify_freeze(ROOT), indent=2, sort_keys=True))
