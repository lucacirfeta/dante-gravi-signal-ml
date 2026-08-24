"""Frozen waveform reconstruction for DANTE-Light prefilter v5 injections.

This module reconstructs only the waveform and detector projection specified by
the outcome-blind v5 trial table.  It does not read development or confirmation
outcomes, score a window, or select an operating point.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256


@dataclass(frozen=True)
class FrozenWaveformParameters:
    approximant: str
    mass_1_msun: float
    mass_2_msun: float
    spin_1z: float
    spin_2z: float
    lambda_1: float
    lambda_2: float
    distance_mpc: float
    inclination_rad: float
    f_low_hz: float
    sample_rate_hz: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectedWaveform:
    plus: np.ndarray
    cross: np.ndarray
    detector_strain: np.ndarray
    detector_delay_s: float
    geocentric_merger_gps: float
    detector_merger_gps: float
    injection_array_center_gps: float


def load_frozen_trials(path: Path) -> dict[str, dict[str, Any]]:
    """Load the frozen identity-only trial table and verify every row."""

    trials: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        body = dict(row)
        declared = body.pop("trial_digest", None)
        if declared != canonical_json_sha256(body):
            raise ContractError("v5 injection trial digest mismatch")
        if row.get("outcome_fields_present") != []:
            raise ContractError("v5 injection trial exposes outcome fields")
        source_id = str(row.get("source_id", ""))
        if not source_id or source_id in trials:
            raise ContractError("v5 injection trial identity is empty or duplicated")
        trials[source_id] = row
    if not trials:
        raise ContractError("v5 injection trial table is empty")
    return trials


def parameters_from_trial(
    trial: Mapping[str, Any], protocol: Mapping[str, Any]
) -> FrozenWaveformParameters:
    """Resolve one trial strictly against the frozen waveform contract."""

    waveforms = protocol["approved_design"]["waveforms"]
    sample_rate = int(waveforms["sample_rate_hz"])
    system = str(trial["system"])
    population = str(trial["population"])

    if population == "legacy_comparability":
        legacy = waveforms["legacy_comparability"]
        system_contract = legacy["systems"].get(system)
        if system_contract is None:
            raise ContractError(f"v5 legacy injection system is not frozen: {system}")
        expected_approximant = str(legacy["approximant"])
        parameters = FrozenWaveformParameters(
            approximant=expected_approximant,
            mass_1_msun=float(system_contract["mass_1_msun"]),
            mass_2_msun=float(system_contract["mass_2_msun"]),
            spin_1z=0.0,
            spin_2z=0.0,
            lambda_1=0.0,
            lambda_2=0.0,
            distance_mpc=float(trial["distance_mpc"]),
            inclination_rad=float(trial["inclination_rad"]),
            f_low_hz=float(system_contract["f_low_hz"]),
            sample_rate_hz=sample_rate,
        )
    elif population == "aligned_tidal_nsbh_stress":
        stress = waveforms["aligned_tidal_nsbh_stress"]
        if system != str(stress["system"]):
            raise ContractError("v5 tidal trial/system mismatch")
        expected_approximant = str(stress["approximant"])
        parameters = FrozenWaveformParameters(
            approximant=expected_approximant,
            mass_1_msun=float(trial["mass_1_msun"]),
            mass_2_msun=float(trial["mass_2_msun"]),
            spin_1z=float(trial["spin_1z"]),
            spin_2z=float(trial["spin_2z"]),
            lambda_1=0.0,
            lambda_2=float(trial["lambda_2"]),
            distance_mpc=float(trial["distance_mpc"]),
            inclination_rad=float(trial["inclination_rad"]),
            f_low_hz=float(trial["f_low_hz"]),
            sample_rate_hz=sample_rate,
        )
        if parameters.spin_2z != float(stress["neutron_star_aligned_spin"]):
            raise ContractError("IMRPhenomNSBH requires the frozen chi_NS=0")
        bounded = {
            "mass_1_msun": ("black_hole_mass_msun", parameters.mass_1_msun),
            "mass_2_msun": ("neutron_star_mass_msun", parameters.mass_2_msun),
            "spin_1z": ("black_hole_aligned_spin", parameters.spin_1z),
            "lambda_2": ("neutron_star_tidal_lambda", parameters.lambda_2),
        }
        for field, (contract_key, value) in bounded.items():
            low, high = map(float, stress[contract_key])
            if not low <= value <= high:
                raise ContractError(f"v5 tidal trial {field} lies outside frozen bounds")
    else:
        raise ContractError(f"v5 injection population is not frozen: {population}")

    if str(trial["approximant"]) != parameters.approximant:
        raise ContractError("v5 injection approximant differs from frozen protocol")
    if float(trial["f_low_hz"]) != parameters.f_low_hz:
        raise ContractError("v5 injection f_low differs from frozen protocol")
    if parameters.mass_1_msun < parameters.mass_2_msun:
        raise ContractError("v5 waveform body ordering must remain BH/primary first")
    return parameters


def generate_polarizations(
    parameters: FrozenWaveformParameters,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate the frozen LALSimulation TD waveform without rescaling."""

    import lal
    import lalsimulation as lalsim

    try:
        approximant = getattr(lalsim, parameters.approximant)
    except AttributeError as exc:
        raise ContractError(
            f"LALSimulation lacks approximant {parameters.approximant}"
        ) from exc
    lal_parameters = lal.CreateDict()
    lalsim.SimInspiralWaveformParamsInsertTidalLambda1(
        lal_parameters, parameters.lambda_1
    )
    lalsim.SimInspiralWaveformParamsInsertTidalLambda2(
        lal_parameters, parameters.lambda_2
    )
    hp, hc = lalsim.SimInspiralChooseTDWaveform(
        parameters.mass_1_msun * lal.MSUN_SI,
        parameters.mass_2_msun * lal.MSUN_SI,
        0.0,
        0.0,
        parameters.spin_1z,
        0.0,
        0.0,
        parameters.spin_2z,
        parameters.distance_mpc * 1e6 * lal.PC_SI,
        parameters.inclination_rad,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0 / parameters.sample_rate_hz,
        parameters.f_low_hz,
        parameters.f_low_hz,
        lal_parameters,
        approximant,
    )
    plus = np.asarray(hp.data.data, dtype=np.float64)
    cross = np.asarray(hc.data.data, dtype=np.float64)
    if plus.shape != cross.shape or plus.ndim != 1 or plus.size == 0:
        raise ContractError("LALSimulation returned invalid v5 polarizations")
    if not np.isfinite(plus).all() or not np.isfinite(cross).all():
        raise ContractError("LALSimulation returned non-finite v5 polarizations")
    return plus, cross


