"""O3a rescore workload audit; parent verification reads no native score."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError  # noqa: E402
from src.dante_light.o3a_native_calibration_cohort import (  # noqa: E402
    load_cohort_contract,
    verify_native_calibration_cohort,
)
from src.dante_light.o3a_native_rescore_preflight import preflight_from_verified_parents  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--external-root",
        type=Path,
        default=Path("/mnt/e/dante_cache/dante_light/o3a_native_v1"),
    )
    args = parser.parse_args()
    root = ROOT.resolve()
    external = args.external_root.resolve()
    calibration, calibration_dir = verify_native_calibration_cohort(
        root=root, external_root=external
    )
    # Its verifier independently re-verifies scan, cohort and index parents.
    scan = json.loads(
        (root / "artifacts/dante_light/o3a_native_v1/primary_scan.json").read_text(encoding="utf-8")
    )
    index = json.loads(
        (root / "artifacts/dante_light/o3a_native_v1/native_index.json").read_text(encoding="utf-8")
    )
    scan_dir = external / f"primary_scan_{scan['run_key']}"
    contract = load_cohort_contract(root=root)
    if (
        contract["parents"]["native_index"]["artifact_digest"] != index["artifact_digest"]
        or contract["parents"]["primary_scan"]["artifact_digest"] != scan["artifact_digest"]
    ):
        raise ContractError("O3a native-rescore preflight parents disagree")
    _rows, audit = preflight_from_verified_parents(
        scan_database=scan_dir / scan["database"]["filename"],
        calibration_ledger=calibration_dir / calibration["ledger"]["filename"],
        root=root,
        expected_calibration_rows_by_detector=calibration["counts_by_detector"],
        bootstrap_block_length_rows=int(contract["selection"]["block_length_rows"]),
    )
    if audit["candidate_rows_by_detector"] != scan["candidate_counts"]:
        raise ContractError("O3a native-rescore seed-count audit disagrees with scan")
    print(json.dumps({"status": "PASS_IDENTITY_SOURCE_PREFLIGHT", **audit}, sort_keys=True))


if __name__ == "__main__":
    main()
