#!/usr/bin/env python3
"""Verify existing O3a INDEX evidence without historical writes or refitting."""

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
    parser.add_argument("--external-root", type=Path, required=True)
    parser.add_argument("--cohort-external-root", type=Path, required=True)
    parser.add_argument("--primary-external-root", type=Path, required=True)
    args = parser.parse_args(argv)
    from src.dante_workflow.o3a_index_verification import verify_index_evidence

    try:
        result = verify_index_evidence(
            root=args.repository_root,
            external_root=args.external_root,
            cohort_external_root=args.cohort_external_root,
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
                    "status": "FAIL_CLOSED_O3A_INDEX_EVIDENCE",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
