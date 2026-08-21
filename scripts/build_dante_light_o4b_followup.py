"""Build or execute the frozen DANTE-Light O4b escalation follow-up."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.followup import (
    build_morphology_gallery,
    build_followup_manifest,
    fetch_and_crossmatch_gwtc5,
    run_physical_followup,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=("manifest", "physical", "catalog", "gallery")
    )
    parser.add_argument("--device", default=None)
    parser.add_argument("--no-iou", action="store_true")
    args = parser.parse_args()
    if args.stage == "manifest":
        result = build_followup_manifest()
    elif args.stage == "physical":
        result = run_physical_followup(device=args.device, with_iou=not args.no_iou)
    elif args.stage == "catalog":
        result = fetch_and_crossmatch_gwtc5()
    else:
        result = build_morphology_gallery()
    print(json.dumps(result.get("selection", result.get("summary", {})), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
