"""Build or verify the frozen multiscale-efficiency-v2 analysis."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2_analysis import (  # noqa: E402
    run_analysis,
    verify_analysis_run,
)

INJECTION_KEY = "b56882a474ff381ce0408337c79e775e980019ee3685b8d116acd8305addf1bb"


def _default_path(windows: str, wsl: str) -> Path:
    return Path(windows if os.name == "nt" else wsl)


DEFAULT_CACHE = _default_path(
    "E:/dante_cache/dante_light/multiscale_efficiency_v2",
    "/mnt/e/dante_cache/dante_light/multiscale_efficiency_v2",
)
DEFAULT_INJECTIONS = DEFAULT_CACHE / f"injections_{INJECTION_KEY}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--injection-run-dir", type=Path, default=DEFAULT_INJECTIONS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--verify-run-dir", type=Path)
    args = parser.parse_args()
    if args.verify_run_dir:
        summary = verify_analysis_run(
            run_dir=args.verify_run_dir,
            injection_run_dir=args.injection_run_dir,
        )
        run_dir = args.verify_run_dir
    else:
        summary, run_dir = run_analysis(
            injection_run_dir=args.injection_run_dir,
            output_root=args.output_root,
        )
    print(f"{summary['status']}: {run_dir}")
    print(f"evidence_digest={summary['artifact_digest']}")


if __name__ == "__main__":
    main()
