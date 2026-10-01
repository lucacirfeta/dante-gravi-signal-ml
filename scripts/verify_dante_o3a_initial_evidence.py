#!/usr/bin/env python3
"""Separate read-only initial O3a evidence CLI; scoped receipt on stdout only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    from src.dante_workflow.o3a_initial_verification import (
        verify_acceptance_evidence,
        verify_raw_evidence,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("raw", "acceptance"), required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--raw-root", type=Path, required=True)
    parser.add_argument("--external-root", type=Path)
    args = parser.parse_args(argv)
    if args.stage == "acceptance" and args.external_root is None:
        parser.error("acceptance requires --external-root")
    if args.stage == "raw" and args.external_root is not None:
        parser.error("raw does not accept --external-root")
    try:
        if args.stage == "raw":
            value = verify_raw_evidence(
                root=args.repository_root, raw_root=args.raw_root
            )
        else:
            value = verify_acceptance_evidence(
                root=args.repository_root,
                raw_root=args.raw_root,
                external_root=args.external_root,
            )
        print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED_O3A_INITIAL_EVIDENCE",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
