#!/usr/bin/env python3
"""Read-only retained PEM snapshot plus actual existing parent gates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument(
        "--allow-retained-driver-drift",
        action="store_true",
        help="Author-approved driver metadata waiver for retained read-only evidence only",
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--expected-plan-sha256", required=True)
    for name in (
        "pem",
        "coincidence",
        "taxonomy",
        "classification",
        "threshold",
        "rescore",
        "calibration",
        "index",
        "cohort",
        "primary",
    ):
        parser.add_argument("--" + name + "-external-root", type=Path, required=True)
    args = parser.parse_args(argv)
    from src.dante_workflow import evidence_snapshot as snapshots
    from src.dante_workflow.o3a_pem_verification import verify_pem_evidence

    try:
        arguments = vars(args).copy()
        root = arguments.pop("repository_root")
        policy = snapshots.load_policy((root / snapshots.POLICY_REL).read_bytes())
        arguments["snapshot_bytes"] = snapshots.read_snapshot_blob(
            arguments.pop("snapshot"), maximum=policy["limits"]["archive_bytes"]
        )
        print(
            json.dumps(
                verify_pem_evidence(root=root, **arguments),
                sort_keys=True,
                allow_nan=False,
            )
        )
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
        sqlite3.Error,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED_O3A_PEM_SNAPSHOT_EVIDENCE",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
