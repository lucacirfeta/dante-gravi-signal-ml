#!/usr/bin/env python3
"""Run the label-free NSBH mini-bank cost/coverage feasibility study.

Requires the pinned WSL LALSuite environment.  The generated curve is an
illustrative aligned-spin, in-family diagnostic and defines no minimal-match
gate or v4 protocol.
"""

from __future__ import annotations

import argparse
from itertools import product
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

import lal
import lalsimulation as lalsim
import numpy as np
import scipy

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_bank import (
    benchmark_complex_filter_kernel,
    greedy_farthest_bank,
    phase_maximized_noise_weighted_match,
)


DEFAULT_CONFIG = ROOT / "config" / "dante_light_prefilter_v4_feasibility.json"
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "dante_light"
    / "prefilter_l4_v4_feasibility"
    / "mini_bank_coverage_v4.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _parameters(config: dict) -> list[dict[str, float]]:
    return [
        {
            "black_hole_mass_msun": float(black_hole_mass),
            "neutron_star_mass_msun": float(neutron_star_mass),
            "black_hole_aligned_spin": float(black_hole_spin),
            "neutron_star_tidal_lambda": float(tidal_lambda),
        }
        for black_hole_mass, neutron_star_mass, black_hole_spin, tidal_lambda in product(
            config["black_hole_mass_msun"],
            config["neutron_star_mass_msun"],
            config["black_hole_aligned_spin"],
            config["neutron_star_tidal_lambda"],
        )
    ]


def _waveform(
    parameters: dict[str, float], *, config: dict, frequency_count: int
) -> np.ndarray:
    dictionary = lal.CreateDict()
    lalsim.SimInspiralWaveformParamsInsertTidalLambda2(
        dictionary, parameters["neutron_star_tidal_lambda"]
    )
    waveform, _cross = lalsim.SimInspiralChooseFDWaveform(
        parameters["black_hole_mass_msun"] * lal.MSUN_SI,
        parameters["neutron_star_mass_msun"] * lal.MSUN_SI,
        0.0,
        0.0,
        parameters["black_hole_aligned_spin"],
        0.0,
        0.0,
        0.0,
        float(config["distance_mpc"]) * 1.0e6 * lal.PC_SI,
        float(config["inclination_rad"]),
        0.0,
        0.0,
        0.0,
        0.0,
        float(config["delta_f_hz"]),
        float(config["f_low_hz"]),
        2048.0,
        float(config["f_low_hz"]),
        dictionary,
        lalsim.GetApproximantFromString(str(config["waveform_approximant"])),
    )
    result = np.zeros(frequency_count, dtype=np.complex128)
    raw = np.asarray(waveform.data.data, dtype=np.complex128)
    if raw.size > result.size:
        raise ContractError("generated waveform exceeds the configured FFT grid")
    result[: raw.size] = raw
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    config_path = args.config.resolve()
    parent = json.loads(config_path.read_text(encoding="utf-8"))
    if parent.get("status") != "FEASIBILITY_ONLY_NOT_A_V4_PROTOCOL":
        raise ContractError("refusing bank study outside the feasibility-only contract")
    boundary = parent["scientific_boundary"]
    if any(
        bool(boundary.get(key))
        for key in (
            "may_freeze_v4",
            "may_select_a_candidate",
            "may_access_development_labels",
            "may_access_reserved_confirmation",
            "may_access_o4b_outcomes",
        )
    ):
        raise ContractError("bank feasibility config permits a forbidden action")
    config = parent["mini_bank_probe"]
    sample_rate = int(parent["signal_contract"]["sample_rate_hz"])
    duration = float(parent["signal_contract"]["duration_s"])
    n_time_samples = int(round(sample_rate * duration))
    expected_delta_f = 1.0 / duration
    if not np.isclose(float(config["delta_f_hz"]), expected_delta_f):
        raise ContractError("mini-bank delta_f is inconsistent with the signal duration")
    frequency_count = n_time_samples // 2 + 1
    frequencies = np.arange(frequency_count, dtype=np.float64) * expected_delta_f
    selected = (frequencies >= float(config["f_low_hz"])) & (
        frequencies <= float(config["f_high_hz"])
    )
    psd = np.full(frequency_count, np.inf, dtype=np.float64)
    psd[selected] = np.asarray(
        [lalsim.SimNoisePSDaLIGOZeroDetHighPower(float(value)) for value in frequencies[selected]],
        dtype=np.float64,
    )
    grid = _parameters(config)
    waveforms = [
        _waveform(parameters, config=config, frequency_count=frequency_count)
        for parameters in grid
    ]
    for waveform in waveforms:
        waveform[~selected] = 0.0
    count = len(grid)
    matrix = np.eye(count, dtype=np.float64)
    for left in range(count):
        for right in range(left + 1, count):
            value = phase_maximized_noise_weighted_match(
                waveforms[left],
                waveforms[right],
                psd,
                delta_f_hz=expected_delta_f,
                n_time_samples=n_time_samples,
            )
            matrix[left, right] = value
            matrix[right, left] = value
    anchor = {key: float(value) for key, value in config["anchor"].items()}
    matching_anchors = [index for index, row in enumerate(grid) if row == anchor]
    if len(matching_anchors) != 1:
        raise ContractError("mini-bank anchor is not unique in the feasibility grid")
    coverage = greedy_farthest_bank(
        matrix,
        bank_sizes=config["bank_sizes"],
        anchor_index=matching_anchors[0],
    )
    for entry in coverage["curve"].values():
        entry["selected_parameters"] = [grid[index] for index in entry["selected_indices"]]
    kernel = benchmark_complex_filter_kernel(
        n_time_samples=n_time_samples,
        bank_sizes=config["bank_sizes"],
        repetitions=int(config["kernel_benchmark_repetitions"]),
        warmup=int(config["kernel_benchmark_warmup"]),
        seed=int(parent["student_probe"]["seed"]),
    )
    matrix_bytes = np.ascontiguousarray(matrix, dtype=np.float64).tobytes()
    payload = {
        "schema_version": 1,
        "status": "COMPLETE_FEASIBILITY_ONLY",
        "routing_enabled": False,
        "candidate_selected": False,
        "protocol_frozen": False,
        "outcome_access": {
            "development_labels": False,
            "reserved_confirmation": False,
            "o4b": False,
        },
        "interpretation": (
            "Illustrative aligned-spin in-family parameter-space coverage and runtime only; "
            "no minimal-match threshold, population coverage, or retention claim."
        ),
        "config": {"path": str(config_path.relative_to(ROOT)), "sha256": _sha256(config_path)},
        "waveform_grid": grid,
        "match_matrix": {
            "shape": list(matrix.shape),
            "dtype": "float64",
            "sha256": hashlib.sha256(matrix_bytes).hexdigest(),
            "values": matrix.tolist(),
        },
        "coverage": coverage,
        "kernel_benchmark": kernel,
        "limitations": config["limitations"],
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpu_count": os.cpu_count(),
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "lal": lal.__version__,
        },
        "source_sha256": {
            "runner": _sha256(Path(__file__).resolve()),
            "bank_module": _sha256(ROOT / "src/dante_light/prefilter_v4_bank.py"),
        },
    }
    _atomic_json(args.output.resolve(), payload)
    print(json.dumps({"status": payload["status"], "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
