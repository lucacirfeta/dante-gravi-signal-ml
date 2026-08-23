#!/usr/bin/env python3
"""Build one frozen DANTE-Light v4 development-only feature ledger."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_dante_light_prefilter_v4_freeze import verify as verify_freeze
from src.dante_light.contracts import ContractError
from src.dante_light.executor import DeferredWindow
from src.dante_light.prefilter_v4_development import (
    build_development_ledger,
    load_injection_trials,
    prepare_v4_injection_features,
)
from src.dante_light.prefilter_v4_protocol import load_protocol
from src.dante_light.preprocessing import prepare_prefilter_v4_features


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role",
        required=True,
        choices=("background", "robust_candidate", "known_glitch", "injection"),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--strain-source", choices=("auto", "local-only", "gwosc-only"), default="auto"
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--protocol",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_protocol_v4.json",
    )
    parser.add_argument(
        "--split",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_splits_v4.json",
    )
    args = parser.parse_args()
    try:
        freeze = verify_freeze()
        if freeze["status"] != "PASS_IDENTITY_ONLY_NOT_OPENED":
            raise ContractError("v4 identity freeze is not unopened")
        protocol = load_protocol(args.protocol)
        config = dict(protocol.payload["feature_extraction"])
        pad_s = float(config["whitening_context_pad_s"])
        if args.role == "injection":
            if args.strain_source == "gwosc-only":
                raise ContractError("v4 injection reconstruction does not permit forced remote-only strain")
            trials = load_injection_trials(
                ROOT / "config/dante_light_prefilter_v4_injection_trials.jsonl"
            )
            prepare = lambda task: prepare_v4_injection_features(
                task,
                protocol=protocol,
                trials=trials,
                local_only=args.strain_source == "local-only",
            )
        else:
            prepare = lambda task: prepare_prefilter_v4_features(
                task.window,
                local_only=args.strain_source == "local-only",
                remote_only=args.strain_source == "gwosc-only",
                config=config,
                pad_s=pad_s,
            )
        ledger = build_development_ledger(
            root=ROOT,
            split_path=args.split,
            protocol=protocol,
            role=args.role,
            output_dir=args.output_dir,
            prepare=prepare,
            workers=args.workers,
            limit=args.limit,
        )
    except (ContractError, DeferredWindow) as exc:
        print(f"V4_NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{ledger['status'].upper()}: {ledger['row_count']} {args.role} development rows")
    print("SEALED: confirmation and O4b were not accessed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
