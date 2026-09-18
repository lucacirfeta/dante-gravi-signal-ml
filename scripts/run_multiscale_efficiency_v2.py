"""Preflight, execute, or verify multiscale-efficiency-v2 injections."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import canonical_json_sha256  # noqa: E402
from src.pipeline_v3_multiscale.efficiency_v2_runner import (  # noqa: E402
    preflight_runner,
    run_paired_injections,
    verify_injection_run,
)

COHORT_KEY = "a0d8ce06d0357f8d0d2c77c4e5901fa9faa2c7fd3b3f47288cf633076a67f0ad"
REFERENCE_KEY = "3e1eb87a2eed3347b3b78ed99491b416cf27cde1bece0c0e84cd0abd38ba8d47"


def _default_root() -> Path:
    return Path("/mnt/e") if Path("/mnt/e").is_dir() else Path("E:/")


def main() -> None:
    drive = _default_root()
    cache = drive / "dante_cache/dante_light/multiscale_efficiency_v2"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-run-dir", default=str(cache / f"cohort_{COHORT_KEY}"))
    parser.add_argument(
        "--reference-run-dir", default=str(cache / f"reference_{REFERENCE_KEY}")
    )
    parser.add_argument("--raw-root", default=str(drive / "o4a"))
    parser.add_argument("--output-root", default=str(cache))
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--encoder-batch", type=int, default=10)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--verify-run-dir")
    args = parser.parse_args()

    if args.verify_run_dir:
        summary = verify_injection_run(run_dir=Path(args.verify_run_dir))
        run_dir = Path(args.verify_run_dir)
    elif args.preflight:
        summary = preflight_runner(
            cohort_run_dir=Path(args.cohort_run_dir),
            reference_run_dir=Path(args.reference_run_dir),
            raw_root=Path(args.raw_root),
            device=args.device,
        )
        run_dir = Path(args.output_root)
    else:
        summary, run_dir = run_paired_injections(
            cohort_run_dir=Path(args.cohort_run_dir),
            reference_run_dir=Path(args.reference_run_dir),
            raw_root=Path(args.raw_root),
            output_root=Path(args.output_root),
            device=args.device,
            workers=args.workers,
            encoder_batch=args.encoder_batch,
        )
    print(f"{summary['status']}: {run_dir}")
    print(
        f"evidence_digest={summary.get('artifact_digest', canonical_json_sha256(summary))}"
    )


if __name__ == "__main__":
    main()
