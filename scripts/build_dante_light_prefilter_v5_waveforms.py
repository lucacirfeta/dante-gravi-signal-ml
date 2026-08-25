#!/usr/bin/env python3
"""Build outcome-blind frozen development waveforms for DANTE-Light v5."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_waveforms import (  # noqa: E402
    build_injection_waveform_cache,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=None)
    args = parser.parse_args()
    summary = build_injection_waveform_cache(root=ROOT, cache_root=args.cache_root)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
