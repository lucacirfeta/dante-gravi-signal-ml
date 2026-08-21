#!/usr/bin/env python3
"""Build a resumable canonical prefilter-feature ledger for an exact run."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.executor import DeferredWindow
from src.dante_light.prefilter_features import build_shadow_feature_ledger
from src.dante_light.preprocessing import prepare_prefilter_features


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--strain-source", choices=("auto", "local-only", "gwosc-only"), default="auto")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    try:
        ledger = build_shadow_feature_ledger(
            root=ROOT,
            manifest_path=args.manifest,
            records_path=args.records,
            output_dir=args.output_dir,
            limit=args.limit,
            prepare=lambda task: prepare_prefilter_features(
                task.window,
                local_only=args.strain_source == "local-only",
                remote_only=args.strain_source == "gwosc-only",
            ),
        )
    except (ContractError, DeferredWindow) as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"PASS: {ledger['row_count']} canonical feature rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
