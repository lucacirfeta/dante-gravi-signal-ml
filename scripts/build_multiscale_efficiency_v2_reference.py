"""Build, preflight, or verify multiscale-efficiency-v2 references."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2_reference import (  # noqa: E402
    build_reference,
    preflight_reference,
    verify_reference,
)

COHORT_RUN_KEY = "a0d8ce06d0357f8d0d2c77c4e5901fa9faa2c7fd3b3f47288cf633076a67f0ad"


def _default_path(windows: str, wsl: str) -> Path:
    return Path(windows if os.name == "nt" else wsl)


DEFAULT_COHORT = _default_path(
    f"E:/dante_cache/dante_light/multiscale_efficiency_v2/cohort_{COHORT_RUN_KEY}",
    f"/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2/cohort_{COHORT_RUN_KEY}",
)
DEFAULT_RAW = _default_path("E:/o4a", "/mnt/e/o4a")
DEFAULT_OUTPUT = _default_path(
    "E:/dante_cache/dante_light/multiscale_efficiency_v2",
    "/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort-run-dir", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--encoder-batch", type=int, default=8)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--verify-run-dir", type=Path)
    args = parser.parse_args()
    if args.verify_run_dir:
        summary = verify_reference(run_dir=args.verify_run_dir)
        run_dir = args.verify_run_dir
    elif args.preflight:
        summary = preflight_reference(
            cohort_run_dir=args.cohort_run_dir,
            raw_root=args.raw_root,
            device=args.device,
        )
        run_dir = args.output_root
    else:
        summary, run_dir = build_reference(
            cohort_run_dir=args.cohort_run_dir,
            raw_root=args.raw_root,
            output_root=args.output_root,
            device=args.device,
            workers=args.workers,
            encoder_batch=args.encoder_batch,
        )
    print(f"{summary['status']}: {run_dir}")
    digest = summary.get("artifact_digest") or summary.get("token_sha256")
    print(f"evidence_digest={digest}")


if __name__ == "__main__":
    main()
