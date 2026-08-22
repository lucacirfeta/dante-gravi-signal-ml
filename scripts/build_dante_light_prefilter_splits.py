#!/usr/bin/env python3
"""Freeze deterministic L4 development/evaluation cohort identities."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_splits import build_prefilter_splits, write_prefilter_splits
from src.dante_light.prefilter_protocol import (
    DEFAULT_PROTOCOL_PATH,
    load_prefilter_protocol,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_splits_v1.json",
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_PATH)
    args = parser.parse_args()
    protocol = load_prefilter_protocol(args.protocol)
    payload = build_prefilter_splits(
        root=ROOT, seed=int(protocol.payload["cohort_split_seed"])
    )
    write_prefilter_splits(payload, args.output)
    for role, cohort in payload["cohorts"].items():
        print(role, cohort["counts"], cohort["split_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
