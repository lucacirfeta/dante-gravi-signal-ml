#!/usr/bin/env python3
"""Train the frozen DANTE-Light v5 student arms on training-only targets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_protocol import repository_reference  # noqa: E402
from src.dante_light.prefilter_v5_training import (  # noqa: E402
    ARMS,
    DEFAULT_OUTPUT,
    run_training,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", default=None)
    parser.add_argument("--arm", action="append", choices=ARMS, default=None)
    parser.add_argument("--replicate", action="append", type=int, default=None)
    parser.add_argument("--smoke-batches", type=int, default=None)
    args = parser.parse_args()
    paths = {
        "student_architectures": "src/dante_light/prefilter_v4_student.py",
        "training_contract": "config/dante_light_prefilter_v5_training_contract.json",
        "training_implementation": "src/dante_light/prefilter_v5_training.py",
        "training_cli": "scripts/train_dante_light_prefilter_v5.py",
    }
    references = {
        label: repository_reference(ROOT, ROOT / path)
        for label, path in paths.items()
    }
    summary = run_training(
        root=ROOT,
        cache_root=args.cache_root,
        code_references=references,
        device_name=args.device,
        arms=args.arm or ARMS,
        replicate_indices=args.replicate,
        smoke=args.smoke_batches is not None,
        smoke_batches=args.smoke_batches,
        output_path=args.output,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "run_key": summary["run_key"],
                "artifact_digest": summary["artifact_digest"],
                "replicate_count": len(summary["replicate_summaries"]),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if summary["status"] != "FAILED_NUMERICAL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
