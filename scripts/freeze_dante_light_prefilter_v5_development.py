#!/usr/bin/env python3
"""Freeze the outcome-blind DANTE-Light v5 development decision contract."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_development_contract import (  # noqa: E402
    DEFAULT_OUTPUT,
    build_development_contract,
    write_contract,
)


def main() -> int:
    paths = {
        "development_contract": ROOT / "src/dante_light/prefilter_v5_development_contract.py",
        "development_evaluator": ROOT / "src/dante_light/prefilter_v5_development.py",
        "development_waveforms": ROOT / "src/dante_light/prefilter_v5_waveforms.py",
        "development_screening": ROOT / "src/dante_light/prefilter_v5_screening.py",
        "development_cli": ROOT / "scripts/run_dante_light_prefilter_v5_development.py",
        "development_verifier": ROOT / "scripts/verify_dante_light_prefilter_v5_development.py",
        "injection_reconstruction": ROOT / "src/dante_light/prefilter_v5_injections.py",
        "student_architectures": ROOT / "src/dante_light/prefilter_v4_student.py",
        "student_training": ROOT / "src/dante_light/prefilter_v5_training.py",
        "teacher": ROOT / "src/dante_light/prefilter_v5_teacher.py",
    }
    contract = build_development_contract(root=ROOT, code_paths=paths)
    write_contract(contract, DEFAULT_OUTPUT)
    print(
        json.dumps(
            {
                "status": contract["status"],
                "development_contract_digest": contract["development_contract_digest"],
                "audit_seed_uint64": contract["audit_seed_uint64"],
                "development_access_at_freeze": [],
                "confirmation_access_at_freeze": [],
                "o4b_access_at_freeze": [],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
