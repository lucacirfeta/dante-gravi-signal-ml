#!/usr/bin/env python3
"""Build fail-closed DANTE-Light prospective shadow evidence from paired runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dante_light.evidence import build_prospective_evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preflight", "operational"))
    parser.add_argument("--canonical-run", type=Path, required=True)
    parser.add_argument("--shared-run", type=Path, required=True)
    parser.add_argument("--epochs", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--latency-objective-s", type=float, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/dante_light/prospective_validation_v1.json"),
    )
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    payload = build_prospective_evidence(
        args.canonical_run,
        args.shared_run,
        epochs_path=args.epochs,
        bundle_path=args.bundle,
        output_path=args.output,
        root=args.root,
        latency_objective_s=args.latency_objective_s,
        mode=args.mode,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
