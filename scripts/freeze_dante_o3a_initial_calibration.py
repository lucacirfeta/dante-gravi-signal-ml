#!/usr/bin/env python3
"""Freeze the approved O3a initial-calibration selector and plan."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_initial_calibration import (  # noqa: E402
    load_selector_contract,
    write_initial_calibration_freeze,
)


def main() -> int:
    plan = write_initial_calibration_freeze(root=ROOT)
    contract = load_selector_contract(root=ROOT)
    print(
        json.dumps(
            {
                "status": plan["status"],
                "contract_digest": contract["contract_digest"],
                "plan_digest": plan["plan_digest"],
                "planned_identity_stream_sha256": plan[
                    "ordered_planned_identity_stream_sha256"
                ],
                "detectors": {
                    detector: {
                        key: value
                        for key, value in detector_plan.items()
                        if key
                        in {
                            "candidate_block_count",
                            "selected_candidate_blocks",
                            "planned_rows",
                            "bootstrap_rows",
                            "point_only_tail_rows",
                        }
                    }
                    for detector, detector_plan in plan["detector_plans"].items()
                },
                "strain_data_accessed": plan["strain_data_accessed"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
