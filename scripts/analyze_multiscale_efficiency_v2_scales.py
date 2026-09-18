#!/usr/bin/env python3
"""Run or verify the frozen unconditional paired short-scale diagnostic."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2_scale_diagnostic import (  # noqa: E402
    run_scale_diagnostic,
    verify_scale_diagnostic,
)

INJECTION_KEY = "b56882a474ff381ce0408337c79e775e980019ee3685b8d116acd8305addf1bb"


def _environment_path(windows: str, wsl: str) -> Path:
    return Path(windows if os.name == "nt" else wsl)


DEFAULT_INJECTIONS = _environment_path(
    f"E:/dante_cache/dante_light/multiscale_efficiency_v2/injections_{INJECTION_KEY}",
    f"/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2/injections_{INJECTION_KEY}",
)
DEFAULT_OUTPUT = _environment_path(
    "E:/dante_cache/dante_light/multiscale_efficiency_v2_scale_diagnostic",
    "/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2_scale_diagnostic",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injection-run-dir", type=Path, default=DEFAULT_INJECTIONS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-run-dir", type=Path)
    args = parser.parse_args()
    if args.verify_run_dir:
        summary = verify_scale_diagnostic(
            run_dir=args.verify_run_dir,
            injection_run_dir=args.injection_run_dir,
            root=ROOT,
        )
        run_dir = args.verify_run_dir
    else:
        summary, run_dir = run_scale_diagnostic(
            injection_run_dir=args.injection_run_dir,
            output_root=args.output_root,
            root=ROOT,
        )
    print(f"{summary['status']}: {run_dir}")
    print(f"evidence_digest={summary['artifact_digest']}")


if __name__ == "__main__":
    main()
