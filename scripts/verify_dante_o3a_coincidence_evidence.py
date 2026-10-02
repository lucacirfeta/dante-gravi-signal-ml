#!/usr/bin/env python3
"""Read-only retained O3a coincidence reconstruction; no productive options."""

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
    parser.add_argument("--scan-copy-dir", type=Path)
    parser.add_argument("--expected-scan-copy-receipt-sha256")
    parser.add_argument(
        "--allow-retained-driver-drift",
        action="store_true",
        help="Author-approved driver metadata waiver for retained read-only evidence only",
    )
    for name in (
        "external-root",
        "taxonomy-external-root",
        "classification-external-root",
        "threshold-external-root",
        "rescore-external-root",
        "calibration-external-root",
        "index-external-root",
        "cohort-external-root",
        "primary-external-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    from src.dante_workflow.o3a_coincidence_verification import (
        verify_coincidence_evidence,
    )

    try:
        arguments = vars(args).copy()
        arguments["root"] = arguments.pop("repository_root")
        print(
            json.dumps(
                verify_coincidence_evidence(**arguments),
                sort_keys=True,
                indent=2,
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
                    "status": "FAIL_CLOSED_O3A_COINCIDENCE_EVIDENCE",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
