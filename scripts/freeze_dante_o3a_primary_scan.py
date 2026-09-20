#!/usr/bin/env python3
"""Freeze the provenance-bound O3a primary-scan contract."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_primary_scan import write_scan_contract  # noqa: E402


def main() -> int:
    value = write_scan_contract(root=ROOT)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
