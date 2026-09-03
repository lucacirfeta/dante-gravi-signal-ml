#!/usr/bin/env python3
"""Replay the post-hoc O4a final-impact attribution audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_final_impact_attribution import build_attribution  # noqa: E402


if __name__ == "__main__":
    print(json.dumps(build_attribution(root=ROOT), indent=2, sort_keys=True))
