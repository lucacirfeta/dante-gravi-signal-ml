"""Frozen PEM follow-up for the corrected O4a pooled-null shortlist."""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_native_rescore import _atomic_json, _atomic_jsonl
from src.dante_light.o4a_corrected_native_rescore_v2 import _load_jsonl
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.prefilter_v5_protocol import sha256_path
from src.pipeline_v2_production.pem_coherence_analysis import (
    AUX_CHANNELS,
    calculate_coherence_and_plot,
    fetch_auxiliary_data,
    require_nds2,
)
from src.pipeline_v2_production.pem_null_calibration import (
    calibrate_event,
    tier_verdict,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_o4a_corrected_native_pem_v1.json")
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_native_pem_v1")
SCHEMA_VERSION = 1


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _file_reference(root: Path, reference: Mapping[str, Any]) -> Path:
    path = (root / str(reference["path"])).resolve()
    if not path.is_file() or sha256_path(path) != str(reference["sha256"]):
        raise ContractError(f"corrected native-PEM reference changed: {path}")
    return path


def validate_native_pem_contract(
    contract: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(contract))
    digest = value.pop("contract_digest", None)
    if digest != canonical_json_sha256(value):
        raise ContractError("corrected native-PEM contract digest mismatch")
    if int(value.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ContractError("corrected native-PEM schema changed")
    if value.get("population") != {
        "selection_source": "native_coincidence_exceeds_primary_threshold_true",
        "primary": {"class": "ROBUST", "role": "primary_diagnostic", "H1": 3, "L1": 6, "total": 9},
        "diagnostic": {"class": "AMBIGUOUS", "role": "separate_diagnostic", "H1": 31, "L1": 25, "total": 56},
        "excluded": {"classes": ["BACKGROUND"], "individual_null_exceeders_used": False},
        "exact_total": 65,
    }:
        raise ContractError("corrected native-PEM population changed")
    if value.get("measurement") != {
        "event_window_s": 32.0,
        "strain_highpass_hz": 20.0,
        "coherence_fftlength_s": 2.0,
        "coherence_overlap_s": 1.0,
        "frequency_band_hz": [20.0, 500.0],
        "background_block_s": 14400.0,
        "background_window_s": 32.0,
        "background_stride_s": 96.0,
        "surrogate_guard_s": 64.0,
        "candidate_exclusion_s": 96.0,
        "candidate_exclusion_population": "all_10942_corrected_native_candidates",
        "minimum_clean_windows": 60,
        "alpha_family_wise": 0.01,
        "bootstrap_resamples": 200,
        "bootstrap_unit": "background_window_indices",
        "seed": 42,
        "time_shift_endpoint": "event_max_over_tested_channels_and_20_500_hz",
        "primary_endpoint": "quiet_zero_lag_q99_confirmed",
        "uncalibrated_is_negative": False,
    }:
        raise ContractError("corrected native-PEM measurement changed")
    channels = value.get("channels")
    if channels != {
        "H1": list(AUX_CHANNELS["H1"]),
        "L1": list(AUX_CHANNELS["L1"]),
        "explicitly_excluded": [
            "L1:PEM-EX_VMON_ETMX_ESDPOWER24_DQ",
            "L1:PEM-EY_MAINSMON_EBAY_1_DQ",
        ],
        "public_subset_is_complete_sensor_network": False,
    }:
        raise ContractError("corrected native-PEM channel policy changed")
    if value.get("scientific_boundary") != {
        "shortlist_is_globally_significant": False,
        "shortlist_description": "pooled-null-threshold exceeders selected for PEM follow-up",
        "pem_is_astrophysical_confirmation": False,
        "pem_no_correlation_excludes_unreleased_sensors": False,
        "primary_and_ambiguous_results_combined": False,
        "background_processed": False,
        "historical_artifacts_immutable": True,
        "future_global_null_required": True,
        "future_global_null_method": "repeat_full_pipeline_on_many_time_slides_and_calibrate_global_maximum_or_exceedance_count",
    }:
        raise ContractError("corrected native-PEM scientific boundary changed")
    if value.get("execution") != {
        "environment": "canonical WSL runtime with nds2",
        "nds_host": "nds.gwosc.org",
        "atomic_per_event_outputs": True,
        "resume_exact_completed_events": True,
        "partial_run_interpretable": False,
        "ephemeral_background_cache_purged": True,
    }:
        raise ContractError("corrected native-PEM execution changed")
    if value.get("output") != {
        "root": "E:/dante_cache/dante_light/o4a_corrected_native_pem_v1",
        "summary_filename": "native_pem_summary.json",
        "targets_filename": "native_pem_targets.jsonl",
        "primary_filename": "native_pem_robust.jsonl",
        "diagnostic_filename": "native_pem_ambiguous.jsonl",
        "historical_artifacts_overwritten": False,
        "large_outputs_committed_to_git": False,
    }:
        raise ContractError("corrected native-PEM output changed")
    for reference in value.get("references", {}).values():
        _file_reference(root, reference)
    coincidence = _read_json(root / value["references"]["native_coincidence"]["path"])
    classification = _read_json(root / value["references"]["native_classification"]["path"])
    if value.get("parents") != {
        "native_coincidence_artifact_digest": coincidence.get("external_artifact_digest"),
        "native_coincidence_contract_digest": coincidence.get("contract_digest"),
        "native_coincidence_primary_sha256": coincidence.get("outputs", {}).get("primary", {}).get("sha256"),
        "native_coincidence_diagnostic_sha256": coincidence.get("outputs", {}).get("diagnostic", {}).get("sha256"),
        "native_classification_artifact_digest": classification.get("external_artifact_digest"),
        "native_classification_row_digest": classification.get("output", {}).get("row_digest"),
        "native_classification_sha256": classification.get("output", {}).get("sha256"),
    }:
        raise ContractError("corrected native-PEM parents changed")
    return {"contract_digest": digest, **value}


def load_native_pem_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_native_pem_contract(_read_json(root / CONTRACT_REL), root=root)


def select_pem_targets(
    primary: Sequence[Mapping[str, Any]],
    diagnostic: Sequence[Mapping[str, Any]],
    *,
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    identities: set[tuple[str, float]] = set()
    for population, rows, expected_class in (
        ("primary", primary, "ROBUST"),
        ("diagnostic", diagnostic, "AMBIGUOUS"),
    ):
        for source in rows:
            if source.get("exceeds_primary_threshold") is not True:
                continue
            detector = str(source.get("detector"))
            gps = float(source.get("gps_start", np.nan))
            identity = (detector, gps)
            if (
                detector not in {"H1", "L1"}
                or not np.isfinite(gps)
                or source.get("measurement_status") != "MEASURED"
                or source.get("seed_native_class") != expected_class
                or source.get("population") != population
                or identity in identities
            ):
                raise ContractError("corrected native-PEM target identity changed")
            identities.add(identity)
            selected.append(
                {
                    "population": population,
                    "detector": detector,
                    "gps_start": gps,
                    "native_class": expected_class,
                    "native_score": float(source["seed_native_score"]),
                    "identity_digest": str(source["seed_identity_digest"]),
                    "image_sha256": str(source["seed_image_sha256"]),
                    "raw_context_sha256": str(source["seed_raw_context_sha256"]),
                    "context_sources": list(source["seed_context_sources"]),
                    "cc_onsource": float(source["cc_onsource"]),
                    "coincidence_primary_threshold_exceeded": True,
                }
            )
    selected.sort(key=lambda row: (float(row["gps_start"]), str(row["detector"])))
    for population in ("primary", "diagnostic"):
        spec = contract["population"][population]
        rows = [row for row in selected if row["population"] == population]
        counts = Counter(row["detector"] for row in rows)
        observed = {"H1": counts["H1"], "L1": counts["L1"], "total": len(rows)}
        expected = {key: int(spec[key]) for key in ("H1", "L1", "total")}
        if observed != expected:
            raise ContractError(f"corrected native-PEM {population} count changed")
    if len(selected) != int(contract["population"]["exact_total"]):
        raise ContractError("corrected native-PEM target total changed")
    return selected


def _external_inputs(
    *,
    root: Path,
    contract: Mapping[str, Any],
    coincidence_external_root: Path,
    classification_external_root: Path,
) -> tuple[list[dict[str, Any]], list[float], Path]:
    coincidence_artifact = _read_json(root / contract["references"]["native_coincidence"]["path"])
    coincidence_dir = coincidence_external_root.resolve() / (
        "native_coincidence_" + coincidence_artifact["external_run"]["run_key"]
    )
    observed = {}
    for name in ("primary", "diagnostic"):
        spec = coincidence_artifact["outputs"][name]
        path = coincidence_dir / spec["filename"]
        rows = _load_jsonl(path)
        if sha256_file(path) != spec["sha256"] or canonical_json_sha256(rows) != spec["row_digest"]:
            raise ContractError(f"corrected native-PEM coincidence {name} changed")
        observed[name] = rows
    targets = select_pem_targets(observed["primary"], observed["diagnostic"], contract=contract)

    classification_artifact = _read_json(root / contract["references"]["native_classification"]["path"])
    classification_dir = classification_external_root.resolve() / (
        "native_classification_" + classification_artifact["external_run"]["run_key"]
    )
    classification_path = classification_dir / classification_artifact["output"]["filename"]
    classification_rows = _load_jsonl(classification_path)
    if (
        sha256_file(classification_path) != contract["parents"]["native_classification_sha256"]
        or canonical_json_sha256(classification_rows) != contract["parents"]["native_classification_row_digest"]
        or len(classification_rows) != 10_942
    ):
        raise ContractError("corrected native-PEM exclusion ledger changed")
    exclusion = [float(row["gps_start"]) for row in classification_rows]
    if not np.isfinite(exclusion).all():
        raise ContractError("corrected native-PEM exclusion GPS is invalid")
    return targets, exclusion, classification_path


def _read_seed_strain(target: Mapping[str, Any], raw_root: Path):
    import h5py
    from gwpy.timeseries import TimeSeries

    gps = float(target["gps_start"])
    pieces: list[np.ndarray] = []
    for source in target["context_sources"]:
        path = (raw_root / str(source["relative_path"])).resolve()
        if raw_root != path and raw_root not in path.parents:
            raise ContractError("corrected native-PEM raw path escaped root")
        if sha256_file(path) != str(source["sha256"]):
            raise ContractError("corrected native-PEM raw source changed")
        block_start, block_end = (float(value) for value in source["block_interval"])
        used_start, used_end = (float(value) for value in source["used_interval"])
        first = int(round((used_start - block_start) * 4096))
        last = int(round((used_end - block_start) * 4096))
        with h5py.File(path, "r") as handle:
            dataset = handle.get("Strain")
            if dataset is None or tuple(dataset.shape) != (int(round((block_end - block_start) * 4096)),):
                raise ContractError("corrected native-PEM HDF5 shape changed")
            pieces.append(np.asarray(dataset[first:last]))
    raw = np.ascontiguousarray(np.concatenate(pieces))
    if raw.shape != (40 * 4096,) or hashlib.sha256(raw.tobytes()).hexdigest() != target["raw_context_sha256"]:
        raise ContractError("corrected native-PEM raw context replay changed")
    central = np.ascontiguousarray(raw[4 * 4096 : 36 * 4096])
    return TimeSeries(central, t0=gps, sample_rate=4096, name=f"{target['detector']}:STRAIN").highpass(20), hashlib.sha256(central.tobytes()).hexdigest()


def _measure_event(
    target: Mapping[str, Any],
    *,
    raw_root: Path,
    run_dir: Path,
    exclusion: Sequence[float],
    exclusion_digest: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    detector = str(target["detector"])
    gps = float(target["gps_start"])
    event_path = run_dir / "events" / f"{target['population']}_{detector}_{int(gps)}.json"
    if event_path.is_file():
        event = _read_json(event_path)
        body = dict(event)
        digest = body.pop("event_digest", None)
        if digest != canonical_json_sha256(body) or body.get("target") != dict(target):
            raise ContractError("corrected native-PEM completed event changed")
        return event

    strain, strain_sha256 = _read_seed_strain(target, raw_root)
    cache_dir = run_dir / "event_aux_cache"
    rows = []
    for channel in contract["channels"][detector]:
        auxiliary = None
        error = None
        for attempt in range(3):
            auxiliary = fetch_auxiliary_data(
                channel, int(gps), int(gps) + 32, cache_dir, contract["execution"]["nds_host"]
            )
            if auxiliary is not None:
                break
            error = f"fetch failed after attempt {attempt + 1}"
            time.sleep(2**attempt)
        if auxiliary is None:
            rows.append({"aux_channel": channel, "data_available": False, "max_coherence": None, "peak_freq": None, "error": error})
            continue
        result = calculate_coherence_and_plot(
            strain,
            auxiliary,
            channel,
            detector,
            int(gps),
            run_dir,
            fftlength=float(contract["measurement"]["coherence_fftlength_s"]),
            freq_bounds=tuple(contract["measurement"]["frequency_band_hz"]),
            threshold=1.0,
            save_plot=False,
        )
        rows.append(
            {
                "aux_channel": channel,
                "data_available": bool(np.isfinite(result["max_coherence"])),
                "max_coherence": float(result["max_coherence"]) if np.isfinite(result["max_coherence"]) else None,
                "peak_freq": float(result["peak_freq"]) if np.isfinite(result["peak_freq"]) else None,
                "error": None,
            }
        )
    tested = [row["aux_channel"] for row in rows if row["data_available"]]
    calibration_path = run_dir / f"null_calibration_{detector}_{int(gps)}.json"
    calibration = None
    if tested:
        if calibration_path.is_file():
            calibration = _read_json(calibration_path)
            if (
                calibration.get("detector") != detector
                or float(calibration.get("event_gps")) != gps
                or calibration.get("candidate_exclusion_digest") != exclusion_digest
                or set(calibration.get("channels", [])) - set(tested)
            ):
                raise ContractError("corrected native-PEM saved calibration changed")
        else:
            calibration = calibrate_event(
                detector,
                gps,
                tested,
                run="O4a",
                block_s=float(contract["measurement"]["background_block_s"]),
                alpha=float(contract["measurement"]["alpha_family_wise"]),
                nds_host=str(contract["execution"]["nds_host"]),
                n_boot=int(contract["measurement"]["bootstrap_resamples"]),
                seed=int(contract["measurement"]["seed"]),
                purge_cache=bool(contract["execution"]["ephemeral_background_cache_purged"]),
                pem_dir=run_dir,
                candidate_gps=np.asarray(exclusion, dtype=np.float64),
                candidate_exclusion_digest=exclusion_digest,
            )
    if calibration is None:
        cmax = top_channel = threshold_shift = threshold_zero = None
        tier = "UNCALIBRATED"
    else:
        calibrated = [row for row in rows if row["aux_channel"] in calibration["channels"] and row["data_available"]]
        top = max(calibrated, key=lambda row: float(row["max_coherence"]))
        cmax = float(top["max_coherence"])
        top_channel = str(top["aux_channel"])
        threshold_shift = float(calibration["threshold_fw"])
        threshold_zero = float(calibration["zero_lag_control"]["q99"])
        tier = tier_verdict(cmax, threshold_shift, threshold_zero)
    body = {
        "schema_version": SCHEMA_VERSION,
        "target": dict(target),
        "strain_window_sha256": strain_sha256,
        "channels": rows,
        "calibration_filename": calibration_path.name if calibration is not None else None,
        "m_channels": len(calibration["channels"]) if calibration is not None else 0,
        "cmax_observed": cmax,
        "top_channel": top_channel,
        "threshold_time_shift_q99": threshold_shift,
        "threshold_zero_lag_q99": threshold_zero,
        "verdict_time_shift": (
            "COUPLED" if cmax is not None and cmax > threshold_shift else "NO_CORRELATION"
        ) if calibration is not None else "UNCALIBRATED",
        "verdict_tier": tier,
        "scientific_interpretation": "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION",
    }
    event = {**body, "event_digest": canonical_json_sha256(body)}
    event_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(event_path, event)
    return event


def _run_key(contract: Mapping[str, Any], runtime: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            "stage": "native_pem_v1",
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
            "parents": contract["parents"],
        }
    )


def run_native_pem(
    *,
    root: Path = ROOT,
    raw_root: Path,
    coincidence_external_root: Path,
    classification_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    raw_root = raw_root.resolve()
    contract = load_native_pem_contract(root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device="cuda")
    if not require_nds2():
        raise ContractError("corrected native-PEM requires the NDS2 client")
    targets, exclusion, classification_path = _external_inputs(
        root=root,
        contract=contract,
        coincidence_external_root=coincidence_external_root,
        classification_external_root=classification_external_root,
    )
    run_key = _run_key(contract, runtime)
    run_dir = external_root.resolve() / f"native_pem_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / contract["output"]["summary_filename"]
    if summary_path.is_file():
        return verify_native_pem(
            root=root,
            coincidence_external_root=coincidence_external_root,
            classification_external_root=classification_external_root,
            external_root=external_root,
        )
    target_path = run_dir / contract["output"]["targets_filename"]
    if target_path.is_file():
        if canonical_json_sha256(_load_jsonl(target_path)) != canonical_json_sha256(targets):
            raise ContractError("corrected native-PEM frozen targets changed")
    else:
        _atomic_jsonl(target_path, targets)
    exclusion_digest = canonical_json_sha256(exclusion)
    events = [
        _measure_event(
            target,
            raw_root=raw_root,
            run_dir=run_dir,
            exclusion=exclusion,
            exclusion_digest=exclusion_digest,
            contract=contract,
        )
        for target in targets
    ]
    primary = [row for row in events if row["target"]["population"] == "primary"]
    diagnostic = [row for row in events if row["target"]["population"] == "diagnostic"]
    primary_path = run_dir / contract["output"]["primary_filename"]
    diagnostic_path = run_dir / contract["output"]["diagnostic_filename"]
    _atomic_jsonl(primary_path, primary)
    _atomic_jsonl(diagnostic_path, diagnostic)

    def population_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        verdicts = Counter(str(row["verdict_tier"]) for row in rows)
        return {
            "total": len(rows),
            "calibrated": len(rows) - verdicts["UNCALIBRATED"],
            "uncalibrated": verdicts["UNCALIBRATED"],
            "verdict_tier": dict(sorted(verdicts.items())),
        }

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_NATIVE_PEM_V1",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "population": contract["population"],
        "measurement": contract["measurement"],
        "scientific_boundary": contract["scientific_boundary"],
        "event_summary": {
            "primary": population_summary(primary),
            "diagnostic": population_summary(diagnostic),
        },
        "sources": {
            "classification_path": str(classification_path),
            "classification_sha256": sha256_file(classification_path),
            "candidate_exclusion_total": len(exclusion),
            "candidate_exclusion_digest": exclusion_digest,
        },
        "outputs": {
            "targets": {"filename": target_path.name, "row_total": len(targets), "sha256": sha256_file(target_path), "row_digest": canonical_json_sha256(targets)},
            "primary": {"filename": primary_path.name, "row_total": len(primary), "sha256": sha256_file(primary_path), "row_digest": canonical_json_sha256(primary)},
            "diagnostic": {"filename": diagnostic_path.name, "row_total": len(diagnostic), "sha256": sha256_file(diagnostic_path), "row_digest": canonical_json_sha256(diagnostic)},
        },
        "gates": {
            "all_65_targets_accounted": len(events) == 65,
            "background_targets": 0,
            "individual_null_exceeders_used": False,
            "banned_channels_measured": 0,
            "primary_and_diagnostic_combined": False,
            "missing_calibration_counted_as_negative": False,
        },
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(summary_path, summary)
    return summary, run_dir


def verify_native_pem(
    *,
    root: Path = ROOT,
    coincidence_external_root: Path,
    classification_external_root: Path,
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_native_pem_contract(root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device="cuda")
    targets, exclusion, classification_path = _external_inputs(
        root=root,
        contract=contract,
        coincidence_external_root=coincidence_external_root,
        classification_external_root=classification_external_root,
    )
    run_key = _run_key(contract, runtime)
    run_dir = external_root.resolve() / f"native_pem_{run_key}"
    summary = _read_json(run_dir / contract["output"]["summary_filename"])
    body = dict(summary)
    digest = body.pop("artifact_digest", None)
    if digest != canonical_json_sha256(body) or body.get("status") != "PASS_COMPLETE_NATIVE_PEM_V1":
        raise ContractError("corrected native-PEM summary changed")
    observed = {}
    for name, expected_rows in (("targets", targets), ("primary", None), ("diagnostic", None)):
        spec = summary["outputs"][name]
        path = run_dir / spec["filename"]
        rows = _load_jsonl(path)
        if (
            sha256_file(path) != spec["sha256"]
            or canonical_json_sha256(rows) != spec["row_digest"]
            or len(rows) != int(spec["row_total"])
            or (expected_rows is not None and rows != expected_rows)
        ):
            raise ContractError(f"corrected native-PEM {name} output changed")
        observed[name] = rows
    if len(observed["primary"]) != 9 or len(observed["diagnostic"]) != 56:
        raise ContractError("corrected native-PEM output population changed")
    banned = set(contract["channels"]["explicitly_excluded"])
    events = [*observed["primary"], *observed["diagnostic"]]
    if any(
        row["target"]["population"] not in {"primary", "diagnostic"}
        or row["scientific_interpretation"] != "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION"
        or any(channel["aux_channel"] in banned for channel in row["channels"])
        for row in events
    ):
        raise ContractError("corrected native-PEM scientific boundary changed")
    if (
        summary["sources"]["classification_sha256"] != sha256_file(classification_path)
        or summary["sources"]["candidate_exclusion_total"] != len(exclusion)
        or summary["sources"]["candidate_exclusion_digest"] != canonical_json_sha256(exclusion)
        or summary["gates"] != {
            "all_65_targets_accounted": True,
            "background_targets": 0,
            "individual_null_exceeders_used": False,
            "banned_channels_measured": 0,
            "primary_and_diagnostic_combined": False,
            "missing_calibration_counted_as_negative": False,
        }
    ):
        raise ContractError("corrected native-PEM verification changed")
    return summary, run_dir


__all__ = [
    "DEFAULT_EXTERNAL_ROOT",
    "load_native_pem_contract",
    "run_native_pem",
    "select_pem_targets",
    "validate_native_pem_contract",
    "verify_native_pem",
]
