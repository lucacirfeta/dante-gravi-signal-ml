#!/usr/bin/env python3
"""Build or verify the non-gating DANTE-Light L4 v4 diagnostic artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_diagnostics import (
    analyze_v4_development_diagnostics,
    verify_v4_development_diagnostics,
    write_v4_development_diagnostics,
)


def _arguments(artifact_dir: Path) -> dict:
    return {
        "root": ROOT,
        "ledgers": {
            role: artifact_dir / f"{role}_feature_ledger_v4_development.json"
            for role in ("background", "robust_candidate", "known_glitch", "injection")
        },
        "screening_path": artifact_dir / "screening_result_v4.json",
        "feasibility_path": ROOT
        / "artifacts/dante_light/prefilter_l4_v4_feasibility/feasibility_summary_v4.json",
        "v2_diagnostics_path": ROOT
        / "artifacts/dante_light/prefilter_l4_v2/diagnostics_v2.json",
        "v3_summary_path": ROOT
        / "artifacts/dante_light/prefilter_l4_v3/screening_summary_v3.json",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=ROOT / "artifacts/dante_light/prefilter_l4_v4_development",
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    output = args.artifact_dir / "diagnostics_v4.json"
    try:
        analysis_arguments = _arguments(args.artifact_dir)
        if args.verify:
            result = verify_v4_development_diagnostics(
                output, **analysis_arguments
            )
        else:
            result = analyze_v4_development_diagnostics(**analysis_arguments)
            write_v4_development_diagnostics(result, output)
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
