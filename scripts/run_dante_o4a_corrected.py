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
    validate_acquisition_manifest,
    verify_primary_calibration,
)
from src.dante_light.o4a_corrected_protocol import (  # noqa: E402
    OUTPUT_REL,
    validate_corrected_protocol,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("acquire", "verify-inputs", "calibrate-primary", "verify-calibration"),
        required=True,
    )
    parser.add_argument("--external-root", type=Path, default=DEFAULT_EXTERNAL_ROOT)
    parser.add_argument("--raw-root", type=Path, default=Path("E:/o4a"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
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
