#!/usr/bin/env python3
"""Explicit metadata-only missing-calibration preflight, not an acquirer."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.adapters import build_adapter  # noqa: E402
from src.dante_workflow.calibration_transport import run_preflight  # noqa: E402
from src.dante_workflow.schema import load_workflow_spec  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--receipt-sha256", required=True)
    parser.add_argument("--candidate-dataset", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; refuse overwrite")
    spec = load_workflow_spec(args.config.resolve(), root=ROOT)
    report = run_preflight(
        spec,
        build_adapter(spec),
        root=ROOT,
        receipt_path=args.receipt,
        receipt_sha=args.receipt_sha256,
        dataset=args.candidate_dataset,
    )
    # Exclusive creation preserves earlier evidence; no raw or workflow writes.
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        )
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "interval_count",
                    "unique_file_count",
                    "report_digest",
                    "historical_release_equivalence_checked",
                    "scientific_execution_ready",
                )
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
