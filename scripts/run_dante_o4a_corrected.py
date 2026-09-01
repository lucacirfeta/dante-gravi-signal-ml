#!/usr/bin/env python3
"""Acquire or verify inputs for the corrected O4a reconstruction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.o4a_corrected_execution import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT,
    acquire_missing_calibration_inputs,
    run_primary_calibration,
    run_primary_scan,
    validate_acquisition_manifest,
    verify_primary_calibration,
    verify_primary_scan,
)
from src.dante_light.o4a_corrected_protocol import (  # noqa: E402
    CURRENT_OUTPUT_REL as OUTPUT_REL,
    validate_corrected_protocol,
)
from src.dante_light.o4a_corrected_runtime import (  # noqa: E402
    write_canonical_runtime_contract,
)
from src.dante_light.o4a_corrected_native import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_NATIVE_EXTERNAL_ROOT,
    freeze_native_cohort,
    verify_native_cohort,
)
from src.dante_light.o4a_corrected_native_index import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_NATIVE_INDEX_EXTERNAL_ROOT,
    build_native_index,
    verify_native_index,
)
from src.dante_light.o4a_corrected_native_rescore import (  # noqa: E402
    DEFAULT_EXTERNAL_ROOT as DEFAULT_NATIVE_RESCORE_EXTERNAL_ROOT,
    run_native_rescore,
    verify_native_rescore,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=(
            "freeze-runtime",
            "acquire",
            "verify-inputs",
            "calibrate-primary",
            "verify-calibration",
            "scan-primary",
            "verify-scan",
            "freeze-native-cohort",
            "verify-native-cohort",
            "build-native-index",
            "verify-native-index",
            "rescore-native",
            "verify-native-rescore",
        ),
        required=True,
    )
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument(
        "--native-external-root", type=Path, default=DEFAULT_NATIVE_EXTERNAL_ROOT
    )
    parser.add_argument(
        "--native-index-external-root",
        type=Path,
        default=DEFAULT_NATIVE_INDEX_EXTERNAL_ROOT,
    )
    parser.add_argument(
        "--native-rescore-external-root",
        type=Path,
        default=DEFAULT_NATIVE_RESCORE_EXTERNAL_ROOT,
    )
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--detector-mode", default="parallel_shared_scorer")
    parser.add_argument("--queue-depth-batches", type=int, default=2)
    parser.add_argument("--queue-topology", default="single_combined_bounded_queue")
    parser.add_argument("--database-commit-rows", type=int, default=1024)
    parser.add_argument("--quality-batch-size", type=int, default=128)
    parser.add_argument("--native-encoder-batch-size", type=int, default=8)
    args = parser.parse_args()
    if args.stage == "freeze-runtime":
        contract = write_canonical_runtime_contract(root=ROOT, device=args.device)
        print(json.dumps(contract, indent=2, sort_keys=True))
        return 0
    if args.stage == "acquire":
        manifest, run_dir = acquire_missing_calibration_inputs(
            root=ROOT, external_root=args.external_root
        )
        print(json.dumps({"run_dir": str(run_dir), **manifest}, indent=2, sort_keys=True))
        return 0
    if args.stage == "calibrate-primary":
        summary, run_dir = run_primary_calibration(
            root=ROOT,
            raw_root=args.raw_root.resolve(),
            external_root=args.external_root.resolve(),
            device=args.device,
            workers=args.workers,
            batch_size=args.batch_size,
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "verify-calibration":
        summary, run_dir = verify_primary_calibration(
            root=ROOT, external_root=args.external_root.resolve()
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "scan-primary":
        summary, run_dir = run_primary_scan(
            root=ROOT,
            raw_root=args.raw_root.resolve(),
            external_root=args.external_root.resolve(),
            device=args.device,
            workers=args.workers,
            batch_size=args.batch_size,
            detector_mode=args.detector_mode,
            queue_depth_batches=args.queue_depth_batches,
            queue_topology=args.queue_topology,
            database_commit_rows=args.database_commit_rows,
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "verify-scan":
        summary, run_dir = verify_primary_scan(
            root=ROOT, external_root=args.external_root.resolve()
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "freeze-native-cohort":
        summary, run_dir = freeze_native_cohort(
            root=ROOT,
            raw_root=args.raw_root.resolve(),
            primary_external_root=args.external_root.resolve(),
            external_root=args.native_external_root.resolve(),
            workers=args.workers,
            quality_batch_size=args.quality_batch_size,
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "verify-native-cohort":
        summary, run_dir = verify_native_cohort(
            root=ROOT,
            primary_external_root=args.external_root.resolve(),
            external_root=args.native_external_root.resolve(),
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "build-native-index":
        summary, run_dir = build_native_index(
            root=ROOT,
            raw_root=args.raw_root.resolve(),
            primary_external_root=args.external_root.resolve(),
            cohort_external_root=args.native_external_root.resolve(),
            external_root=args.native_index_external_root.resolve(),
            device=args.device,
            workers=args.workers,
            encoder_batch_size=args.native_encoder_batch_size,
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "verify-native-index":
        summary, run_dir = verify_native_index(
            root=ROOT,
            primary_external_root=args.external_root.resolve(),
            cohort_external_root=args.native_external_root.resolve(),
            external_root=args.native_index_external_root.resolve(),
            device=args.device,
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "rescore-native":
        summary, run_dir = run_native_rescore(
            root=ROOT,
            raw_root=args.raw_root.resolve(),
            primary_external_root=args.external_root.resolve(),
            cohort_external_root=args.native_external_root.resolve(),
            index_external_root=args.native_index_external_root.resolve(),
            external_root=args.native_rescore_external_root.resolve(),
            device=args.device,
            workers=args.workers,
            batch_size=args.batch_size,
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    if args.stage == "verify-native-rescore":
        summary, run_dir = verify_native_rescore(
            root=ROOT,
            primary_external_root=args.external_root.resolve(),
            cohort_external_root=args.native_external_root.resolve(),
            index_external_root=args.native_index_external_root.resolve(),
            external_root=args.native_rescore_external_root.resolve(),
            device=args.device,
        )
        print(json.dumps({"run_dir": str(run_dir), **summary}, indent=2, sort_keys=True))
        return 0
    protocol = validate_corrected_protocol(
        json.loads((ROOT / OUTPUT_REL).read_text(encoding="utf-8")), ROOT
    )
    run_dir = args.external_root.resolve() / f"inputs_{protocol['protocol_digest']}"
    path = run_dir / "acquisition_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    validate_acquisition_manifest(manifest, run_dir=run_dir, protocol=protocol)
    print(f"PASS {path} {manifest['manifest_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
