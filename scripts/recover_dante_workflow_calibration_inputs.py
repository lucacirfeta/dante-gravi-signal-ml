#!/usr/bin/env python3
"""Separate transport run and offline replay; never scientific admission."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.adapters import build_adapter  # noqa:E402
from src.dante_workflow.calibration_recovery import (  # noqa: E402
    build_plan,
    acquire,
    verify,
    write_json,
)
from src.dante_workflow.schema import load_workflow_spec  # noqa:E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--report-sha256")
    parser.add_argument("--historical-receipt", type=Path)
    args = parser.parse_args()
    if args.stage == "run":
        if any(
            x is None
            for x in (
                args.config,
                args.report,
                args.report_sha256,
                args.historical_receipt,
            )
        ):
            parser.error("run requires explicit config/report+SHA/historical-receipt")
        spec = load_workflow_spec(args.config.resolve(), root=ROOT)
        plan = build_plan(
            spec,
            build_adapter(spec),
            root=ROOT,
            report_path=args.report,
            report_sha=args.report_sha256,
            receipt_path=args.historical_receipt,
        )
        result = acquire(plan, args.run_dir, root=ROOT)
        print(
            json.dumps(
                {"status": result["status"], "interval_count": len(result["records"])}
            )
        )
    else:
        result = verify(args.run_dir, root=ROOT)
        output = args.run_dir / "verification.json"
        if output.exists():
            parser.error("verification evidence already exists; refuse overwrite")
        write_json(output, result)
        print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
