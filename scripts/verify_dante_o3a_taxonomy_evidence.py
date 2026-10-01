#!/usr/bin/env python3
"""Read-only frozen O3a morphology taxonomy replay; no productive options."""

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
    for name in (
        "external-root",
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
    from src.dante_workflow.o3a_taxonomy_verification import verify_taxonomy_evidence

    try:
        arguments = vars(args).copy()
        arguments["root"] = arguments.pop("repository_root")
        result = verify_taxonomy_evidence(**arguments)
        print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
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
                    "status": "FAIL_CLOSED_O3A_TAXONOMY_EVIDENCE",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
