#!/usr/bin/env python3
"""Build the development-only injection ledger for the frozen L4 v3 A/B screen."""

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
    resolve_frozen_injection_trials,
)
from src.dante_light.prefilter_v3 import extract_prefilter_v3_features
from src.dante_light.prefilter_v3_protocol import (
    DEFAULT_PROTOCOL_V3_PATH,
    load_prefilter_v3_protocol,
    verify_prefilter_v3_sources,
)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V3_PATH)
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v3_protocol(args.protocol)
        verify_prefilter_v3_sources(protocol, root=ROOT)
        feature_config = dict(protocol.payload["feature_extraction"])
        split_path = ROOT / str(protocol.payload["parent_v2"]["split"]["path"])
        trials = load_injection_trials(
            resolve_frozen_injection_trials(split_path, root=ROOT)
        )

        def build_features(values, sample_rate_hz):
            if sample_rate_hz != int(feature_config["sample_rate_hz"]):
                raise ContractError("injection sample rate differs from v3 protocol")
            return extract_prefilter_v3_features(values, config=feature_config)

        ledger = build_split_feature_ledger(
            root=ROOT,
            split_path=split_path,
            role="injection",
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
            prepare=lambda task: prepare_injection_prefilter_features(
                task,
                trials=trials,
                feature_builder=build_features,
            ),
        )
    except (ContractError, DeferredWindow) as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"{ledger['status'].upper()}: {ledger['row_count']} injection development rows")
    print("SEALED: reserved confirmation and O4b outcomes were not accessed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
