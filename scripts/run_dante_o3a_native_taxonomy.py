#!/usr/bin/env python3
"""Freeze, run, or independently replay-verify O3a morphology taxonomy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_taxonomy import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    execute,
    freeze_contract,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    for name in ("freeze", "run", "verify"):
        mode.add_argument("--" + name, action="store_true")
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    args = parser.parse_args()
    if args.freeze:
        contract = freeze_contract(root=ROOT)
        print(
            json.dumps(
                {
                    "status": contract["status"],
                    "contract_digest": contract["contract_digest"],
                }
            )
        )
        return
    summary, directory = execute(
        root=ROOT, external_root=args.external_root, verify=args.verify
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "artifact_digest": summary["artifact_digest"],
                "run_dir": str(directory),
                "replay_verified": args.verify,
            }
        )
    )


if __name__ == "__main__":
    main()