def project_frozen_waveform(
    plus: np.ndarray,
    cross: np.ndarray,
    *,
    detector: str,
    ra_rad: float,
    dec_rad: float,
    psi_rad: float,
    geocentric_merger_gps: float,
    sample_rate_hz: int,
) -> ProjectedWaveform:
    """Project at the frozen geocentric merger and preserve endpoint placement."""

    import lal

    if detector not in {"H1", "L1"}:
        raise ContractError(f"unsupported v5 detector: {detector}")
    if plus.shape != cross.shape:
        raise ContractError("v5 plus/cross shape mismatch")
    cached = {
        "H1": lal.LHO_4K_DETECTOR,
        "L1": lal.LLO_4K_DETECTOR,
    }
    instrument = lal.CachedDetectors[cached[detector]]
    epoch = lal.LIGOTimeGPS(float(geocentric_merger_gps))
    gmst = lal.GreenwichMeanSiderealTime(epoch)
    f_plus, f_cross = lal.ComputeDetAMResponse(
        instrument.response, ra_rad, dec_rad, psi_rad, gmst
    )
    delay = float(lal.TimeDelayFromEarthCenter(instrument.location, ra_rad, dec_rad, epoch))
    strain = f_plus * plus + f_cross * cross
    detector_merger = float(geocentric_merger_gps) + delay
    # InjectionEngine takes the array centre; LAL TD arrays end at merger.
    array_center = detector_merger - (len(strain) / float(sample_rate_hz)) / 2.0
    return ProjectedWaveform(
        plus=plus,
        cross=cross,
        detector_strain=np.asarray(strain, dtype=np.float64),
        detector_delay_s=delay,
        geocentric_merger_gps=float(geocentric_merger_gps),
        detector_merger_gps=detector_merger,
        injection_array_center_gps=array_center,
    )


def reconstruct_frozen_trial(
    trial: Mapping[str, Any], protocol: Mapping[str, Any]
) -> tuple[FrozenWaveformParameters, ProjectedWaveform]:
    """Reconstruct one frozen trial without reading strain or outcomes."""

    parameters = parameters_from_trial(trial, protocol)
    plus, cross = generate_polarizations(parameters)
    duration = float(protocol["approved_design"]["waveforms"]["window_duration_s"])
    geocentric_merger = float(trial["gps_start"]) + duration / 2.0
    projected = project_frozen_waveform(
        plus,
        cross,
        detector=str(trial["detector"]),
        ra_rad=float(trial["ra_rad"]),
        dec_rad=float(trial["dec_rad"]),
        psi_rad=float(trial["psi_rad"]),
        geocentric_merger_gps=geocentric_merger,
        sample_rate_hz=parameters.sample_rate_hz,
    )
    return parameters, projected
