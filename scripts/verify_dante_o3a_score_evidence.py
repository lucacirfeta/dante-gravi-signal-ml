#!/usr/bin/env python3
"""Read retained O3a calibration/rescore evidence without scoring or writes."""

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
    parser.add_argument("--stage", choices=("calibration", "rescore"), required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    for name in (
        "external-root",
        "index-external-root",
        "cohort-external-root",
        "primary-external-root",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--calibration-external-root", type=Path)
    args = parser.parse_args(argv)
    from src.dante_workflow.o3a_score_verification import verify_score_evidence

    try:
        result = verify_score_evidence(
            root=args.repository_root,
            stage=args.stage,
            external_root=args.external_root,
            index_external_root=args.index_external_root,
            cohort_external_root=args.cohort_external_root,
            primary_external_root=args.primary_external_root,
            calibration_external_root=args.calibration_external_root,
        )
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
        sqlite3.Error,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED_O3A_SCORE_EVIDENCE",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
