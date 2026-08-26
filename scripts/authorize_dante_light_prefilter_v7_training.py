#!/usr/bin/env python3
"""Write the explicit training-only v7 authorization receipt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_training import (
    DEFAULT_AUTHORIZATION,
    build_training_authorization,
    execution_code_references,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_AUTHORIZATION)
    args = parser.parse_args()
    payload = build_training_authorization(
        root=ROOT, source_references=execution_code_references(ROOT)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(json.dumps({"status": payload["status"], "authorization_digest": payload["authorization_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
