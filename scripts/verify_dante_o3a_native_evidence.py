#!/usr/bin/env python3
"""Read-only O3a scan/native cohort evidence CLI; stdout receipt only."""

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
    parser.add_argument("--stage", choices=("scan", "cohort"), required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--external-root", type=Path, required=True)
    parser.add_argument("--primary-external-root", type=Path)
    args = parser.parse_args(argv)
    if (args.stage == "cohort") != (args.primary_external_root is not None):
        parser.error("--primary-external-root required only for cohort")
    from src.dante_workflow.o3a_native_verification import verify_native_evidence

    try:
        result = verify_native_evidence(
            root=args.repository_root,
            stage=args.stage,
            external_root=args.external_root,
            primary_external_root=args.primary_external_root,
        )
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
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
                    "status": "FAIL_CLOSED_O3A_NATIVE_EVIDENCE",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
