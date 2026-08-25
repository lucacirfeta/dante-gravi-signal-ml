#!/usr/bin/env python3
"""Run the frozen v6 Phase-B five-arm screening matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_protocol import repository_reference
from src.dante_light.prefilter_v6_training import DEFAULT_CACHE, run_training


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--device", default=None)
    parser.add_argument("--arm", action="append", default=None)
    parser.add_argument("--replicate", action="append", type=int, default=None)
    parser.add_argument("--smoke-batches", type=int, default=None)
    args = parser.parse_args()
    paths = {
        "phase_a_architectures": "src/dante_light/prefilter_v6_phase_a.py",
        "phase_b_objectives": "src/dante_light/prefilter_v6_phase_b.py",
        "training_contract": "src/dante_light/prefilter_v6_training_contract.py",
        "training_implementation": "src/dante_light/prefilter_v6_training.py",
        "training_runner": "scripts/train_dante_light_prefilter_v6_phase_b.py",
        "v5_training_utilities": "src/dante_light/prefilter_v5_training.py",
    }
    references = {name: repository_reference(ROOT, ROOT / path) for name, path in paths.items()}
    summary = run_training(
        root=ROOT,
        cache_root=args.cache_root.resolve(),
        code_references=references,
        device_name=args.device,
        arm_ids=args.arm,
        replicate_indices=args.replicate,
        smoke=args.smoke_batches is not None,
        smoke_batches=args.smoke_batches,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "run_key": summary["run_key"],
                "selection": summary["selection"],
                "artifact_digest": summary["artifact_digest"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
