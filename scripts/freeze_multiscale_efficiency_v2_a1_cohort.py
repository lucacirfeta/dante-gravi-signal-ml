#!/usr/bin/env python3
"""Freeze or verify the outcome-blind multiscale A1 held-out cohort."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2_a1_cohort import (  # noqa: E402
    freeze_a1_cohort,
    verify_a1_cohort,
)


def _environment_path(windows: str, wsl: str) -> Path:
    return Path(windows if os.name == "nt" else wsl)


DEFAULT_OUTPUT = _environment_path(
    "E:/dante_cache/dante_light/multiscale_efficiency_v2_a1",
    "/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2_a1",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-run-dir", type=Path)
    args = parser.parse_args()
    if args.verify_run_dir:
        summary = verify_a1_cohort(run_dir=args.verify_run_dir, root=ROOT)
        run_dir = args.verify_run_dir
    else:
        summary, run_dir = freeze_a1_cohort(output_root=args.output_root, root=ROOT)
    print(f"{summary['status']}: {run_dir}")
    print(f"artifact_digest={summary['artifact_digest']}")


if __name__ == "__main__":
    main()
