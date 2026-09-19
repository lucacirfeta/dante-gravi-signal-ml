#!/usr/bin/env python3
"""Freeze compact O3a scan and calibration-proposal identity universes."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_population_geometry import (  # noqa: E402
    write_identity_universes,
)


def main() -> int:
    value = write_identity_universes(root=ROOT)
    print(
        json.dumps(
            {
                "status": value["status"],
                "manifest_digest": value["manifest_digest"],
                "counts": {
                    role: item["counts_by_detector"]
                    for role, item in value["roles"].items()
                },
                "selection_boundary": value["selection_boundary"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
