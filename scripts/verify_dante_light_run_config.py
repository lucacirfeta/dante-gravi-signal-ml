#!/usr/bin/env python3
"""Preflight a locked DANTE-Light shadow manifest against causal epochs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dante_light.run_config import verify_run_configuration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--epochs", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--reference-manifest",
        type=Path,
        default=Path("config/reference_artifacts.json"),
    )
    args = parser.parse_args()
    result = verify_run_configuration(
        manifest_path=args.manifest,
        epochs_path=args.epochs,
        root=args.root,
        reference_manifest_path=args.reference_manifest,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
