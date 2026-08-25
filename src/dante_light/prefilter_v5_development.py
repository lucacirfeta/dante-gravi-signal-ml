"""One-shot development evaluation for the frozen DANTE-Light v5 students."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from src.dante_light.contracts import (
    ContractError,
    FailClosedReason,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.executor import DeferredWindow
from src.dante_light.prefilter_v5_development_contract import (
    DEFAULT_OUTPUT as DEFAULT_CONTRACT,
    load_development_contract,
)
from src.dante_light.prefilter_v5_injections import (
    load_frozen_trials,
    reconstruct_frozen_trial,
)
from src.dante_light.prefilter_v5_protocol import ROOT, repository_reference, sha256_path
from src.dante_light.prefilter_v5_teacher import (
    ExactNativeTeacher,
    PreparedTeacherInput,
    _fetch_teacher_strain,
)
from src.dante_light.prefilter_v5_training import ARMS, _model, student_input
from src.dante_light.prefilter_v5_waveforms import (
    validate_waveform_cache as validate_external_waveform_cache,
)


SCHEMA_VERSION = 1
DEFAULT_SPLIT_ENTRIES = ROOT / "config/dante_light_prefilter_splits_v5.jsonl"
DEFAULT_PROTOCOL = ROOT / "config/dante_light_prefilter_protocol_v5.json"
DEFAULT_TRIALS = ROOT / "config/dante_light_prefilter_v5_injection_trials.jsonl"
DEFAULT_TRAINING = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_training/student_training_summary_v5.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v5_development/development_result_v5.json"
)


def default_development_cache_root() -> Path:
    configured = os.environ.get("DANTE_V5_DEVELOPMENT_CACHE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path("E:/dante_cache/dante_light/prefilter_l4_v5_development").resolve()


def default_training_cache_root() -> Path:
    configured = os.environ.get("DANTE_V5_CACHE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path("E:/dante_cache/dante_light/prefilter_l4_v5_training").resolve()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as stream:
        np.savez(stream, **arrays)
    temporary.replace(path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v5 development JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"v5 development JSON is not a mapping: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"invalid v5 development JSONL {path}: {exc}") from exc


def load_development_rows(
    *, root: Path = ROOT, contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    reference = contract["source_references"]["split_entries"]
    path = root / str(reference["path"])
    if sha256_path(path) != reference["sha256"]:
        raise ContractError("v5 development split entries hash mismatch")
    rows = [row for row in _load_jsonl(path) if row.get("partition") == "development"]
    if not rows or any(row.get("partition") != "development" for row in rows):
        raise ContractError("v5 development partition is empty or contaminated")
    rows.sort(key=lambda row: (row["detector"], row["role"], row["cohort_id"]))
    if len({row["cohort_id"] for row in rows}) != len(rows):
        raise ContractError("v5 development cohort identities are duplicated")
    return rows


def waveform_run_key(
    contract: Mapping[str, Any], *, partition: str = "development"
) -> str:
    return canonical_json_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "partition": partition,
            "development_contract_digest": contract["development_contract_digest"],
            "injection_trials": contract["source_references"]["injection_trials"],
            "injection_reconstruction": contract["code_references"][
                "injection_reconstruction"
            ],
        }
    )


def build_injection_waveform_cache(
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    cache_root: Path | None = None,
) -> dict[str, Any]:
    """Materialize development waveforms without reading strain or outcomes."""

    contract = load_development_contract(contract_path, root=root)
    protocol = _load_json(root / contract["source_references"]["protocol"]["path"])
    trials_path = root / contract["source_references"]["injection_trials"]["path"]
    trials = load_frozen_trials(trials_path)
    selected = [trial for trial in trials.values() if trial["partition"] == "development"]
    selected.sort(key=lambda row: row["source_id"])
    if not selected:
        raise ContractError("v5 development injection waveform set is empty")
    run_key = waveform_run_key(contract)
    run_dir = (cache_root or default_development_cache_root()) / f"waveforms_{run_key}"
    rows = []
    for trial in selected:
        source_id = str(trial["source_id"])
        identity = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
        data_path = run_dir / "arrays" / f"{identity}.npz"
        row_path = run_dir / "records" / f"{identity}.json"
        if row_path.is_file():
            row = _load_json(row_path)
            body = dict(row)
            declared = body.pop("record_digest", None)
            if declared != canonical_json_sha256(body):
                raise ContractError("v5 waveform cache record digest mismatch")
            if row.get("run_key") != run_key or row.get("source_id") != source_id:
                raise ContractError("v5 waveform cache identity collision")
            if not data_path.is_file() or sha256_path(data_path) != row["array_sha256"]:
                raise ContractError("v5 waveform cache array mismatch")
            rows.append(row)
            continue
        parameters, projected = reconstruct_frozen_trial(trial, protocol)
        detector_strain = np.ascontiguousarray(projected.detector_strain, dtype=np.float64)
        if detector_strain.size == 0 or not np.isfinite(detector_strain).all():
            raise ContractError("v5 projected waveform is invalid")
        _atomic_npz(data_path, detector_strain=detector_strain)
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "WAVEFORM_COMPLETE_OUTCOME_BLIND",
            "run_key": run_key,
            "partition": "development",
            "source_id": source_id,
            "trial_digest": trial["trial_digest"],
            "parameters": parameters.to_dict(),
            "projection": {
                "detector_delay_s": projected.detector_delay_s,
                "geocentric_merger_gps": projected.geocentric_merger_gps,
                "detector_merger_gps": projected.detector_merger_gps,
                "injection_array_center_gps": projected.injection_array_center_gps,
            },
            "array_path": data_path.relative_to(run_dir).as_posix(),
            "array_sha256": sha256_path(data_path),
            "array_samples": int(detector_strain.size),
            "development_strain_accessed": False,
            "teacher_scores_accessed": False,
            "student_outputs_accessed": False,
            "confirmation_accessed": False,
            "o4b_accessed": False,
        }
        row = {**body, "record_digest": canonical_json_sha256(body)}
        _atomic_json(row_path, row)
        rows.append(row)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "COMPLETE_OUTCOME_BLIND_DEVELOPMENT_WAVEFORMS",
        "run_key": run_key,
        "development_contract_digest": contract["development_contract_digest"],
        "row_count": len(rows),
        "source_ids_digest": canonical_json_sha256([row["source_id"] for row in rows]),
        "record_digests": [row["record_digest"] for row in rows],
        "cache_location": {
            "environment_alias": "DANTE_V5_DEVELOPMENT_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
        },
        "development_strain_accessed": False,
        "teacher_scores_accessed": False,
        "student_outputs_accessed": False,
        "confirmation_accessed": False,
        "o4b_accessed": False,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "waveform_summary.json", summary)
    return summary


def _validate_waveform_cache(
    contract: Mapping[str, Any], *, cache_root: Path
) -> tuple[Path, dict[str, dict[str, Any]]]:
    run_key = waveform_run_key(contract)
    run_dir = cache_root / f"waveforms_{run_key}"
    summary = _load_json(run_dir / "waveform_summary.json")
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v5 waveform summary digest mismatch")
    if summary.get("status") != "COMPLETE_OUTCOME_BLIND_DEVELOPMENT_WAVEFORMS":
        raise ContractError("v5 development waveform cache is incomplete")
    records: dict[str, dict[str, Any]] = {}
    for path in sorted((run_dir / "records").glob("*.json")):
        row = _load_json(path)
        row_body = dict(row)
        if row_body.pop("record_digest", None) != canonical_json_sha256(row_body):
            raise ContractError("v5 waveform record digest mismatch")
        data_path = run_dir / row["array_path"]
        if sha256_path(data_path) != row["array_sha256"]:
            raise ContractError("v5 waveform array hash mismatch")
        records[row["source_id"]] = row
    if len(records) != int(summary["row_count"]):
        raise ContractError("v5 waveform cache row count mismatch")
    return run_dir, records


def _digest_array(value: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def _fetch_development_strain(
    window: WindowIdentity,
    *,
    representation: RepresentationContract,
    raw_cache_dir: Path,
) -> tuple[object, dict[str, Any]]:
    """Read local strain or fetch once into the versioned E: run cache."""

    from gwpy.timeseries import TimeSeries

    from src.core import data_loader

    start = window.gps_start - representation.whitening_pad_s
    end = window.gps_start + window.duration_s + representation.whitening_pad_s
    cache_name = f"{window.detector}_{start}_{end}.hdf5"
    cache_path = raw_cache_dir / cache_name
    if cache_path.is_file():
        strain = TimeSeries.read(cache_path)
        source = "development_run_cache"
    else:
        try:
            strain = _fetch_teacher_strain(
                window, representation=representation, local_only=True
            )
            source = "preexisting_local_raw_mirror"
        except DeferredWindow as exc:
            if exc.reason != FailClosedReason.DEPENDENCY_UNAVAILABLE:
                raise
            strain = data_loader.fetch_strain_data(
                window.detector,
                start,
                end,
                sample_rate=representation.sample_rate_hz,
                local_only=False,
                remote_only=False,
                cache_raw=False,
            )
            raw_cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(".tmp.hdf5")
            strain.write(temporary, format="hdf5", path="strain")
            temporary.replace(cache_path)
            source = "gwosc_fetched_into_development_run_cache"
    return strain, {
        "strain_source": source,
        "raw_cache_path": (
            cache_path.relative_to(raw_cache_dir.parent).as_posix()
            if cache_path.is_file()
            else None
        ),
        "raw_cache_file_sha256": sha256_path(cache_path) if cache_path.is_file() else None,
    }


def _prepare_from_strain(
    strain: object,
    *,
    window: WindowIdentity,
    representation: RepresentationContract,
    raw_sha256: str,
) -> PreparedTeacherInput:
    import matplotlib.pyplot as plt

    from src.core.preprocessor import extract_clean_subwindow, generate_qtransform, whiten_context

    start = window.gps_start
    end = start + window.duration_s
    pad = representation.whitening_pad_s
    tolerance = 1.0 / representation.sample_rate_hz
    actual_start = float(strain.t0.value)
    actual_end = actual_start + float(strain.duration.value)
    if (
        int(round(float(strain.sample_rate.value))) != representation.sample_rate_hz
        or actual_start > start - pad + tolerance
        or actual_end < end + pad - tolerance
        or not np.isfinite(strain.value).all()
    ):
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    began = time.perf_counter()
    whitened, padding = whiten_context(strain, start, end, pad=pad)
    clean = extract_clean_subwindow(whitened, start, end)
    whitening_s = time.perf_counter() - began
    if (
        float(padding.get("effective_left", 0.0)) + tolerance < pad
        or float(padding.get("effective_right", 0.0)) + tolerance < pad
        or abs(float(clean.duration.value) - window.duration_s) > tolerance
    ):
        raise DeferredWindow(FailClosedReason.INCOMPLETE_DATA)
    clean_values = np.ascontiguousarray(clean.value, dtype=np.float32)
    expected = int(representation.sample_rate_hz * representation.analysis_duration_s)
    if clean_values.shape != (expected,) or not np.isfinite(clean_values).all():
        raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    began = time.perf_counter()
    spectrogram = generate_qtransform(
        clean,
        save_path=None,
        cmap=representation.colormap,
        qrange=representation.query_qrange,
        frange=representation.frequency_range_hz,
        output_size=representation.image_shape[:2],
    )
    q_transform_s = time.perf_counter() - began
    began = time.perf_counter()
    rgba = plt.get_cmap(representation.colormap)(spectrogram)
    image = np.ascontiguousarray((rgba[:, :, :3] * 255).astype(np.uint8))
    rendering_s = time.perf_counter() - began
    if image.shape != representation.image_shape:
        raise DeferredWindow(FailClosedReason.NONFINITE_INPUT)
    return PreparedTeacherInput(
        image=image,
        clean_strain=clean_values,
        raw_strain_sha256=raw_sha256,
        clean_strain_sha256=_digest_array(clean_values),
        image_sha256=_digest_array(image),
        timings={
            "data_read_s": 0.0,
            "whitening_s": whitening_s,
            "q_transform_s": q_transform_s,
            "rendering_s": rendering_s,
        },
    )


def _prepare_injection(
    row: Mapping[str, Any],
    *,
    representation: RepresentationContract,
    waveform_run_dir: Path,
    waveform_record: Mapping[str, Any],
    raw_cache_dir: Path,
) -> tuple[PreparedTeacherInput, dict[str, Any]]:
    from src.core.injection import InjectionEngine

    window = WindowIdentity.from_dict(row["window"])
    began = time.perf_counter()
    raw, source_metadata = _fetch_development_strain(
        window,
        representation=representation,
        raw_cache_dir=raw_cache_dir,
    )
    data_read_s = time.perf_counter() - began
    raw_values = np.ascontiguousarray(raw.value)
    with np.load(waveform_run_dir / waveform_record["array_path"], allow_pickle=False) as values:
        projected = np.asarray(values["detector_strain"], dtype=np.float64)
    engine = InjectionEngine(sample_rate=representation.sample_rate_hz)
    injected = engine.inject(
        raw,
        projected,
        float(waveform_record["projection"]["injection_array_center_gps"]),
    )
    injected_values = np.ascontiguousarray(injected.value)
    prepared = _prepare_from_strain(
        injected,
        window=window,
        representation=representation,
        raw_sha256=_digest_array(injected_values),
    )
    prepared.timings["data_read_s"] = data_read_s
    return prepared, {
        "raw_background_strain_sha256": _digest_array(raw_values),
        "injected_strain_sha256": _digest_array(injected_values),
        "projected_waveform_sha256": waveform_record["array_sha256"],
        "waveform_record_digest": waveform_record["record_digest"],
        "snr_used_for_selection_or_gate": False,
        **source_metadata,
    }


def _load_models(
    *,
    root: Path,
    contract: Mapping[str, Any],
    training_cache_root: Path,
    device: torch.device,
) -> tuple[dict[tuple[str, int], torch.nn.Module], dict[str, Any]]:
    training = _load_json(root / contract["source_references"]["training_summary"]["path"])
    if training.get("artifact_digest") != contract["training_artifact_digest"]:
        raise ContractError("v5 development/training artifact digest mismatch")
    run_dir = training_cache_root / f"student_{training['run_key']}"
    models = {}
    for row in training["replicate_summaries"]:
        arm = str(row["arm"])
        replicate = int(row["replicate_index"])
        if row.get("status") != "TRAINING_COMPLETE":
            raise ContractError("v5 development cannot load an incomplete replicate")
        path = run_dir / row["best_model"]["path"]
        if sha256_path(path) != row["best_model"]["sha256"]:
            raise ContractError("v5 development model checkpoint hash mismatch")
        state = torch.load(path, map_location=device, weights_only=True)
        model = _model(arm).to(device=device, dtype=torch.float32)
        model.load_state_dict(state["model_state"])
        model.eval()
        models[(arm, replicate)] = model
    expected = {(arm, replicate) for arm in ARMS for replicate in range(5)}
    if set(models) != expected:
        raise ContractError("v5 development model matrix is incomplete")
    return models, training


def _clock(device: torch.device) -> float:
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    return time.perf_counter()


def _student_score(
    strain: np.ndarray,
    *,
    arm: str,
    model: torch.nn.Module,
    stft_contract: Mapping[str, Any],
    device: torch.device,
) -> tuple[float, dict[str, float]]:
    began = time.perf_counter()
    inputs = student_input(strain[None, :], arm=arm, stft_contract=stft_contract)
    transform_s = time.perf_counter() - began
    began = _clock(device)
    with torch.no_grad():
        prediction = model(inputs.to(device=device, dtype=torch.float32)).squeeze()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        value = float(prediction.detach().cpu().item())
    inference_s = _clock(device) - began
    if not math.isfinite(value):
        raise ContractError("v5 development student prediction is non-finite")
    return value, {
        "student_input_transform_s": transform_s,
        "student_batch1_inference_s": inference_s,
        "prefilter_total_s": transform_s + inference_s,
    }


def _ensure_development_access(run_dir: Path, *, run_key: str, rows: Sequence[Mapping[str, Any]]) -> None:
    path = run_dir / "development_access_log.jsonl"
    identity_digest = canonical_json_sha256([row["cohort_id"] for row in rows])
    body = {
        "schema_version": SCHEMA_VERSION,
        "sequence": 0,
        "run_key": run_key,
        "action": "OPEN_FROZEN_DEVELOPMENT_ONCE",
        "partition": "development",
        "identity_count": len(rows),
        "identity_digest": identity_digest,
        "confirmation_accessed": False,
        "o4b_accessed": False,
    }
    record = {**body, "record_digest": canonical_json_sha256(body)}
    if path.is_file():
        existing = _load_jsonl(path)
        if existing != [record]:
            raise ContractError("v5 development access ledger differs from frozen run")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(
            descriptor,
            (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def development_run_key(
    contract: Mapping[str, Any], *, device: torch.device
) -> str:
    environment = {
        "python": os.sys.version.split()[0],
        "numpy": np.__version__,
        "torch": torch.__version__,
        "device_type": device.type,
        "device_name": torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu",
    }
    return canonical_json_sha256(
        {
            "schema_version": SCHEMA_VERSION,
            "development_contract_digest": contract["development_contract_digest"],
            "training_run_key": contract["training_run_key"],
            "environment": environment,
        }
    )


def run_development_evaluation(
    *,
    root: Path = ROOT,
    contract_path: Path = DEFAULT_CONTRACT,
    development_cache_root: Path | None = None,
    training_cache_root: Path | None = None,
    device_name: str | None = None,
    workers: int = 2,
    output_path: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    """Open development once, score all frozen models and preserve a full E: ledger."""

    if not 1 <= workers <= 8:
        raise ContractError("v5 development workers must be in [1,8]")
    contract = load_development_contract(contract_path, root=root)
    rows = load_development_rows(root=root, contract=contract)
    device = torch.device(device_name or ("cuda" if torch.cuda.is_available() else "cpu"))
    run_key = development_run_key(contract, device=device)
    cache_root = (development_cache_root or default_development_cache_root()).resolve()
    run_dir = cache_root / f"development_{run_key}"
    _ensure_development_access(run_dir, run_key=run_key, rows=rows)
    waveform_dir, waveforms = validate_external_waveform_cache(
        contract, cache_root=cache_root
    )
    representation = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    )
    protocol = _load_json(root / contract["source_references"]["protocol"]["path"])
    stft_contract = protocol["approved_design"]["students"]["complex_stft_2d"]["stft"]
    models, training = _load_models(
        root=root,
        contract=contract,
        training_cache_root=(training_cache_root or default_training_cache_root()).resolve(),
        device=device,
    )
    teacher = ExactNativeTeacher(root=root, representation=representation, device=str(device))
    # Warm-up is synthetic and cannot reveal a development outcome.
    teacher.score([np.zeros(representation.image_shape, dtype=np.uint8)])
    zero_strain = np.zeros((representation.sample_rate_hz * 32,), dtype=np.float32)
    for (arm, _replicate), model in models.items():
        _student_score(
            zero_strain,
            arm=arm,
            model=model,
            stft_contract=stft_contract,
            device=device,
        )
    record_dir = run_dir / "records"
    strain_dir = run_dir / "strain"
    failures = []

    def prepare(row: Mapping[str, Any]) -> tuple[PreparedTeacherInput, dict[str, Any]]:
        if row["role"] == "injection":
            source_id = str(row["source"]["source_id"])
            if source_id not in waveforms:
                raise ContractError(f"v5 development waveform missing: {source_id}")
            return _prepare_injection(
                row,
                representation=representation,
                waveform_run_dir=waveform_dir,
                waveform_record=waveforms[source_id],
                raw_cache_dir=run_dir / "raw_strain_cache",
            )
        window = WindowIdentity.from_dict(row["window"])
        began = time.perf_counter()
        strain, source_metadata = _fetch_development_strain(
            window,
            representation=representation,
            raw_cache_dir=run_dir / "raw_strain_cache",
        )
        data_read_s = time.perf_counter() - began
        raw_values = np.ascontiguousarray(strain.value)
        prepared = _prepare_from_strain(
            strain,
            window=window,
            representation=representation,
            raw_sha256=_digest_array(raw_values),
        )
        prepared.timings["data_read_s"] = data_read_s
        return prepared, source_metadata

    pending = []
    completed: dict[str, dict[str, Any]] = {}
    for row in rows:
        identity = str(row["window"]["window_id"])
        record_path = record_dir / f"{identity}.json"
        if record_path.is_file():
            record = _load_json(record_path)
            record_body = dict(record)
            if record_body.pop("record_digest", None) != canonical_json_sha256(record_body):
                raise ContractError("v5 development cached record digest mismatch")
            if record.get("run_key") != run_key or record.get("cohort_id") != row["cohort_id"]:
                raise ContractError("v5 development cached record identity collision")
            strain_path = run_dir / record["clean_strain_path"]
            if sha256_path(strain_path) != record["clean_strain_file_sha256"]:
                raise ContractError("v5 development cached strain file mismatch")
            completed[identity] = record
        else:
            pending.append(row)

    def finalize(row: Mapping[str, Any], prepared: PreparedTeacherInput, metadata: Mapping[str, Any]) -> dict[str, Any]:
        scores, teacher_timings = teacher.score([prepared.image])
        teacher_score = float(scores[0])
        identity = str(row["window"]["window_id"])
        strain_path = strain_dir / f"{identity}.npz"
        _atomic_npz(strain_path, clean_strain=prepared.clean_strain)
        student = {}
        for arm in ARMS:
            arm_rows = []
            for replicate in range(5):
                prediction, timings = _student_score(
                    prepared.clean_strain,
                    arm=arm,
                    model=models[(arm, replicate)],
                    stft_contract=stft_contract,
                    device=device,
                )
                arm_rows.append(
                    {
                        "replicate_index": replicate,
                        "prediction_standardized": prediction,
                        "timings": timings,
                    }
                )
            student[arm] = arm_rows
        exact_cost = (
            float(prepared.timings["q_transform_s"])
            + float(prepared.timings["rendering_s"])
            + float(teacher_timings["score_total_s"])
        )
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "DEVELOPMENT_ROW_COMPLETE",
            "run_key": run_key,
            "partition": "development",
            "cohort_id": row["cohort_id"],
            "window": row["window"],
            "detector": row["detector"],
            "role": row["role"],
            "morphology": row["morphology"],
            "retention_target": row["retention_target"],
            "source_id": row["source"]["source_id"],
            "gps_block": f"{row['detector']}:{math.floor(float(row['window']['gps_start']) / 4096)}",
            "teacher_score_native": teacher_score,
            "teacher_timings": teacher_timings,
            "preparation_timings": prepared.timings,
            "avoidable_exact_path_cost_s": exact_cost,
            "student": student,
            "clean_strain_sha256": prepared.clean_strain_sha256,
            "clean_strain_path": strain_path.relative_to(run_dir).as_posix(),
            "clean_strain_file_sha256": sha256_path(strain_path),
            "preparation_metadata": dict(metadata),
            "confirmation_accessed": False,
            "o4b_accessed": False,
        }
        record = {**body, "record_digest": canonical_json_sha256(body)}
        _atomic_json(record_dir / f"{identity}.json", record)
        return record

    chunk_size = max(1, workers * 2)
    for start in range(0, len(pending), chunk_size):
        chunk = pending[start : start + chunk_size]
        prepared_by_id = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(prepare, row): row for row in chunk}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    prepared_by_id[row["cohort_id"]] = future.result()
                except Exception as exc:
                    failures.append(
                        {
                            "cohort_id": row["cohort_id"],
                            "window_id": row["window"]["window_id"],
                            "exception_type": type(exc).__name__,
                            "reason": exc.reason.value if isinstance(exc, DeferredWindow) else str(exc),
                        }
                    )
        for row in chunk:
            if row["cohort_id"] not in prepared_by_id:
                continue
            prepared, metadata = prepared_by_id[row["cohort_id"]]
            record = finalize(row, prepared, metadata)
            completed[row["window"]["window_id"]] = record
    if failures:
        failure_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "V5_NOT_READY_INCOMPLETE_DEVELOPMENT",
            "run_key": run_key,
            "failures": failures,
            "confirmation_accessed": False,
            "o4b_accessed": False,
        }
        _atomic_json(run_dir / "development_failures.json", failure_body)
        raise ContractError(
            f"v5 development has {len(failures)} unresolved rows; resume the same run key"
        )
    if len(completed) != len(rows):
        raise ContractError("v5 development ledger is incomplete")
    ordered = [completed[row["window"]["window_id"]] for row in rows]
    ledger_path = run_dir / "development_rows_v5.jsonl"
    ledger_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in ordered),
        encoding="utf-8",
        newline="\n",
    )
    counts: dict[str, int] = {}
    for row in ordered:
        key = f"{row['detector']}|{row['role']}|{row['morphology']}"
        counts[key] = counts.get(key, 0) + 1
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "DEVELOPMENT_MATRIX_COMPLETE_PENDING_SCREENING",
        "run_key": run_key,
        "development_contract_digest": contract["development_contract_digest"],
        "training_artifact_digest": training["artifact_digest"],
        "row_count": len(ordered),
        "stratum_counts": counts,
        "full_ledger": {
            "environment_alias": "DANTE_V5_DEVELOPMENT_CACHE_ROOT",
            "run_subdirectory": run_dir.name,
            "path": ledger_path.name,
            "sha256": sha256_path(ledger_path),
        },
        "access_ledger": {
            "path": "development_access_log.jsonl",
            "sha256": sha256_path(run_dir / "development_access_log.jsonl"),
            "entries": 1,
        },
        "source_references": {
            "contract": repository_reference(root, contract_path),
            "training_summary": contract["source_references"]["training_summary"],
        },
        "development_rows_accessed": [row["cohort_id"] for row in rows],
        "confirmation_rows_accessed": [],
        "o4b_rows_accessed": [],
        "routing_enabled": False,
        "candidate_promotion_allowed": False,
    }
    summary = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "development_result_v5.json", summary)
    _atomic_json(output_path, summary)
    return summary
