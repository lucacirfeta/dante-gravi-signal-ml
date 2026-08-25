#!/usr/bin/env python3
"""Build development-only real-strain ledgers for the frozen L4 v3 A/B screen."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.executor import DeferredWindow
from src.dante_light.prefilter_features import build_split_feature_ledger
from src.dante_light.prefilter_v3_protocol import (
    DEFAULT_PROTOCOL_V3_PATH,
    load_prefilter_v3_protocol,
    verify_prefilter_v3_sources,
)
from src.dante_light.preprocessing import prepare_prefilter_v3_features


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role",
        required=True,
        choices=("background", "robust_candidate", "known_glitch"),
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--strain-source",
        choices=("auto", "local-only", "gwosc-only"),
        default="auto",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V3_PATH)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v3_protocol(args.protocol)
        verify_prefilter_v3_sources(protocol, root=ROOT)
        feature_config = dict(protocol.payload["feature_extraction"])
        pad_s = float(feature_config["whitening_context_pad_s"])
        split_path = ROOT / str(protocol.payload["parent_v2"]["split"]["path"])
        ledger = build_split_feature_ledger(
            root=ROOT,
            split_path=split_path,
            role=args.role,
            output_dir=args.output_dir,
            limit=args.limit,
            workers=args.workers,
            schema_version=3,
            file_version="v3_development",
            feature_source=f"prefilter-v3:{protocol.payload['protocol_digest']}",
            scientific_mode="v3_hypothesis_generating_development_feature_extraction",
            accepted_split_statuses=("availability_screened_before_feature_extraction",),
            verify_preflight_strain=True,
            partitions=("development",),
            prepare=lambda task: prepare_prefilter_v3_features(
                task.window,
                local_only=args.strain_source == "local-only",
                remote_only=args.strain_source == "gwosc-only",
                config=feature_config,
                pad_s=pad_s,
            ),
        )
    except (ContractError, DeferredWindow) as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{ledger['status'].upper()}: {ledger['row_count']} {args.role} development rows")
    print("SEALED: reserved confirmation and O4b outcomes were not accessed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
