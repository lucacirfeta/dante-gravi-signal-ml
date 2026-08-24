#!/usr/bin/env python3
"""Fail-closed verifier for the DANTE-Light v5 teacher ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_teacher import (  # noqa: E402
    default_cache_root,
    load_teacher_contract,
    verify_teacher_ledger_summary,
)


DEFAULT_ARTIFACT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/teacher_ledger_summary_v5.json"
)


def verify(
    *,
    artifact: Path = DEFAULT_ARTIFACT,
    cache_root: Path | None = None,
    require_complete: bool = True,
) -> dict:
    summary = json.loads(artifact.read_text(encoding="utf-8"))
    return verify_teacher_ledger_summary(
        summary,
        root=ROOT,
        contract=load_teacher_contract(root=ROOT),
        cache_root=cache_root or default_cache_root(),
        require_complete=require_complete,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--allow-smoke", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(
                artifact=args.artifact,
                cache_root=args.cache_root,
                require_complete=not args.allow_smoke,
            ),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
