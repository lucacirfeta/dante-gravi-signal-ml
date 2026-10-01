#!/usr/bin/env python3
"""Capture/admit isolated retained bytes only; not a PEM/scientific verifier."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--policy",
        type=Path,
        default=ROOT / "config/dante_workflow_evidence_snapshot_v1.json",
    )
    stages = parser.add_subparsers(dest="stage", required=True)
    capture = stages.add_parser("capture")
    capture.add_argument("--plan", type=Path, required=True)
    capture.add_argument("--expected-plan-sha256", required=True)
    capture.add_argument(
        "--root", action="append", required=True, help="identifier=absolute-path"
    )
    capture.add_argument("--output", type=Path, required=True)
    verify = stages.add_parser("verify")
    verify.add_argument("--snapshot", type=Path, required=True)
    verify.add_argument("--expected-sha256", required=True)
    verify.add_argument("--expected-plan-sha256", required=True)
    args = parser.parse_args(argv)
    from src.dante_workflow import evidence_snapshot as snapshot

    try:
        policy_bytes = snapshot.read_snapshot_blob(args.policy, maximum=65536)
        policy = snapshot.load_policy(policy_bytes)
        if args.stage == "capture":
            roots = {}
            for declaration in args.root:
                name, separator, value = declaration.partition("=")
                if not separator or name in roots or not value:
                    raise snapshot.SnapshotError("invalid or duplicate explicit root")
                roots[name] = Path(value)
            plan = snapshot.read_snapshot_blob(
                args.plan, maximum=policy["limits"]["manifest_bytes"]
            )
            payload = snapshot.capture_snapshot(
                plan_bytes=plan,
                expected_plan_sha256=args.expected_plan_sha256,
                policy_bytes=policy_bytes,
                roots=roots,
            )
            digest = snapshot._sha(payload)
        else:
            payload = snapshot.read_snapshot_blob(
                args.snapshot, maximum=policy["limits"]["archive_bytes"]
            )
            digest = args.expected_sha256
        admitted = snapshot.admit_snapshot(
            payload,
            expected_sha256=digest,
            expected_plan_sha256=args.expected_plan_sha256,
            policy_bytes=policy_bytes,
        )
        if args.stage == "capture":
            snapshot.publish_snapshot(args.output, payload, roots=roots)
        print(json.dumps(admitted.receipt(), sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED_ISOLATED_SNAPSHOT_BYTES",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
