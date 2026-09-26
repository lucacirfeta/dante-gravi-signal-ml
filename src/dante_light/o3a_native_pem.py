"""O3a-only diagnostic PEM preflight and frozen input selection.

This module does not load the historical O4a PEM adapter or its provenance
reconciliation. The O4a contract is a method reference, never a data source.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Any

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_calibration_cohort import _atomic_json, _atomic_jsonl
from src.dante_light.o3a_native_contract import ROOT
from src.dante_light.o3a_primary_scan import _download_frame
from src.dante_light.o3a_raw_acquisition import _inventory_frames, load_source_inventory
from src.dante_light.o3a_raw_download import file_sha256

CONTRACT_REL = Path("config/dante_o3a_native_pem_v1.json")
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")
EXPECTED_STATUS = "FROZEN_O3A_NATIVE_PEM_V1"
COMPACT_REL = Path("artifacts/dante_light/o3a_native_v1/native_pem.json")
SOURCE_PATHS = (
    "src/dante_light/o3a_native_pem.py",
    "scripts/run_dante_o3a_native_pem.py",
    "tests/test_dante_o3a_native_pem.py",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"O3a PEM expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not all(isinstance(row, dict) for row in rows):
        raise ContractError(f"O3a PEM expected JSONL objects: {path}")
    return rows


def _sealed(value: Mapping[str, Any], key: str) -> None:
    body = dict(value)
    if body.pop(key, None) != canonical_json_sha256(body):
        raise ContractError(f"O3a PEM {key} seal changed")


def _verified_file(root: Path, reference: Mapping[str, Any]) -> Path:
    path = (root / str(reference["path"])).resolve()
    if (
        not path.is_relative_to(root.resolve())
        or not path.is_file()
        or file_sha256(path) != reference["sha256"]
    ):
        raise ContractError(f"O3a PEM parent file changed: {path}")
    return path


def load_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    value = _read_json(root / CONTRACT_REL)
    _sealed(value, "contract_digest")
    if value.get("schema_version") != 1 or value.get("status") != EXPECTED_STATUS or value.get("run") != "O3A":
        raise ContractError("O3a PEM contract identity changed")
    if set(value.get("implementation_sources", {})) != set(SOURCE_PATHS):
        raise ContractError("O3a PEM source freeze is incomplete")
    for relative in SOURCE_PATHS:
        if file_sha256(root / relative) != value["implementation_sources"][relative]:
            raise ContractError(f"O3a PEM frozen source changed: {relative}")
    method = _read_json(_verified_file(root, value["method_reference"]))
    _sealed(method, "contract_digest")
    expected_measurement = {
        key: item for key, item in method["measurement"].items()
        if key != "candidate_exclusion_population"
    }
    if value.get("measurement") != expected_measurement:
        raise ContractError("O3a PEM frozen measurement method changed")
    channels = value["channels"]
    if set(channels) != {"H1", "L1", "channel_count_per_detector", "explicitly_excluded", "public_subset_is_complete_sensor_network"}:
        raise ContractError("O3a PEM channel policy fields changed")
    if (
        any(
            len(channels[detector]) != int(channels["channel_count_per_detector"])
            or len(set(channels[detector])) != len(channels[detector])
            for detector in ("H1", "L1")
        )
        or any(not set(channels[detector]).issubset(method["channels"][detector]) for detector in ("H1", "L1"))
        or set(channels["H1"] + channels["L1"]) & set(method["channels"]["explicitly_excluded"])
        or channels["explicitly_excluded"] != method["channels"]["explicitly_excluded"]
        or channels["public_subset_is_complete_sensor_network"] is not False
    ):
        raise ContractError("O3a PEM public five-channel subset changed")
    boundary = value["scientific_boundary"]
    if boundary != {
        "diagnostic_only": True,
        "o4a_comparison_performed": False,
        "global_significance_claim": False,
        "astrophysical_confirmation_claim": False,
        "uncalibrated_is_negative": False,
        "primary_and_diagnostic_combined": False,
        "a2_promoted": False,
        "unreleased_sensors_cleared": False,
    }:
        raise ContractError("O3a PEM scientific boundary changed")
    for reference in value["parents"].values():
        _verified_file(root, reference)
    coincidence = _read_json(root / value["parents"]["coincidence"]["path"])
    classification = _read_json(root / value["parents"]["classification"]["path"])
    _sealed(coincidence, "artifact_digest")
    _sealed(classification, "artifact_digest")
    if (
        coincidence["artifact_digest"] != value["parents"]["coincidence"]["artifact_digest"]
        or classification["artifact_digest"] != value["parents"]["classification"]["artifact_digest"]
        or coincidence["status"] != "PASS_VERIFIED_O3A_NATIVE_COINCIDENCE"
        or classification["status"] != "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION"
        or classification["row_total"] != value["population"]["candidate_exclusion_total"]
    ):
        raise ContractError("O3a PEM verified parent identity changed")
    coincidence_contract = _read_json(root / value["parents"]["coincidence_contract"]["path"])
    _sealed(coincidence_contract, "contract_digest")
    if (
        coincidence_contract["contract_digest"] != coincidence["contract_digest"]
        or coincidence_contract["measurement"]["segment_duration_s"] != value["measurement"]["event_window_s"]
        or coincidence_contract["measurement"]["sample_rate_hz"]
        != load_source_inventory(root=root)["source_query"]["sample_rate_hz"]
    ):
        raise ContractError("O3a PEM event geometry changed")
    return value


def _external_rows(
    *, root: Path, contract: Mapping[str, Any], external_root: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    coincidence = _read_json(root / contract["parents"]["coincidence"]["path"])
    classification = _read_json(root / contract["parents"]["classification"]["path"])
    coincidence_dir = external_root / f"native_coincidence_{coincidence['run_key']}"
    classification_dir = external_root / f"native_classification_{classification['run_key']}"
    observed: dict[str, list[dict[str, Any]]] = {}
    for bucket in ("primary", "diagnostic"):
        spec = coincidence["outputs"][bucket]
        path = coincidence_dir / spec["filename"]
        rows = _jsonl(path)
        if (
            file_sha256(path) != spec["sha256"]
            or canonical_json_sha256(rows) != spec["row_digest"]
            or len(rows) != spec["row_total"]
        ):
            raise ContractError(f"O3a PEM coincidence {bucket} ledger changed")
        observed[bucket] = rows
    path = classification_dir / "native_classified_candidates.jsonl"
    classified = _jsonl(path)
    if (
        file_sha256(path) != classification["output_sha256"]
        or canonical_json_sha256(classified) != classification["output_row_digest"]
        or len(classified) != contract["population"]["candidate_exclusion_total"]
    ):
        raise ContractError("O3a PEM full candidate-exclusion ledger changed")
    return observed, classified


def _check_sources(
    sources: Sequence[Mapping[str, Any]], *, detector: str, gps: int,
    pad: int, duration: int, inventory_frames: Mapping[str, Mapping[str, Any]],
) -> None:
    cursor = gps - pad
    end = gps + duration + pad
    if not sources:
        raise ContractError("O3a PEM raw context has no source")
    for source in sources:
        used_start, used_end = (int(x) for x in source["used_interval_gps"])
        frame_start, frame_end = int(source["gps_start"]), int(source["gps_end"])
        digest = str(source["sha256"])
        published = inventory_frames.get(str(source["filename"]))
        if (
            source["detector"] != detector
            or published is None
            or any(source[key] != published[key] for key in ("filename", "gps_start", "gps_end", "url"))
            or used_start != cursor
            or not (frame_start <= used_start < used_end <= frame_end)
            or len(digest) != 64
            or not all(ch in "0123456789abcdef" for ch in digest)
            or int(source["size_bytes"]) <= 0
            or not str(source["url"]).startswith("https://")
        ):
            raise ContractError("O3a PEM raw source coverage or identity changed")
        cursor = used_end
    if cursor != end:
        raise ContractError("O3a PEM raw context is incomplete")


def preflight_inputs(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[float]]:
    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root)
    coincidence_rows, classified = _external_rows(root=root, contract=contract, external_root=external_root)
    coincidence_contract = _read_json(root / contract["parents"]["coincidence_contract"]["path"])
    measurement = coincidence_contract["measurement"]
    pad = int(measurement["whitening_pad_s"])
    duration = int(measurement["segment_duration_s"])
    inventory = load_source_inventory(root=root)
    inventory_frames = {
        detector: {frame["filename"]: frame for frame in _inventory_frames(inventory, detector)}
        for detector in ("H1", "L1")
    }
    by_key = {(str(row["detector"]), int(row["gps_start"])): row for row in classified}
    if len(by_key) != len(classified):
        raise ContractError("O3a PEM classification identities are not unique")
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for bucket, label in (("primary", "ROBUST"), ("diagnostic", "AMBIGUOUS")):
        for row in coincidence_rows[bucket]:
            if row["exceeds_primary_threshold"] is not True:
                continue
            detector, gps = str(row["detector"]), int(row["gps_start"])
            key = detector, gps
            classified_row = by_key.get(key)
            if (
                key in seen or detector not in ("H1", "L1")
                or classified_row is None
                or row["population"] != bucket
                or row["measurement_status"] != "MEASURED"
                or row["seed_native_class"] != label
                or classified_row["native_class"] != label
                or classified_row["identity_digest"] != row["seed_identity_digest"]
                or classified_row["raw_context_sha256"] != row["seed_raw_context_sha256"]
                or classified_row["image_sha256"] != row["seed_image_sha256"]
                or not np.isfinite(float(row["seed_native_score"]))
                or float(classified_row["native_score"]) != float(row["seed_native_score"])
            ):
                raise ContractError("O3a PEM selected target identity changed")
            _check_sources(
                classified_row["context_sources"], detector=detector, gps=gps,
                pad=pad, duration=duration, inventory_frames=inventory_frames[detector],
            )
            seen.add(key)
            targets.append({
                "population": bucket,
                "detector": detector,
                "gps_start": gps,
                "native_class": label,
                "native_score": float(row["seed_native_score"]),
                "identity_digest": row["seed_identity_digest"],
                "image_sha256": row["seed_image_sha256"],
                "raw_context_sha256": row["seed_raw_context_sha256"],
                "context_sources": classified_row["context_sources"],
                "cc_onsource": float(row["cc_onsource"]),
            })
    targets.sort(key=lambda row: (row["gps_start"], row["detector"]))
    counts = {bucket: Counter(row["detector"] for row in targets if row["population"] == bucket) for bucket in ("primary", "diagnostic")}
    for bucket in counts:
        expected = contract["population"][bucket]
        if any(counts[bucket][detector] != expected[detector] for detector in ("H1", "L1")) or sum(counts[bucket].values()) != expected["total"]:
            raise ContractError(f"O3a PEM selected {bucket} count changed")
    if len(targets) != contract["population"]["exact_total"]:
        raise ContractError("O3a PEM total selected target count changed")
    exclusion = [float(row["gps_start"]) for row in classified]
    if not np.isfinite(exclusion).all():
        raise ContractError("O3a PEM candidate-exclusion GPS is invalid")
    body = {
        "status": "PASS_O3A_NATIVE_PEM_INPUT_PREFLIGHT",
        "contract_digest": contract["contract_digest"],
        "target_total": len(targets),
        "target_digest": canonical_json_sha256(targets),
        "candidate_exclusion_total": len(exclusion),
        "candidate_exclusion_digest": canonical_json_sha256(exclusion),
        "strain_opened": False,
        "pem_outcomes_opened": False,
    }
    return {**body, "preflight_digest": canonical_json_sha256(body)}, targets, exclusion


def _run_key(contract: Mapping[str, Any], preflight: Mapping[str, Any]) -> str:
    return canonical_json_sha256({
        "stage": "o3a_native_pem_v1",
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
    })


def _event_strain(
    target: Mapping[str, Any], *, run_dir: Path, contract: Mapping[str, Any],
) -> tuple[Any, str]:
    """Fetch only inventory-bound O3a frames; replay the frozen 40 s bytes."""
    import h5py
    from gwpy.timeseries import TimeSeries

    gps = int(target["gps_start"])
    detector = str(target["detector"])
    coincidence_contract = _read_json(ROOT / contract["parents"]["coincidence_contract"]["path"])
    sample_rate = int(coincidence_contract["measurement"]["sample_rate_hz"])
    pad = int(coincidence_contract["measurement"]["whitening_pad_s"])
    duration = int(coincidence_contract["measurement"]["segment_duration_s"])
    cache = run_dir / "transient_raw" / detector
    pieces: list[np.ndarray] = []
    for source in target["context_sources"]:
        filename = str(source["filename"])
        path = (cache / filename).resolve()
        if path.parent != cache.resolve():
            raise ContractError("O3a PEM raw source path escaped cache")
        frame = {
            **source,
            "duration_s": int(source["gps_end"]) - int(source["gps_start"]),
        }
        _download_frame(
            frame=frame,
            target=path,
            retries=int(contract["execution"]["download_retries"]),
            expected_sha256=str(source["sha256"]),
        )
        used_start, used_end = (int(x) for x in source["used_interval_gps"])
        first = (used_start - int(source["gps_start"])) * sample_rate
        last = (used_end - int(source["gps_start"])) * sample_rate
        with h5py.File(path, "r") as handle:
            dataset = handle.get("strain/Strain")
            if dataset is None or tuple(dataset.shape) != (
                frame["duration_s"] * sample_rate,
            ):
                raise ContractError("O3a PEM frame strain shape changed")
            pieces.append(np.asarray(dataset[first:last], dtype=np.float64))
    raw = np.ascontiguousarray(np.concatenate(pieces), dtype=np.float64)
    if (
        raw.shape != ((duration + 2 * pad) * sample_rate,)
        or not np.isfinite(raw).all()
        or hashlib.sha256(raw.tobytes()).hexdigest() != target["raw_context_sha256"]
    ):
        raise ContractError("O3a PEM frozen raw context did not replay")
    central = np.ascontiguousarray(raw[pad * sample_rate : (pad + duration) * sample_rate])
    central_sha = hashlib.sha256(central.tobytes()).hexdigest()
    series = TimeSeries(central, t0=gps, sample_rate=sample_rate, name=f"{detector}:STRAIN")
    return series.highpass(float(contract["measurement"]["strain_highpass_hz"])), central_sha


def _verify_event(
    event: Mapping[str, Any], *, target: Mapping[str, Any], run_dir: Path,
    exclusion_digest: str, contract: Mapping[str, Any],
) -> None:
    _sealed(event, "event_digest")
    if (
        event["target"] != dict(target)
        or event["candidate_exclusion_digest"] != exclusion_digest
        or event["scientific_interpretation"] != "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION"
    ):
        raise ContractError("O3a PEM completed event identity changed")
    detector = str(target["detector"])
    observed_channels = [row["aux_channel"] for row in event["channels"]]
    if observed_channels != contract["channels"][detector]:
        raise ContractError("O3a PEM completed event channel set changed")
    calibration_spec = event["calibration"]
    if calibration_spec is None:
        if (
            event["verdict_tier"] != "UNCALIBRATED"
            or event["verdict_time_shift"] != "UNCALIBRATED"
            or event["cmax_observed"] is not None
            or event["top_channel"] is not None
            or event["threshold_time_shift_q99"] is not None
            or event["threshold_zero_lag_q99"] is not None
        ):
            raise ContractError("O3a PEM missing calibration was counted as negative")
        return
    path = run_dir / calibration_spec["filename"]
    if path.parent != run_dir or file_sha256(path) != calibration_spec["sha256"]:
        raise ContractError("O3a PEM calibration file changed")
    calibration = _read_json(path)
    if (
        calibration["detector"] != detector
        or calibration["run"] != "O3a"
        or float(calibration["event_gps"]) != float(target["gps_start"])
        or calibration["candidate_exclusion_digest"] != exclusion_digest
        or calibration["candidate_exclusion_population"]
        != contract["population"]["candidate_exclusion_total"]
        or calibration["channels"] != calibration_spec["channels"]
        or set(calibration["channels"]) - set(observed_channels)
        or calibration["alpha_family_wise"] != contract["measurement"]["alpha_family_wise"]
        or calibration["n_windows"] < contract["measurement"]["minimum_clean_windows"]
    ):
        raise ContractError("O3a PEM calibration identity changed")
    from src.pipeline_v2_production.pem_null_calibration import tier_verdict

    cmax = float(event["cmax_observed"])
    measured = [
        row for row in event["channels"]
        if row["aux_channel"] in calibration["channels"] and row["data_available"]
    ]
    if not measured or cmax != max(float(row["max_coherence"]) for row in measured):
        raise ContractError("O3a PEM calibrated event maximum changed")
    if event["top_channel"] not in {
        row["aux_channel"] for row in measured
        if float(row["max_coherence"]) == cmax
    }:
        raise ContractError("O3a PEM top channel changed")
    threshold_shift = float(calibration["threshold_fw"])
    threshold_zero = float(calibration["zero_lag_control"]["q99"])
    if (
        event["threshold_time_shift_q99"] != threshold_shift
        or event["threshold_zero_lag_q99"] != threshold_zero
        or event["verdict_tier"] != tier_verdict(cmax, threshold_shift, threshold_zero)
        or event["verdict_time_shift"] != (
            "COUPLED" if cmax > threshold_shift else "NO_CORRELATION"
        )
    ):
        raise ContractError("O3a PEM completed event verdict changed")


def _measure_event(
    target: Mapping[str, Any], *, run_dir: Path, exclusion: Sequence[float],
    exclusion_digest: str, contract: Mapping[str, Any],
) -> dict[str, Any]:
    from src.pipeline_v2_production.pem_coherence_analysis import (
        calculate_coherence_and_plot,
        fetch_auxiliary_data,
    )
    from src.pipeline_v2_production.pem_null_calibration import calibrate_event, tier_verdict

    detector, gps = str(target["detector"]), int(target["gps_start"])
    event_path = run_dir / "events" / f"{target['population']}_{detector}_{gps}.json"
    if event_path.is_file():
        event = _read_json(event_path)
        _verify_event(
            event, target=target, run_dir=run_dir,
            exclusion_digest=exclusion_digest, contract=contract,
        )
        return event
    strain, strain_sha = _event_strain(target, run_dir=run_dir, contract=contract)
    rows: list[dict[str, Any]] = []
    cache = run_dir / "event_aux_cache"
    measurement = contract["measurement"]
    for channel in contract["channels"][detector]:
        auxiliary = None
        for attempt in range(int(contract["execution"]["aux_fetch_retries"])):
            auxiliary = fetch_auxiliary_data(
                channel, gps, gps + int(measurement["event_window_s"]),
                cache, str(contract["execution"]["nds_host"]),
            )
            if auxiliary is not None:
                break
            time.sleep(float(contract["execution"]["aux_fetch_backoff_base_s"]) ** attempt)
        if auxiliary is None:
            rows.append({"aux_channel": channel, "data_available": False, "max_coherence": None, "peak_freq": None})
            continue
        result = calculate_coherence_and_plot(
            strain, auxiliary, channel, detector, gps, run_dir,
            fftlength=float(measurement["coherence_fftlength_s"]),
            freq_bounds=tuple(measurement["frequency_band_hz"]),
            threshold=1.0, save_plot=False,
        )
        available = bool(np.isfinite(result["max_coherence"]))
        rows.append({
            "aux_channel": channel,
            "data_available": available,
            "max_coherence": float(result["max_coherence"]) if available else None,
            "peak_freq": float(result["peak_freq"]) if available else None,
        })
    tested = [row["aux_channel"] for row in rows if row["data_available"]]
    calibration_path = run_dir / f"null_calibration_{detector}_{gps}.json"
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
                raise ContractError("O3a PEM saved calibration changed")
        else:
            calibration = calibrate_event(
                detector, gps, tested, run="O3a",
                block_s=float(measurement["background_block_s"]),
                alpha=float(measurement["alpha_family_wise"]),
                nds_host=str(contract["execution"]["nds_host"]),
                n_boot=int(measurement["bootstrap_resamples"]),
                seed=int(measurement["seed"]),
                purge_cache=bool(contract["execution"]["ephemeral_background_cache_purged"]),
                pem_dir=run_dir,
                candidate_gps=np.asarray(exclusion, dtype=np.float64),
                candidate_exclusion_digest=exclusion_digest,
            )
    if calibration is None:
        cmax = threshold_shift = threshold_zero = None
        top_channel = None
        tier = "UNCALIBRATED"
        calibration_spec = None
    else:
        calibrated = [row for row in rows if row["aux_channel"] in calibration["channels"] and row["data_available"]]
        if not calibrated:
            raise ContractError("O3a PEM calibration has no measured channel")
        top = max(calibrated, key=lambda row: float(row["max_coherence"]))
        cmax = float(top["max_coherence"])
        top_channel = str(top["aux_channel"])
        threshold_shift = float(calibration["threshold_fw"])
        threshold_zero = float(calibration["zero_lag_control"]["q99"])
        tier = tier_verdict(cmax, threshold_shift, threshold_zero)
        calibration_spec = {
            "filename": calibration_path.name,
            "sha256": file_sha256(calibration_path),
            "channels": calibration["channels"],
        }
    body = {
        "schema_version": 1,
        "target": dict(target),
        "candidate_exclusion_digest": exclusion_digest,
        "strain_window_sha256": strain_sha,
        "channels": rows,
        "calibration": calibration_spec,
        "cmax_observed": cmax,
        "top_channel": top_channel,
        "threshold_time_shift_q99": threshold_shift,
        "threshold_zero_lag_q99": threshold_zero,
        "verdict_time_shift": (
            "COUPLED" if cmax > threshold_shift else "NO_CORRELATION"
        ) if calibration is not None else "UNCALIBRATED",
        "verdict_tier": tier,
        "scientific_interpretation": "PEM_DIAGNOSTIC_ONLY_NOT_ASTROPHYSICAL_CONFIRMATION",
    }
    event = {**body, "event_digest": canonical_json_sha256(body)}
    event_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(event_path, event)
    return event


def _outputs_spec(path: Path, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "filename": path.name,
        "row_total": len(rows),
        "sha256": file_sha256(path),
        "row_digest": canonical_json_sha256(rows),
    }


def run_native_pem(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    from src.pipeline_v2_production.pem_coherence_analysis import require_nds2

    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root)
    if not require_nds2():
        raise ContractError("O3a PEM NDS2 client is unavailable")
    preflight, targets, exclusion = preflight_inputs(root=root, external_root=external_root)
    unique_sources = {
        (target["detector"], source["filename"]): source
        for target in targets for source in target["context_sources"]
    }
    coincidence_contract = _read_json(root / contract["parents"]["coincidence_contract"]["path"])
    required_bytes = sum(int(source["size_bytes"]) for source in unique_sources.values())
    reserve = int(coincidence_contract["execution"]["free_space_reserve_bytes"])
    if shutil.disk_usage(external_root).free < required_bytes + reserve:
        raise ContractError("O3a PEM external disk lacks raw-cache reserve")
    run_key = _run_key(contract, preflight)
    run_dir = external_root / f"{contract['output']['prefix']}{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "native_pem_summary.json"
    if summary_path.is_file():
        return verify_native_pem(root=root, external_root=external_root)
    target_path = run_dir / "native_pem_targets.jsonl"
    if target_path.is_file():
        if _jsonl(target_path) != targets:
            raise ContractError("O3a PEM resumed target list changed")
    else:
        _atomic_jsonl(target_path, targets)
    exclusion_digest = preflight["candidate_exclusion_digest"]
    events = [
        _measure_event(
            target, run_dir=run_dir, exclusion=exclusion,
            exclusion_digest=exclusion_digest, contract=contract,
        )
        for target in targets
    ]
    outputs: dict[str, dict[str, Any]] = {"targets": _outputs_spec(target_path, targets)}
    event_summary: dict[str, dict[str, Any]] = {}
    for bucket in ("primary", "diagnostic"):
        rows = [row for row in events if row["target"]["population"] == bucket]
        path = run_dir / f"native_pem_{bucket}.jsonl"
        _atomic_jsonl(path, rows)
        outputs[bucket] = _outputs_spec(path, rows)
        verdicts = Counter(row["verdict_tier"] for row in rows)
        event_summary[bucket] = {
            "total": len(rows),
            "calibrated": len(rows) - verdicts["UNCALIBRATED"],
            "uncalibrated": verdicts["UNCALIBRATED"],
            "verdict_tier": dict(sorted(verdicts.items())),
        }
    for (detector, filename), source in unique_sources.items():
        path = (run_dir / "transient_raw" / detector / filename).resolve()
        if (
            path.parent != (run_dir / "transient_raw" / detector).resolve()
            or file_sha256(path) != source["sha256"]
        ):
            raise ContractError("O3a PEM transient raw frame changed before purge")
        path.unlink()
    body = {
        "schema_version": 1,
        "status": "PASS_COMPLETE_O3A_NATIVE_PEM_V1",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "preflight_digest": preflight["preflight_digest"],
        "target_digest": preflight["target_digest"],
        "candidate_exclusion_digest": exclusion_digest,
        "event_summary": event_summary,
        "outputs": outputs,
        "transient_raw_purged": True,
        "scientific_boundary": contract["scientific_boundary"],
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(summary_path, summary)
    return summary, run_dir


def verify_native_pem(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], Path]:
    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root)
    preflight, targets, exclusion = preflight_inputs(root=root, external_root=external_root)
    run_dir = external_root / f"{contract['output']['prefix']}{_run_key(contract, preflight)}"
    summary = _read_json(run_dir / "native_pem_summary.json")
    _sealed(summary, "artifact_digest")
    if (
        summary["status"] != "PASS_COMPLETE_O3A_NATIVE_PEM_V1"
        or summary["contract_digest"] != contract["contract_digest"]
        or summary["preflight_digest"] != preflight["preflight_digest"]
        or summary["target_digest"] != preflight["target_digest"]
        or summary["candidate_exclusion_digest"] != preflight["candidate_exclusion_digest"]
        or summary["transient_raw_purged"] is not True
        or summary["scientific_boundary"] != contract["scientific_boundary"]
    ):
        raise ContractError("O3a PEM completed summary identity changed")
    observed: dict[str, list[dict[str, Any]]] = {}
    for bucket in ("targets", "primary", "diagnostic"):
        spec = summary["outputs"][bucket]
        path = run_dir / spec["filename"]
        rows = _jsonl(path)
        if (
            file_sha256(path) != spec["sha256"]
            or len(rows) != spec["row_total"]
            or canonical_json_sha256(rows) != spec["row_digest"]
        ):
            raise ContractError(f"O3a PEM {bucket} output changed")
        observed[bucket] = rows
    if observed["targets"] != targets:
        raise ContractError("O3a PEM target list changed")
    if any(path.is_file() for path in (run_dir / "transient_raw").rglob("*")):
        raise ContractError("O3a PEM transient raw cache is not empty")
    events = [*observed["primary"], *observed["diagnostic"]]
    if len(events) != len(targets):
        raise ContractError("O3a PEM event accounting incomplete")
    by_identity = {(row["population"], row["detector"], row["gps_start"]): row for row in targets}
    if len(by_identity) != len(targets):
        raise ContractError("O3a PEM target identities are not unique")
    observed_keys: set[tuple[str, str, int]] = set()
    for bucket in ("primary", "diagnostic"):
        for event in observed[bucket]:
            target = event["target"]
            key = target["population"], target["detector"], target["gps_start"]
            if target["population"] != bucket or key in observed_keys or key not in by_identity or by_identity[key] != target:
                raise ContractError("O3a PEM event target changed or duplicated")
            observed_keys.add(key)
            _verify_event(
                event, target=target, run_dir=run_dir,
                exclusion_digest=preflight["candidate_exclusion_digest"],
                contract=contract,
            )
    if observed_keys != set(by_identity):
        raise ContractError("O3a PEM event target set incomplete")
    if len(exclusion) != contract["population"]["candidate_exclusion_total"]:
        raise ContractError("O3a PEM candidate-exclusion population changed")
    for bucket in ("primary", "diagnostic"):
        rows = observed[bucket]
        counts = Counter(row["verdict_tier"] for row in rows)
        expected = contract["population"][bucket]
        if (
            len(rows) != expected["total"]
            or summary["event_summary"][bucket] != {
                "total": len(rows),
                "calibrated": len(rows) - counts["UNCALIBRATED"],
                "uncalibrated": counts["UNCALIBRATED"],
                "verdict_tier": dict(sorted(counts.items())),
            }
        ):
            raise ContractError(f"O3a PEM {bucket} summary changed")
    body = {
        "status": "PASS_VERIFIED_O3A_NATIVE_PEM_V1",
        "run_key": summary["run_key"],
        "contract_digest": contract["contract_digest"],
        "run_artifact_digest": summary["artifact_digest"],
        "event_summary": summary["event_summary"],
        "scientific_boundary": contract["scientific_boundary"],
    }
    compact = {**body, "artifact_digest": canonical_json_sha256(body)}
    compact_path = root / COMPACT_REL
    if compact_path.is_file():
        if _read_json(compact_path) != compact:
            raise ContractError("O3a PEM compact receipt changed")
    else:
        _atomic_json(compact_path, compact)
    return compact, run_dir


__all__ = [
    "COMPACT_REL", "CONTRACT_REL", "DEFAULT_EXTERNAL_ROOT", "load_contract",
    "preflight_inputs", "run_native_pem", "verify_native_pem",
]
