#!/usr/bin/env python3
"""Verify the O4a native source-provenance reconciliation record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_native_provenance import (  # noqa: E402
    load_reconciliation,
    replay_reconciliation_sample,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument(
        "--native-external-root",
        type=Path,
        default=Path("E:/dante_cache/dante_light/o4a_corrected_native_v1"),
    )
    args = parser.parse_args()
    record = load_reconciliation(root=args.root, verify_git=True)
    result: dict[str, object] = {
        "status": record["status"],
        "record_digest": record["record_digest"],
        "canonical_source_sha256": record["canonical_source"]["sha256"],
        "historical_raw_sha256": record["unretained_raw_source"]["sha256"],
        "canonical_replay_rows_recorded": len(record["canonical_replay"]["rows"]),
    }
    if args.replay:
        if args.raw_root is None:
            parser.error("--replay requires --raw-root")
        result["replay"] = replay_reconciliation_sample(
            root=args.root,
            raw_root=args.raw_root,
            native_external_root=args.native_external_root,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
