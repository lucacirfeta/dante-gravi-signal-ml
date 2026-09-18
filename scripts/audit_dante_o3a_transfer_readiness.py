#!/usr/bin/env python3
"""Print the read-only O3a local-readiness audit as canonical JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_transfer_readiness import (  # noqa: E402
    DEFAULT_GATE,
    audit_local_readiness,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--cache-root", type=Path)
    args = parser.parse_args()
    result = audit_local_readiness(
        root=ROOT,
        gate_path=args.gate,
        cache_root=args.cache_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
