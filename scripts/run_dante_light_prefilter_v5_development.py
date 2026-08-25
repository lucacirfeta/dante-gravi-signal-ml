#!/usr/bin/env python3
"""Run the authorized one-shot DANTE-Light v5 development evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError  # noqa: E402
from src.dante_light.prefilter_v5_development import (  # noqa: E402
    run_development_evaluation,
)
from src.dante_light.prefilter_v5_screening import (  # noqa: E402
    screen_development,
    write_screening,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development-cache-root", type=Path, default=None)
    parser.add_argument("--training-cache-root", type=Path, default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    try:
        development = run_development_evaluation(
            root=ROOT,
            development_cache_root=args.development_cache_root,
            training_cache_root=args.training_cache_root,
            device_name=args.device,
            workers=args.workers,
        )
        screening = screen_development(root=ROOT, cache_root=args.development_cache_root)
        write_screening(screening)
    except ContractError as exc:
        print(f"V5_NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "development_status": development["status"],
                "scientific_status": screening["status"],
                "selected_architecture": screening["selected_architecture"],
                "confirmation_rows_accessed": [],
                "o4b_rows_accessed": [],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
