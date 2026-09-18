#!/usr/bin/env python3
"""Build or verify the frozen A2 separate-channel evidence."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2_a2_channels import (  # noqa: E402
    build_two_channel_evidence,
    verify_two_channel_evidence,
)


def _environment_path(windows: str, wsl: str) -> Path:
    return Path(windows if os.name == "nt" else wsl)


DEFAULT_OUTPUT = _environment_path(
    "E:/dante_cache/dante_light/multiscale_efficiency_v2_a2",
    "/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2_a2",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("build", "verify"))
    parser.add_argument("--heldout-run-dir", type=Path, required=True)
    parser.add_argument("--joint-null-run-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.stage == "build":
        summary, run_dir = build_two_channel_evidence(
            heldout_run_dir=args.heldout_run_dir,
            joint_null_run_dir=args.joint_null_run_dir,
            output_root=args.output_root,
            root=ROOT,
        )
    else:
        if args.run_dir is None:
            parser.error("verify requires --run-dir")
        summary = verify_two_channel_evidence(
            run_dir=args.run_dir,
            heldout_run_dir=args.heldout_run_dir,
            joint_null_run_dir=args.joint_null_run_dir,
            root=ROOT,
        )
        run_dir = args.run_dir

    print(f"{summary['status']}: {run_dir}")
    print(f"artifact_digest={summary['artifact_digest']}")


if __name__ == "__main__":
    main()
