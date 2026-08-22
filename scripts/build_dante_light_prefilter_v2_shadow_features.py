#!/usr/bin/env python3
"""Build the frozen O4b shadow L4 v2 feature ledger after development PASS."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.executor import DeferredWindow
from src.dante_light.prefilter_features import build_shadow_feature_ledger
from src.dante_light.prefilter_v2_protocol import (
    DEFAULT_PROTOCOL_V2_PATH,
    load_prefilter_v2_protocol,
)
from src.dante_light.preprocessing import prepare_prefilter_v2_features


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "config/dante_light_o4b_shadow_v2.json",
    )
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--screening", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--strain-source",
        choices=("auto", "local-only", "gwosc-only"),
        default="auto",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V2_PATH)
    args = parser.parse_args()
    try:
        import json

        protocol = load_prefilter_v2_protocol(args.protocol)
        screening = json.loads(args.screening.read_text(encoding="utf-8"))
        if screening.get("status") != "PASS" or screening.get("protocol") != protocol.reference:
            raise ContractError("O4b v2 feature extraction requires the frozen development PASS")
        feature_config = dict(protocol.payload["feature_extraction"])
        pad_s = float(
            protocol.payload["cohort_augmentation"]["availability_preflight"][
                "whitening_context_pad_s"
            ]
        )
        ledger = build_shadow_feature_ledger(
            root=ROOT,
            manifest_path=args.manifest,
            records_path=args.records,
            output_dir=args.output_dir,
            limit=args.limit,
            schema_version=2,
            file_version="v2",
            feature_source=f"prefilter-v2:{protocol.payload['protocol_digest']}",
            scientific_mode="frozen_o4b_shadow_v2_feature_extraction",
            prepare=lambda task: prepare_prefilter_v2_features(
                task.window,
                local_only=args.strain_source == "local-only",
                remote_only=args.strain_source == "gwosc-only",
                config=feature_config,
                pad_s=pad_s,
            ),
        )
    except (OSError, json.JSONDecodeError, ContractError, DeferredWindow) as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    print(f"PASS: {ledger['row_count']} frozen O4b v2 feature rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
