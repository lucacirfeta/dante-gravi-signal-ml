#!/usr/bin/env python3
"""Run or verify the frozen multiscale efficiency v2 causal trace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2_causal import (  # noqa: E402
    load_causal_contract,
    run_causal_diagnostic,
    verify_causal_diagnostic,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-run-dir", type=Path)
    parser.add_argument("--injection-run-dir", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--encoder-batch", type=int, default=8)
    parser.add_argument("--verify-run-dir", type=Path)
    parser.add_argument("--print-contract", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.print_contract:
        print(json.dumps(load_causal_contract(ROOT), indent=2, sort_keys=True))
        return 0
    if args.verify_run_dir is not None:
        print(
            json.dumps(
                verify_causal_diagnostic(run_dir=args.verify_run_dir, root=ROOT),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    required = {
        "--cohort-run-dir": args.cohort_run_dir,
        "--injection-run-dir": args.injection_run_dir,
        "--raw-root": args.raw_root,
        "--output-root": args.output_root,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise SystemExit(f"missing required arguments: {', '.join(missing)}")
    summary, run_dir = run_causal_diagnostic(
        cohort_run_dir=args.cohort_run_dir,
        injection_run_dir=args.injection_run_dir,
        raw_root=args.raw_root,
        output_root=args.output_root,
        device=args.device,
        workers=args.workers,
        encoder_batch=args.encoder_batch,
        root=ROOT,
    )
    print(json.dumps({"run_dir": str(run_dir), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
