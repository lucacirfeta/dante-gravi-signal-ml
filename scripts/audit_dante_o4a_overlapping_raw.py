#!/usr/bin/env python3
"""Build or verify the sample-level O4a overlapping-span audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_overlap_audit import (  # noqa: E402
    OUTPUT_REL,
    build_overlap_audit,
    validate_overlap_audit,
    write_overlap_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--output", type=Path, default=ROOT / OUTPUT_REL)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        saved = json.loads(args.output.read_text(encoding="utf-8"))
        validate_overlap_audit(saved)
        rebuilt = build_overlap_audit(root=ROOT, raw_root=args.raw_root)
        if saved != rebuilt:
            raise RuntimeError("overlapping raw span audit is stale")
        print(f"PASS {args.output} {saved['artifact_digest']}")
        return 0
    value = write_overlap_audit(root=ROOT, raw_root=args.raw_root, output=args.output)
    print(f"PASS {args.output} {value['artifact_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
