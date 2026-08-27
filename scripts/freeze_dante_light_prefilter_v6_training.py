#!/usr/bin/env python3
"""Freeze compact targets and the v6 Phase-B training input contract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v6_teacher import _atomic_json
from src.dante_light.prefilter_v6_training_contract import (
    DEFAULT_CONTRACT,
    DEFAULT_TARGETS,
    DEFAULT_TEACHER_SUMMARY,
    build_training_freeze,
    load_training_freeze,
)


DEFAULT_CACHE = Path(
    os.environ.get(
        "DANTE_V6_TRAINING_CACHE_ROOT",
        r"E:\dante_cache\dante_light\prefilter_l4_v6_training",
    )
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teacher-summary", type=Path, default=DEFAULT_TEACHER_SUMMARY)
    parser.add_argument("--teacher-cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    args = parser.parse_args()
    contract, rows = build_training_freeze(
        root=ROOT,
        teacher_summary_path=args.teacher_summary.resolve(),
        teacher_cache_root=args.teacher_cache_root.resolve(),
        targets_path=args.targets.resolve(),
        write_targets=True,
    )
    _atomic_json(args.contract.resolve(), contract)
    load_training_freeze(args.contract.resolve(), root=ROOT)
    print(
        json.dumps(
            {
                "status": "PASS",
                "training_contract_digest": contract["training_contract_digest"],
                "row_count": len(rows),
                "counts": contract["population"]["counts"],
                "target_standardization": contract["target_standardization"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
