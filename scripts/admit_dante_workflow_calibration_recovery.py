#!/usr/bin/env python3
"""Create or independently verify explicit recovery admission; no science job."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_workflow.adapters import build_adapter  # noqa: E402
from src.dante_workflow.calibration_admission import (  # noqa: E402
    create_receipt,
    inspect_admitted_inputs,
)
from src.dante_workflow.schema import load_workflow_spec  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("create", "verify"), required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-sha256")
    parser.add_argument("--recovery-dir", type=Path)
    args = parser.parse_args(argv)
    spec = load_workflow_spec(args.config.resolve(), root=ROOT)
    adapter = build_adapter(spec)
    if args.stage == "create":
        if any(x is None for x in (args.policy, args.policy_sha256, args.recovery_dir)):
            parser.error("create requires pinned policy and recovery directory")
        result = create_receipt(
            spec,
            adapter,
            root=ROOT,
            output=args.receipt,
            policy_path=args.policy,
            policy_sha=args.policy_sha256,
            recovery_dir=args.recovery_dir,
        )
        result = {k: v for k, v in result.items() if k != "records"}
    else:
        if args.receipt_sha256 is None:
            parser.error("verify requires receipt SHA")
        result = inspect_admitted_inputs(
            spec,
            adapter,
            root=ROOT,
            receipt_path=args.receipt,
            receipt_sha=args.receipt_sha256,
        )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
