#!/usr/bin/env python3
"""Execute or verify the frozen O3a detector-aware native index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_index import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    build_native_index,
    clear_infrastructure_failure,
    verify_native_index,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--clear-infrastructure-failure", action="store_true")
    args = parser.parse_args()
    if args.clear_infrastructure_failure:
        archive = clear_infrastructure_failure(root=ROOT, external_root=args.external_root)
        print(json.dumps({"archived_failure": str(archive)}, indent=2))
        return 0
    summary, run_dir = (
        verify_native_index(root=ROOT, external_root=args.external_root)
        if args.verify
        else build_native_index(root=ROOT, external_root=args.external_root)
    )
    print(json.dumps({"summary": summary, "run_dir": str(run_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
