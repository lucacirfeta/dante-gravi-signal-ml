#!/usr/bin/env python3
"""Run the frozen retrospective training-only DANTE-Light v5 diagnostic."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_protocol import repository_reference  # noqa: E402
from src.dante_light.prefilter_v5_training_diagnostics import (  # noqa: E402
    DEFAULT_OUTPUT,
    DEFAULT_SPEC,
    run_training_diagnostics,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--device", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    code_references = {
        "diagnostic_cli": repository_reference(ROOT, Path(__file__)),
        "diagnostic_implementation": repository_reference(
            ROOT,
            ROOT / "src/dante_light/prefilter_v5_training_diagnostics.py",
        ),
    }
    result = run_training_diagnostics(
        root=ROOT,
        spec_path=args.spec.resolve(),
        cache_root=args.cache_root.resolve(),
        device_name=args.device,
        code_references=code_references,
        output_path=args.output.resolve(),
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "artifact_digest": result["artifact_digest"],
                "output": str(args.output.resolve()),
                "development_rows_accessed": [],
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
