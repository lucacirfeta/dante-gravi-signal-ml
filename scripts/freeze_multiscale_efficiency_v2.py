"""Freeze or verify the O4a multiscale-efficiency-v2 identity cohort."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.pipeline_v3_multiscale.efficiency_v2 import (  # noqa: E402
    freeze_cohort,
    verify_cohort,
)

DEFAULT_PRIMARY = Path(
    "E:/dante_cache/dante_light/o4a_corrected_v2/"
    "primary_scan_5c19c3141fdc79bed75434362ffbbeb31fe36a99a4e64554482cb0023f0631bb/"
    "primary_scan.sqlite"
)
DEFAULT_INDEX_MANIFEST = Path(
    "E:/dante_cache/dante_light/o4a_canonical_provenance_rerun_v1/index/"
    "native_index_750681d0e35f1a9f766e37e6d3b858280b903d50dbbc982458f0662c6553488b/"
    "native_index_consumption_manifest.json"
)
DEFAULT_INDEX_COHORT = Path(
    "E:/dante_cache/dante_light/o4a_canonical_provenance_rerun_v1/cohort/"
    "native_cohort_0b76b9852c825fe26344f6468ff464865f10471d8b289912680225d08b447397/"
    "native_cohort.jsonl"
)
DEFAULT_CALIBRATION = Path(
    "E:/dante_cache/dante_light/o4a_canonical_provenance_rerun_v1/native_calibration/"
    "native_calibration_152d077c0c2211b3d7574ad230e0a672e69027c1eaa220a9af20df9e5b7f7b4a/"
    "native_calibration_cohort.jsonl"
)
DEFAULT_OUTPUT = Path("E:/dante_cache/dante_light/multiscale_efficiency_v2")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-scan-db", type=Path, default=DEFAULT_PRIMARY)
    parser.add_argument(
        "--native-index-manifest", type=Path, default=DEFAULT_INDEX_MANIFEST
    )
    parser.add_argument(
        "--native-index-cohort-ledger", type=Path, default=DEFAULT_INDEX_COHORT
    )
    parser.add_argument(
        "--native-calibration-ledger", type=Path, default=DEFAULT_CALIBRATION
    )
    parser.add_argument("--external-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-run-dir", type=Path)
    args = parser.parse_args()
    if args.verify_run_dir:
        summary = verify_cohort(run_dir=args.verify_run_dir)
        run_dir = args.verify_run_dir
    else:
        summary, run_dir = freeze_cohort(
            primary_scan_db=args.primary_scan_db,
            native_index_manifest=args.native_index_manifest,
            native_index_cohort_ledger=args.native_index_cohort_ledger,
            native_calibration_ledger=args.native_calibration_ledger,
            external_root=args.external_root,
        )
    print(f"{summary['status']}: {run_dir}")
    print(f"artifact_digest={summary['artifact_digest']}")


if __name__ == "__main__":
    main()
