#!/usr/bin/env python3
"""Populate or verify the separate raw cache for O4a v1 parity replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import canonical_json_sha256  # noqa: E402
from src.dante_light.o4a_v1_parity_cache import (  # noqa: E402
    COMPACT_ARTIFACT, DEFAULT_CACHE_ROOT, DEFAULT_RAW_ROOT, build_cache, compact_cache_artifact,
    validate_cache,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    cache_root = args.cache_root.resolve()
    if args.verify:
        summary = validate_cache(root=ROOT, cache_root=cache_root)
    else:
        summary = build_cache(
            root=ROOT, cache_root=cache_root, raw_root=args.raw_root.resolve(), workers=args.workers,
            retries=args.retries, limit=args.limit,
        )
        if args.limit is None:
            summary = validate_cache(root=ROOT, cache_root=cache_root)
            compact = compact_cache_artifact(summary)
            compact["external_summary_sha256"] = hashlib.sha256((cache_root / "summary.json").read_bytes()).hexdigest()
            body = dict(compact); body.pop("artifact_digest")
            compact["artifact_digest"] = canonical_json_sha256(body)
            COMPACT_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
            COMPACT_ARTIFACT.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: summary[key] for key in ("status", "run_key", "expected_missing_count", "completed_count", "failure_count")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
