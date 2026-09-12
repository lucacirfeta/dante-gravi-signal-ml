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
from src.dante_light.o4a_canonical_native_calibration_rerun import (  # noqa: E402
    run as run_native_calibration,
    write_frozen_contract as write_frozen_native_calibration_contract,
)
from src.dante_light.o4a_canonical_native_rescore_rerun import (  # noqa: E402
    run as run_native_rescore,
    write_frozen_contract as write_frozen_native_rescore_contract,
    write_verified_evidence as write_native_rescore_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=(
            "validate",
            "preflight",
            "freeze-contract",
            "run",
            "verify",
            "record-evidence",
        ),
    )
    parser.add_argument(
        "--stage",
        choices=("COHORT", "INDEX", "NATIVE_CALIBRATION", "RESCORE"),
        default="COHORT",
    )
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
            writers = {
                "COHORT": write_frozen_cohort_contract,
                "INDEX": write_frozen_index_contract,
                "NATIVE_CALIBRATION": write_frozen_native_calibration_contract,
                "RESCORE": write_frozen_native_rescore_contract,
            }
            path = writers[args.stage](root=ROOT)
            result = {"status": "FROZEN_CONTRACT", "stage": args.stage, "path": str(path)}
        elif args.operation == "record-evidence":
            if args.stage != "RESCORE":
                raise ContractError("record-evidence is currently defined only for RESCORE")
            path = write_native_rescore_evidence(root=ROOT)
            result = {
                "status": "RECORDED_VERIFIED_EVIDENCE",
                "stage": args.stage,
                "path": str(path),
            }
        else:
            if args.stage == "COHORT":
                summary, run_dir = run_cohort(
                    root=ROOT,
                    workers=args.workers,
                    quality_batch_size=args.quality_batch_size,
                    verify_only=args.operation == "verify",
                )
            elif args.stage == "INDEX":
                summary, run_dir = run_index(
                    root=ROOT,
                    workers=args.workers,
                    encoder_batch_size=args.encoder_batch_size,
                    verify_only=args.operation == "verify",
                )
            elif args.stage == "NATIVE_CALIBRATION":
                summary, run_dir, manifest_evidence = run_native_calibration(
                    root=ROOT,
                    verify_only=args.operation == "verify",
                )
            else:
                summary, run_dir = run_native_rescore(
                    root=ROOT,
                    verify_only=args.operation == "verify",
                )
            result = {"run_dir": str(run_dir), **summary}
            if args.stage == "NATIVE_CALIBRATION":
                result["index_consumption_manifest"] = manifest_evidence
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
