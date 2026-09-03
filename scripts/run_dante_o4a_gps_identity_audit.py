#!/usr/bin/env python3
"""Run or verify the frozen O4a GPS identity-semantics audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_gps_identity_audit import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    run_audit,
    verify_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("run", "verify"), required=True)
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    args = parser.parse_args()
    function = run_audit if args.stage == "run" else verify_audit
    result = function(root=ROOT, external_root=args.external_root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
