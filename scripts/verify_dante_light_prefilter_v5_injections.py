#!/usr/bin/env python3
"""Verify the frozen v5 injection generator without reading outcomes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.prefilter_v5_injections import (  # noqa: E402
    load_frozen_trials,
    parameters_from_trial,
    reconstruct_frozen_trial,
)


DEFAULT_PROTOCOL = ROOT / "config/dante_light_prefilter_protocol_v5.json"
DEFAULT_TRIALS = ROOT / "config/dante_light_prefilter_v5_injection_trials.jsonl"


def verify(*, waveform_smoke: bool = False) -> dict:
    protocol = json.loads(DEFAULT_PROTOCOL.read_text(encoding="utf-8"))
    trials = load_frozen_trials(DEFAULT_TRIALS)
    systems: dict[str, int] = {}
    partitions: dict[str, int] = {}
    detectors: dict[str, int] = {}
    representatives: dict[str, dict] = {}
    for trial in trials.values():
        parameters_from_trial(trial, protocol)
        systems[str(trial["system"])] = systems.get(str(trial["system"]), 0) + 1
        partitions[str(trial["partition"])] = partitions.get(str(trial["partition"]), 0) + 1
        detectors[str(trial["detector"])] = detectors.get(str(trial["detector"]), 0) + 1
        representatives.setdefault(str(trial["system"]), trial)

    waveform_checks = []
    if waveform_smoke:
        for system, trial in sorted(representatives.items()):
            parameters, projected = reconstruct_frozen_trial(trial, protocol)
            waveform_checks.append(
                {
                    "system": system,
                    "approximant": parameters.approximant,
                    "samples": int(projected.detector_strain.size),
                    "duration_s": float(
                        projected.detector_strain.size / parameters.sample_rate_hz
                    ),
                    "chi_ns": parameters.spin_2z,
                    "lambda_ns": parameters.lambda_2,
                    "detector_delay_s": projected.detector_delay_s,
                }
            )
    return {
        "status": "PASS_OUTCOME_BLIND",
        "trial_count": len(trials),
        "systems": dict(sorted(systems.items())),
        "partitions": dict(sorted(partitions.items())),
        "detectors": dict(sorted(detectors.items())),
        "outcome_fields_accessed": [],
        "waveform_smoke_executed": waveform_smoke,
        "waveform_checks": waveform_checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--waveform-smoke",
        action="store_true",
        help="also generate one LALSimulation waveform per frozen system",
    )
    args = parser.parse_args()
    print(json.dumps(verify(waveform_smoke=args.waveform_smoke), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
