#!/usr/bin/env python3
"""Populate the resumable E: raw-window cache for frozen v6 Phase B."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_protocol import repository_reference
from src.dante_light.prefilter_v6_cache import build_phase_b_cache


DEFAULT_CACHE = Path(os.environ.get("DANTE_V6_RAW_CACHE_ROOT", r"E:\dante_cache\dante_light\prefilter_l4_v6_raw"))
DEFAULT_ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v6_cache/phase_b_raw_cache_summary_v6.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    references = {
        "cache_implementation": repository_reference(ROOT, ROOT / "src/dante_light/prefilter_v6_cache.py"),
        "cache_runner": repository_reference(ROOT, Path(__file__).resolve()),
    }
    summary = build_phase_b_cache(
        root=ROOT,
        cache_root=args.cache_root.resolve(),
        artifact_path=args.artifact.resolve(),
        implementation_references=references,
        workers=args.workers,
        retries=args.retries,
        limit=args.limit,
    )
    print(json.dumps({
        "status": summary["status"],
        "run_key": summary["run_key"],
        "cached_interval_count": summary["cached_interval_count"],
        "artifact_digest": summary["artifact_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
