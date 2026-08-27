#!/usr/bin/env python3
"""Freeze the explicit one-shot v7 threshold-search authorization."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_threshold_search import (
    DEFAULT_AUTHORIZATION,
    build_threshold_search_authorization,
    threshold_search_code_references,
)
from src.dante_light.prefilter_v7_training import _atomic_json


def main() -> int:
    payload = build_threshold_search_authorization(
        root=ROOT, code_references=threshold_search_code_references(ROOT)
    )
    _atomic_json(DEFAULT_AUTHORIZATION, payload)
    print(json.dumps({
        "status": payload["status"],
        "authorization_digest": payload["authorization_digest"],
        "allowed": payload["allowed"],
        "forbidden": payload["forbidden"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
