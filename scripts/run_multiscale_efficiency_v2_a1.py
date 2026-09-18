#!/usr/bin/env python3
"""Run or verify the frozen multiscale-efficiency-v2 A1 experiment."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2_a1_runner import (  # noqa: E402
    run_heldout,
    run_joint_null,
    verify_heldout,
    verify_joint_null,
)


def _environment_path(windows: str, wsl: str) -> Path:
    return Path(windows if os.name == "nt" else wsl)


DEFAULT_RAW = _environment_path("E:/o4a", "/mnt/e/o4a")
DEFAULT_OUTPUT = _environment_path(
    "E:/dante_cache/dante_light/multiscale_efficiency_v2_a1",
    "/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2_a1",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage",
        choices=("joint-null", "heldout", "verify-joint-null", "verify-heldout"),
    )
    parser.add_argument("--joint-null-run-dir", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--encoder-batch", type=int, default=10)
    args = parser.parse_args()

    if args.stage == "joint-null":
        summary, run_dir = run_joint_null(
            raw_root=args.raw_root,
            output_root=args.output_root,
            device=args.device,
            workers=args.workers,
            encoder_batch=args.encoder_batch,
            root=ROOT,
        )
    elif args.stage == "heldout":
        if args.joint_null_run_dir is None:
            parser.error("heldout requires --joint-null-run-dir")
        summary, run_dir = run_heldout(
            joint_null_run_dir=args.joint_null_run_dir,
            raw_root=args.raw_root,
            output_root=args.output_root,
            device=args.device,
            workers=args.workers,
            encoder_batch=args.encoder_batch,
            root=ROOT,
        )
    elif args.stage == "verify-joint-null":
        if args.run_dir is None:
            parser.error("verify-joint-null requires --run-dir")
        summary = verify_joint_null(run_dir=args.run_dir, root=ROOT)
        run_dir = args.run_dir
    else:
        if args.run_dir is None or args.joint_null_run_dir is None:
            parser.error("verify-heldout requires --run-dir and --joint-null-run-dir")
        summary = verify_heldout(
            run_dir=args.run_dir,
            joint_null_run_dir=args.joint_null_run_dir,
            root=ROOT,
        )
        run_dir = args.run_dir

    print(f"{summary['status']}: {run_dir}")
    print(f"artifact_digest={summary['artifact_digest']}")


if __name__ == "__main__":
    main()
