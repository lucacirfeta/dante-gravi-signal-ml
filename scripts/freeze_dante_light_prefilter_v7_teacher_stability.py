#!/usr/bin/env python3
"""Freeze the v7 exact-teacher fingerprint and training-only canary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v7_teacher_stability import build_stability_contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    payload = build_stability_contract(root=ROOT, device=args.device, write=True)
    print(json.dumps({
        "status": payload["status"],
        "stability_contract_digest": payload["stability_contract_digest"],
        "teacher_fingerprint_digest": payload["teacher_fingerprint"]["fingerprint_digest"],
        "canary_count": payload["canary_contract"]["total_canaries"],
        "accessed": payload["accessed"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
