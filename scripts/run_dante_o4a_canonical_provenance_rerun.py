#!/usr/bin/env python3
"""Freeze, run, or verify the canonical O4a provenance remediation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError  # noqa: E402
from src.dante_light.o4a_canonical_provenance_rerun import (  # noqa: E402
    load_protocol,
    preflight,
    run_cohort,
    run_index,
    write_frozen_cohort_contract,
    write_frozen_index_contract,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("validate", "preflight", "freeze-contract", "run", "verify"),
    )
    parser.add_argument("--stage", choices=("COHORT", "INDEX"), default="COHORT")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--quality-batch-size", type=int, default=128)
    parser.add_argument("--encoder-batch-size", type=int, default=8)
    parser.add_argument("--no-cuda-check", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.operation == "validate":
            result = load_protocol(root=ROOT, verify_git=True)
        elif args.operation == "preflight":
            result = preflight(root=ROOT, require_cuda=not args.no_cuda_check)
        elif args.operation == "freeze-contract":
            path = (
                write_frozen_cohort_contract(root=ROOT)
                if args.stage == "COHORT"
                else write_frozen_index_contract(root=ROOT)
            )
            result = {"status": "FROZEN_CONTRACT", "stage": args.stage, "path": str(path)}
        else:
            if args.stage == "COHORT":
                summary, run_dir = run_cohort(
                    root=ROOT,
                    workers=args.workers,
                    quality_batch_size=args.quality_batch_size,
                    verify_only=args.operation == "verify",
                )
            else:
                summary, run_dir = run_index(
                    root=ROOT,
                    workers=args.workers,
                    encoder_batch_size=args.encoder_batch_size,
                    verify_only=args.operation == "verify",
                )
            result = {"run_dir": str(run_dir), **summary}
    except (ContractError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED_CLOSED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
