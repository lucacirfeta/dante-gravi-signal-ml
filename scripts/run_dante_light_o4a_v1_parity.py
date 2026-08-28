#!/usr/bin/env python3
"""Freeze, execute, resume, or verify the canonical O4a v1 parity replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_v1_parity_replay import (  # noqa: E402
    DEFAULT_CACHE_ROOT, DEFAULT_RAW_ROOT, EXECUTION_PATH, build_execution_contract,
    run_canonical_replay, validate_execution_contract, verify_score_run,
    write_compact_result, write_execution_contract,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--check-freeze", action="store_true")
    parser.add_argument("--verify-run", type=Path)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    modes = sum((args.freeze, args.check_freeze, args.verify_run is not None))
    if modes > 1:
        parser.error("--freeze, --check-freeze and --verify-run are mutually exclusive")
    if args.freeze:
        value = write_execution_contract()
        print(f"FROZEN {EXECUTION_PATH} {value['execution_digest']}")
        return 0
    if args.check_freeze:
        stored = json.loads(EXECUTION_PATH.read_text(encoding="utf-8"))
        validate_execution_contract(stored, root=ROOT)
        if stored != build_execution_contract(ROOT):
            raise RuntimeError("stored parity execution contract is stale")
        print(f"PASS {EXECUTION_PATH} {stored['execution_digest']}")
        return 0
    if args.verify_run is not None:
        result = verify_score_run(root=ROOT, run_dir=args.verify_run.resolve())
        write_compact_result(result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    output, summary = run_canonical_replay(
        root=ROOT, raw_root=args.raw_root.resolve(), cache_root=args.cache_root.resolve(),
        output_dir=None if args.output_dir is None else args.output_dir.resolve(),
        device=args.device,
    )
    print(json.dumps({"output_dir": str(output), **summary}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
