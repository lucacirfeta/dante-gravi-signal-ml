#!/usr/bin/env python3
"""Freeze outcome-blind availability-screened L4 v2 cohort identities."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.executor import DeferredWindow
from src.dante_light.prefilter_splits import write_prefilter_splits
from src.dante_light.prefilter_v2_protocol import (
    DEFAULT_PROTOCOL_V2_PATH,
    load_prefilter_v2_protocol,
)
from src.dante_light.prefilter_v2_splits import build_prefilter_v2_splits
from src.dante_light.preprocessing import preflight_prefilter_window


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "config/dante_light_prefilter_splits_v2.json",
    )
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL_V2_PATH)
    parser.add_argument(
        "--strain-source",
        choices=("auto", "local-only", "gwosc-only"),
        default="auto",
    )
    args = parser.parse_args()
    try:
        protocol = load_prefilter_v2_protocol(args.protocol)
        known_rules = protocol.payload["cohort_augmentation"]["known_glitch"]
        from src.core.reference_index_builder import download_gs_classifications_csv

        for detector, relative_path in known_rules["catalog_paths"].items():
            catalog_path = ROOT / str(relative_path)
            if not catalog_path.exists():
                download_gs_classifications_csv(
                    catalog_path.parent,
                    run="O3b",
                    detector=detector,
                )
        feature_rules = protocol.payload["feature_extraction"]
        pad_s = float(
            protocol.payload["cohort_augmentation"]["availability_preflight"][
                "whitening_context_pad_s"
            ]
        )
        payload = build_prefilter_v2_splits(
            root=ROOT,
            protocol=protocol,
            preflight=lambda window: preflight_prefilter_window(
                window,
                local_only=args.strain_source == "local-only",
                remote_only=args.strain_source == "gwosc-only",
                pad_s=pad_s,
                expected_sample_rate_hz=int(feature_rules["sample_rate_hz"]),
            ),
        )
        write_prefilter_splits(payload, args.output)
    except (ContractError, DeferredWindow) as exc:
        print(f"NOT_READY: {exc}", file=sys.stderr)
        return 2
    for role, cohort in payload["cohorts"].items():
        print(role, cohort["counts"], cohort["split_sha256"])
    print("PASS: O4b outcomes were not accessed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
