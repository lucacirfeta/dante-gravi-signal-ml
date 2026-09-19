#!/usr/bin/env python3
"""Freeze or verify the O3a GWOSC inventory and raw acquisition plan."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_raw_acquisition import (  # noqa: E402
    load_acquisition_plan,
    load_source_inventory,
    write_raw_acquisition_freeze,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        acquisition = load_acquisition_plan(root=ROOT)
    else:
        acquisition = write_raw_acquisition_freeze(root=ROOT)
    inventory = load_source_inventory(root=ROOT)
    print(
        json.dumps(
            {
                "status": acquisition["status"],
                "inventory_digest": inventory["inventory_digest"],
                "acquisition_digest": acquisition["acquisition_digest"],
                "source_frame_counts": {
                    detector: inventory["summaries"][detector]["frame_count"]
                    for detector in inventory["detectors"]
                },
                "required_source_frame_counts": {
                    detector: acquisition["detector_plans"][detector][
                        "required_source_frame_count"
                    ]
                    for detector in acquisition["detectors"]
                },
                "downloaded_bytes": acquisition["summary"]["downloaded_bytes"],
                "strain_data_accessed": acquisition["execution_boundary"][
                    "strain_data_accessed"
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
