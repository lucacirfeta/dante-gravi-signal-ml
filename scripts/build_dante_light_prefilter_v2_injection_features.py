#!/usr/bin/env python3
"""Reconstruct frozen CBC injections and build the L4 v2 feature ledger."""

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
from src.dante_light.prefilter_injections import (
    load_injection_trials,
    prepare_injection_prefilter_features,
)
from src.dante_light.prefilter_v2 import extract_prefilter_v2_features
from src.dante_light.prefilter_v2_protocol import (
    DEFAULT_PROTOCOL_V2_PATH,
    load_prefilter_v2_protocol,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_splits_v2.json",
    )
    parser.add_argument("--trials", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V2_PATH)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v2_protocol(args.protocol)
        feature_config = dict(protocol.payload["feature_extraction"])
        trials = load_injection_trials(args.trials)

        def build_features(values, sample_rate_hz):
            if sample_rate_hz != int(feature_config["sample_rate_hz"]):
                raise ContractError("injection sample rate differs from v2 protocol")
            return extract_prefilter_v2_features(values, config=feature_config)

        ledger = build_split_feature_ledger(
            root=ROOT,
            split_path=args.split,
            role="injection",
            output_dir=args.output_dir,
            limit=args.limit,
            workers=args.workers,
            schema_version=2,
            file_version="v2",
            feature_source=f"prefilter-v2:{protocol.payload['protocol_digest']}",
            scientific_mode="research_only_v2_development_feature_extraction",
            accepted_split_statuses=("availability_screened_before_feature_extraction",),
            verify_preflight_strain=True,
            prepare=lambda task: prepare_injection_prefilter_features(
                task,
                trials=trials,
                feature_builder=build_features,
            ),
        )
    except (ContractError, DeferredWindow) as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{ledger['status'].upper()}: {ledger['row_count']} injection rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
