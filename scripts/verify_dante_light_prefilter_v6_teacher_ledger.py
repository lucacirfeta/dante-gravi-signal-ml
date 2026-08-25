#!/usr/bin/env python3
"""Fail-closed verifier for the frozen v6 Phase-B teacher ledger."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v6_teacher import verify_teacher_ledger_summary


DEFAULT_ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v6_training/teacher_ledger_summary_v6.json"
DEFAULT_CACHE = Path(
    os.environ.get(
        "DANTE_V6_TRAINING_CACHE_ROOT",
        r"E:\dante_cache\dante_light\prefilter_l4_v6_training",
    )
)


def verify(*, artifact: Path, cache_root: Path, require_complete: bool = True) -> dict:
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    return verify_teacher_ledger_summary(
        summary,
        root=ROOT,
        cache_root=cache_root,
        require_complete=require_complete,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                artifact=args.artifact.resolve(),
                cache_root=args.cache_root.resolve(),
                require_complete=not args.allow_smoke,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
