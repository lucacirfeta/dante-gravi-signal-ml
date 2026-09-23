#!/usr/bin/env python3
"""Freeze, preflight, run or verify O3a-only native score replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o3a_native_rescore import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    clear_infrastructure_failure,
    cuda_preflight_rescore,
    preflight_rescore,
    run_native_rescore,
    verify_native_rescore,
    write_compact_rescore_artifact,
    write_rescore_contract,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--contract-only", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--cuda-preflight", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--clear-infrastructure-failure", action="store_true")
    args = parser.parse_args()
    if args.contract_only:
        contract = write_rescore_contract(root=ROOT)
        print(json.dumps({"status": contract["status"], "contract_digest": contract["contract_digest"]}))
    elif args.preflight:
        preflight, _ = preflight_rescore(root=ROOT, external_root=args.external_root)
        print(json.dumps({"status": preflight["status"], "run_key": preflight["run_key"], "audit": preflight["audit"]}))
    elif args.cuda_preflight:
        result, _ = cuda_preflight_rescore(root=ROOT, external_root=args.external_root)
        print(json.dumps({"status": result["status"], "run_key": result["run_key"]}))
    elif args.run:
        result, _ = run_native_rescore(root=ROOT, external_root=args.external_root)
        print(json.dumps({"status": result["status"], "run_key": result["run_key"], "row_total": result["row_total"]}))
    elif args.verify:
        result, _ = verify_native_rescore(root=ROOT, external_root=args.external_root)
        compact = write_compact_rescore_artifact(root=ROOT, external_root=args.external_root)
        print(json.dumps({"status": result["status"], "artifact_digest": compact["artifact_digest"]}))
    elif args.clear_infrastructure_failure:
        path = clear_infrastructure_failure(root=ROOT, external_root=args.external_root)
        print(json.dumps({"status": "ARCHIVED_INFRASTRUCTURE_FAILURE", "archive": str(path)}))


if __name__ == "__main__":
    main()
