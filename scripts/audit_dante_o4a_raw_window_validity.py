#!/usr/bin/env python3
"""Run or validate the complete sample-level O4a raw-window audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_window_validity_audit import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    OUTPUT_REL,
    run_window_validity_audit,
    validate_window_validity_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        value = json.loads((ROOT / OUTPUT_REL).read_text(encoding="utf-8"))
        validate_window_validity_summary(value)
        database = args.external_root / f"raw_validity_{value['run_key']}" / value["database"]["filename"]
        from src.dante_light.prefilter_v5_protocol import sha256_path

        if not database.is_file() or sha256_path(database) != value["database"]["sha256"]:
            raise RuntimeError("raw-window validity external database mismatch")
        print(f"PASS {ROOT / OUTPUT_REL} {value['artifact_digest']}")
        return 0
    value, run_dir = run_window_validity_audit(
        root=ROOT,
        raw_root=args.raw_root,
        external_root=args.external_root,
    )
    print(json.dumps({"run_dir": str(run_dir), **value}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

