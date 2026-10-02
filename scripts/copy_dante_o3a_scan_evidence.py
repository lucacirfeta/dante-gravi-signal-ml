#!/usr/bin/env python3
"""Explicit isolated SCAN byte transport; no historical SQLite repair."""

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
    parser.add_argument("--stage", choices=("capture", "verify"), required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--primary-external-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-receipt-sha256")
    args = parser.parse_args(argv)
    from src.dante_workflow.o3a_scan_copy import capture_copy, verify_copy

    try:
        kwargs = {
            "root": args.repository_root,
            "primary_external_root": args.primary_external_root,
            "output": args.output,
        }
        if args.stage == "capture":
            if args.expected_receipt_sha256 is not None:
                raise ValueError("capture cannot adopt an existing receipt")
            result = capture_copy(**kwargs)
        else:
            if args.expected_receipt_sha256 is None:
                raise ValueError(
                    "verify requires an independently supplied receipt SHA256"
                )
            result = verify_copy(
                **kwargs, expected_receipt_sha256=args.expected_receipt_sha256
            )
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (
        ValueError,
        RuntimeError,
        OSError,
        KeyError,
        TypeError,
        StopIteration,
    ) as error:
        print(
            json.dumps(
                {
                    "status": "FAIL_CLOSED_ISOLATED_SCAN_COPY",
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
