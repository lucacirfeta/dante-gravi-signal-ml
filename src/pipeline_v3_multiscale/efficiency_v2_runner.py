"""Paired end-to-end injection runner for multiscale efficiency v2.

The primary endpoint is the canonical 32 s detector-threshold decision.  The
short-scale decisions are diagnostic and are defined only conditionally on a
primary recovery.  Every injected trial retains the clean control from the
same frozen background identity.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import (
    ROOT,
    _read_jsonl,
    _verify_rows,
    load_contract,
    sha256_file,
    verify_cohort,
)
from src.pipeline_v3_multiscale.efficiency_v2_reference import (
    SCALE_LABELS,
    _encode_images,
    _read_raw_context,
    _runtime_identity,
    _score_tokens,
    load_reference_contract,
    verify_raw_sources,
    verify_reference,
)

RUNNER_CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2_runner.json")
SCHEMA_VERSION = 1
IMAGE_LABELS = ("primary_32", *SCALE_LABELS)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    temporary.replace(path)


def _assert_file_reference(
    root: Path, reference: Mapping[str, Any], label: str
) -> None:
    path = root / str(reference.get("path", ""))
    if not path.is_file() or sha256_file(path) != str(reference.get("sha256", "")):
        raise ContractError(f"multiscale runner {label} reference mismatch")


def _environment_path(reference: Mapping[str, Any]) -> Path:
    environment = "windows" if os.name == "nt" else "wsl"
    return Path(str(reference["path_by_environment"][environment])).resolve()


def validate_runner_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("multiscale runner contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported multiscale runner schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-runner":
        raise ContractError("multiscale runner contract id changed")
    if value.get("status") != "APPROVED_PAIRED_INJECTION_INPUT":
        raise ContractError("multiscale paired injection runner is not approved")

    root = root.resolve()
    parent = load_contract(root)
    reference = load_reference_contract(root)
    parent_ref = value.get("parent_contract", {})
    reference_ref = value.get("reference_contract", {})
    if (
        parent_ref.get("contract_digest") != parent["contract_digest"]
        or reference_ref.get("contract_digest") != reference["contract_digest"]
    ):
        raise ContractError("multiscale runner parent contract changed")
    _assert_file_reference(root, parent_ref, "parent contract")
    _assert_file_reference(root, reference_ref, "reference contract")

    waveform = value.get("waveform", {})
    expected_durations = {
        "Blip": 1.0,
        "NarrowChirp": 1.0,
        "Whistle": 1.0,
        "ScatteredLight": 2.0,
        "NoiseBlob": 4.0,
        "HarmonicComb": 4.0,
        "WallOfLines": 4.0,
        "KoiFish": 1.0,
    }
    if waveform.get("duration_s_by_morphology") != expected_durations:
        raise ContractError("approved waveform durations changed")
    if (
        waveform.get("injection_alignment") != "center_of_32s_analysis_window"
        or waveform.get("injection_domain") != "raw_strain_before_whitening"
        or waveform.get("snr_reference") != "paired_clean_raw_32s_window"
        or waveform.get("seed_algorithm")
        != "sha256(contract+detector+raw_block+morphology+identity)_uint32_be"
    ):
        raise ContractError("approved waveform reconstruction changed")

    endpoint = value.get("endpoints", {})
    if (
        endpoint.get("primary_decision") != "injected_32s_score_gt_detector_native_p99"
        or endpoint.get("conditional_eligibility") != "primary_recovered"
        or endpoint.get("scale_or_fusion_allowed") is not False
        or endpoint.get("paired_clean_control_required") is not True
        or endpoint.get("rate_upper_limit_allowed") is not False
    ):
        raise ContractError("multiscale runner endpoint contract changed")

    paired = value.get("paired_design", {})
    expected_paired = {
        "same_backgrounds_across_morphologies": True,
        "same_backgrounds_across_target_snr": True,
        "clean_control_scored_once_per_background": True,
        "primary_source_blocks_per_detector": 100,
        "secondary_source_blocks_per_detector": 40,
        "expected_clean_controls": 280,
        "expected_primary_trials": 6000,
        "expected_secondary_trials": 1440,
        "expected_total_trials": 7440,
    }
    if paired != expected_paired:
        raise ContractError("approved paired-design cardinalities changed")

    for label in ("cohort", "reference_build"):
        frozen = value.get("frozen_inputs", {}).get(label, {})
        summary_path = root / str(frozen.get("compact_summary_path", ""))
        if not summary_path.is_file() or sha256_file(summary_path) != str(
            frozen.get("compact_summary_sha256", "")
        ):
            raise ContractError(f"frozen {label} compact summary mismatch")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        artifact_digest = summary.get(
            "external_artifact_digest", summary.get("artifact_digest")
        )
        if summary.get("run_key") != frozen.get(
            "run_key"
        ) or artifact_digest != frozen.get("artifact_digest"):
            raise ContractError(f"frozen {label} identity mismatch")

    for name, source_ref in value.get("references", {}).items():
        _assert_file_reference(root, source_ref, name)
    return value


def load_runner_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root.resolve() / RUNNER_CONTRACT_REL
    return validate_runner_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root.resolve()
    )


def derive_waveform_seed(
    contract_digest: str, row: Mapping[str, Any], morphology: str
) -> tuple[int, str]:
    material = {
        "contract_digest": str(contract_digest),
        "detector": str(row["detector"]),
        "raw_block_sha256": str(row["raw_block"]["source_sha256"]),
        "morphology": str(morphology),
        "identity_digest": str(row["identity_digest"]),
    }
    digest = canonical_json_sha256(material)
    return int.from_bytes(bytes.fromhex(digest[:8]), "big", signed=False), digest


def _generate_unit_waveform(
    *, morphology: str, duration_s: float, sample_rate_hz: int, seed: int
) -> np.ndarray:
    from src.core.injection import SyntheticGlitchGenerator

    state = np.random.get_state()
    try:
        np.random.seed(seed)
        waveform = SyntheticGlitchGenerator(sample_rate=sample_rate_hz).generate(
            morphology, amplitude=1.0, duration=duration_s
        )
    finally:
        np.random.set_state(state)
    waveform = np.ascontiguousarray(np.asarray(waveform, dtype=np.float64))
    expected = round(duration_s * sample_rate_hz)
    if waveform.shape != (expected,) or np.any(~np.isfinite(waveform)):
        raise ContractError("multiscale unit waveform is invalid")
    if not np.any(waveform):
        raise ContractError("multiscale unit waveform is identically zero")
    return waveform


def _render_images(
    series: Any,
    *,
    gps_start: float,
    parent: Mapping[str, Any],
) -> tuple[list[np.ndarray], dict[str, Any]]:
    import matplotlib.pyplot as plt

    from src.core.preprocessor import (
        extract_clean_subwindow,
        generate_qtransform,
        whiten_context,
    )

    preprocessing = parent["preprocessing"]
    representation = parent["representation"]
    sample_rate = int(preprocessing["sample_rate_hz"])
    pad = float(preprocessing["whitening_pad_s"])
    duration = float(preprocessing["analysis_duration_s"])
    whitened, pad_info = whiten_context(
        series, gps_start, gps_start + duration, pad=pad
    )
    tolerance = 1.0 / sample_rate
    if (
        float(pad_info["effective_left"]) < pad - tolerance
        or float(pad_info["effective_right"]) < pad - tolerance
    ):
        raise ContractError("multiscale injection whitening context is incomplete")
    analysis = extract_clean_subwindow(whitened, gps_start, gps_start + duration)
    values = np.ascontiguousarray(analysis.value)
    if values.shape != (round(duration * sample_rate),) or np.any(~np.isfinite(values)):
        raise ContractError("multiscale injection analysis window is invalid")

    cmap_name = str(representation["colormap"])
    cmap = plt.get_cmap(cmap_name)
    image_shape = list(representation["image_shape"])

    def image_for(window: Any, qrange: Sequence[int]) -> np.ndarray:
        spectrogram = generate_qtransform(
            window,
            qrange=tuple(qrange),
            frange=tuple(representation["frequency_range_hz"]),
            output_size=tuple(image_shape[:2]),
            save_path=None,
            cmap=cmap_name,
        )
        image = np.ascontiguousarray(
            (cmap(spectrogram)[:, :, :3] * 255).astype(np.uint8)
        )
        if list(image.shape) != image_shape:
            raise ContractError("multiscale injection image shape changed")
        return image

    images = [image_for(analysis, representation["discovery"]["qrange"])]
    center = gps_start + duration / 2.0
    conditional = representation["conditional_multiscale"]
    for scale in conditional["scales_s"]:
        scale = float(scale)
        images.append(
            image_for(
                analysis.crop(center - scale / 2.0, center + scale / 2.0),
                conditional["qrange"],
            )
        )
    hashes = {
        label: hashlib.sha256(image.tobytes()).hexdigest()
        for label, image in zip(IMAGE_LABELS, images, strict=True)
    }
    return images, {
        "analysis_window_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
        "image_sha256_by_endpoint": hashes,
    }


def _preprocess_clean_task(
    arguments: tuple[Mapping[str, Any], str, Mapping[str, Any]],
) -> tuple[list[np.ndarray], dict[str, Any]]:
    row, raw_root_value, parent = arguments
    sample_rate = int(parent["preprocessing"]["sample_rate_hz"])
    raw_series, raw_values = _read_raw_context(
        row, raw_root=Path(raw_root_value), sample_rate_hz=sample_rate
    )
    images, replay = _render_images(
        raw_series, gps_start=float(row["gps_start"]), parent=parent
    )
    primary_hash = replay["image_sha256_by_endpoint"]["primary_32"]
    if primary_hash != str(row["expected_clean_image_sha256"]):
        raise ContractError("paired clean primary image hash mismatch")
    replay.update(
        {
            "detector": str(row["detector"]),
            "role": str(row["role"]),
            "role_index": int(row["role_index"]),
            "gps_start": float(row["gps_start"]),
            "identity_digest": str(row["identity_digest"]),
            "raw_source_sha256": str(row["raw_block"]["source_sha256"]),
            "raw_context_sha256": hashlib.sha256(raw_values.tobytes()).hexdigest(),
        }
    )
    return images, replay


def _preprocess_morphology_task(
    arguments: tuple[
        Mapping[str, Any],
        str,
        Mapping[str, Any],
        str,
        float,
        Sequence[float],
        str,
    ],
) -> list[tuple[list[np.ndarray], dict[str, Any]]]:
    from src.core.injection import InjectionEngine

    row, raw_root_value, parent, morphology, duration_s, target_snrs, digest = arguments
    sample_rate = int(parent["preprocessing"]["sample_rate_hz"])
    raw_series, raw_values = _read_raw_context(
        row, raw_root=Path(raw_root_value), sample_rate_hz=sample_rate
    )
    gps = float(row["gps_start"])
    analysis_duration = float(parent["preprocessing"]["analysis_duration_s"])
    center = gps + analysis_duration / 2.0
    seed, seed_digest = derive_waveform_seed(digest, row, morphology)
    unit = _generate_unit_waveform(
        morphology=morphology,
        duration_s=duration_s,
        sample_rate_hz=sample_rate,
        seed=seed,
    )
    engine = InjectionEngine(sample_rate=sample_rate)
    clean_raw = raw_series.crop(gps, gps + analysis_duration)
    unit_snr = float(engine.compute_snr(clean_raw, unit))
    if not math.isfinite(unit_snr) or unit_snr <= 0:
        raise ContractError("multiscale unit waveform SNR is invalid")
    raw_digest = hashlib.sha256(raw_values.tobytes()).hexdigest()
    unit_digest = hashlib.sha256(unit.tobytes()).hexdigest()
    results: list[tuple[list[np.ndarray], dict[str, Any]]] = []
    for target_snr in target_snrs:
        target_snr = float(target_snr)
        scaled = np.ascontiguousarray(unit * (target_snr / unit_snr))
        injected = engine.inject(raw_series.copy(), scaled, center)
        injected_values = np.ascontiguousarray(injected.value)
        if np.any(~np.isfinite(injected_values)):
            raise ContractError("multiscale injected raw context is non-finite")
        images, replay = _render_images(injected, gps_start=gps, parent=parent)
        trial_identity = {
            "contract_digest": digest,
            "role": str(row["role"]),
            "detector": str(row["detector"]),
            "identity_digest": str(row["identity_digest"]),
            "morphology": morphology,
            "target_snr": target_snr,
        }
        replay.update(
            {
                "trial_id": canonical_json_sha256(trial_identity),
                "detector": str(row["detector"]),
                "role": str(row["role"]),
                "role_index": int(row["role_index"]),
                "gps_start": gps,
                "identity_digest": str(row["identity_digest"]),
                "raw_source_sha256": str(row["raw_block"]["source_sha256"]),
                "raw_context_sha256": raw_digest,
                "injected_raw_context_sha256": hashlib.sha256(
                    injected_values.tobytes()
                ).hexdigest(),
                "morphology": morphology,
                "duration_s": float(duration_s),
                "target_snr": target_snr,
                "unit_snr": unit_snr,
                "amplitude_scale": target_snr / unit_snr,
                "waveform_seed": seed,
                "waveform_seed_digest": seed_digest,
                "unit_waveform_sha256": unit_digest,
                "scaled_waveform_sha256": hashlib.sha256(scaled.tobytes()).hexdigest(),
            }
        )
        results.append((images, replay))
    return results


def classify_trial_endpoints(
    *,
    clean_scores: Mapping[str, float],
    injected_scores: Mapping[str, float],
    primary_threshold: float,
    scale_thresholds: Mapping[str, float],
) -> dict[str, Any]:
    primary_recovered = float(injected_scores["primary_32"]) > float(primary_threshold)
    scale_rows: dict[str, Any] = {}
    for label in SCALE_LABELS:
        threshold = float(scale_thresholds[label])
        exceeds = float(injected_scores[label]) > threshold
        scale_rows[label] = {
            "injected_score": float(injected_scores[label]),
            "clean_score": float(clean_scores[label]),
            "threshold": threshold,
            "clean_exceeds_threshold": float(clean_scores[label]) > threshold,
            "diagnostic_exceeds_threshold": exceeds,
            "conditional_scale_response": exceeds if primary_recovered else None,
        }
    return {
        "primary": {
            "injected_score": float(injected_scores["primary_32"]),
            "clean_score": float(clean_scores["primary_32"]),
            "threshold": float(primary_threshold),
            "clean_exceeds_threshold": float(clean_scores["primary_32"])
            > float(primary_threshold),
            "end_to_end_recovered": primary_recovered,
        },
        "conditional_multiscale": {
            "eligible": primary_recovered,
            "scale_or_fusion_applied": False,
            "scales": scale_rows,
        },
    }


def _score_image_groups(
    groups: Sequence[Sequence[np.ndarray]],
    *,
    model: Any,
    transform: Any,
    device: Any,
    native_centroids: Any,
    short_centroids: Mapping[str, Any],
    parent: Mapping[str, Any],
    encoder_batch: int,
) -> list[dict[str, float]]:
    import torch

    flat = [image for group in groups for image in group]
    tokens: list[np.ndarray] = []
    for start in range(0, len(flat), encoder_batch):
        tokens.extend(
            _encode_images(
                flat[start : start + encoder_batch],
                model=model,
                transform=transform,
                device=device,
            )
        )
    expected = len(groups) * len(IMAGE_LABELS)
    if len(tokens) != expected:
        raise ContractError("multiscale runner encoder cardinality mismatch")
    rows: list[dict[str, float]] = []
    discovery_top_k = int(parent["representation"]["discovery"]["top_k"])
    conditional_top_k = int(parent["representation"]["conditional_multiscale"]["top_k"])
    for group_index in range(len(groups)):
        offset = group_index * len(IMAGE_LABELS)
        primary_tokens = torch.from_numpy(tokens[offset]).unsqueeze(0).to(device)
        row = {
            "primary_32": _score_tokens(
                primary_tokens, native_centroids, discovery_top_k
            )[0]
        }
        for scale_index, label in enumerate(SCALE_LABELS, start=1):
            scale_tokens = (
                torch.from_numpy(tokens[offset + scale_index]).unsqueeze(0).to(device)
            )
            row[label] = _score_tokens(
                scale_tokens, short_centroids[label], conditional_top_k
            )[0]
        rows.append(row)
    return rows


def _load_reference_inputs(
    *,
    runner: Mapping[str, Any],
    reference_run_dir: Path,
    device: Any,
    root: Path,
) -> tuple[Any, dict[str, dict[str, Any]], dict[str, Any]]:
    import torch

    reference_summary = verify_reference(run_dir=reference_run_dir, root=root)
    expected = runner["frozen_inputs"]["reference_build"]
    if (
        reference_summary["artifact_digest"] != expected["artifact_digest"]
        or reference_summary["run_key"] != expected["run_key"]
    ):
        raise ContractError("multiscale runner reference build changed")
    short: dict[str, dict[str, Any]] = {"H1": {}, "L1": {}}
    for detector in ("H1", "L1"):
        for label in SCALE_LABELS:
            entry = reference_summary["indices"][detector][label]
            with np.load(
                reference_run_dir / entry["filename"], allow_pickle=False
            ) as data:
                values = np.ascontiguousarray(data["embeddings"], dtype=np.float32)
            short[detector][label] = torch.from_numpy(values).to(device)
    threshold_path = reference_run_dir / reference_summary["thresholds"]["filename"]
    thresholds = json.loads(threshold_path.read_text(encoding="utf-8"))["thresholds"]

    native_ref = runner["frozen_inputs"]["canonical_native_index"]
    native_path = _environment_path(native_ref)
    if not native_path.is_file() or sha256_file(native_path) != native_ref["sha256"]:
        raise ContractError("canonical native index changed")
    with np.load(native_path, allow_pickle=False) as data:
        native_values = np.ascontiguousarray(data["embeddings"], dtype=np.float32)
    native = torch.from_numpy(native_values).to(device)

    primary_ref = runner["frozen_inputs"]["canonical_native_thresholds"]
    primary_path = _environment_path(primary_ref)
    if not primary_path.is_file() or sha256_file(primary_path) != primary_ref["sha256"]:
        raise ContractError("canonical native thresholds changed")
    primary = json.loads(primary_path.read_text(encoding="utf-8"))["thresholds"]
    return native, short, {"primary": primary, "conditional": thresholds}


def _runner_run_key(
    *,
    runner_contract_digest: str,
    cohort_artifact_digest: str,
    reference_artifact_digest: str,
    runtime_environment_digest: str,
) -> str:
    return canonical_json_sha256(
        {
            "stage": "run_multiscale_efficiency_v2_paired_injections",
            "runner_contract_digest": runner_contract_digest,
            "cohort_artifact_digest": cohort_artifact_digest,
            "reference_artifact_digest": reference_artifact_digest,
            "runtime_environment_digest": runtime_environment_digest,
        }
    )


def _clean_id(row: Mapping[str, Any], runner_digest: str) -> str:
    return canonical_json_sha256(
        {
            "runner_contract_digest": runner_digest,
            "role": row["role"],
            "detector": row["detector"],
            "identity_digest": row["identity_digest"],
        }
    )


def _chunk_path(run_dir: Path, replay: Mapping[str, Any]) -> Path:
    return (
        run_dir
        / "chunks"
        / str(replay["role"])
        / str(replay["detector"])
        / f"{int(replay['role_index']):04d}_{replay['morphology']}.json"
    )


def _verified_chunk(path: Path, expected_ids: Sequence[str]) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"multiscale injection chunk digest mismatch: {path}")
    rows = payload.get("trials", [])
    if [row.get("trial_id") for row in rows] != list(expected_ids):
        raise ContractError(f"multiscale injection chunk identities changed: {path}")
    return rows


def _update_progress(
    path: Path, *, stage: str, completed: int, total: int, started: float
) -> None:
    elapsed = max(0.0, time.monotonic() - started)
    rate = completed / elapsed if elapsed > 0 else 0.0
    remaining = (total - completed) / rate if rate > 0 else None
    _atomic_json(
        path,
        {
            "stage": stage,
            "completed": completed,
            "total": total,
            "fraction": completed / total if total else 1.0,
            "elapsed_seconds": elapsed,
            "estimated_remaining_seconds": remaining,
        },
    )


def preflight_runner(
    *,
    cohort_run_dir: Path,
    reference_run_dir: Path,
    raw_root: Path,
    device: str = "cuda",
    root: Path = ROOT,
) -> dict[str, Any]:
    import torch

    from src.core.encoder import build_dinov2_transform
    from src.core.model_loader import load_dinov2_model

    root = root.resolve()
    runner = load_runner_contract(root)
    parent = load_contract(root)
    cohort_summary = verify_cohort(run_dir=cohort_run_dir, root=root)
    rows = _read_jsonl(cohort_run_dir / cohort_summary["ledger"]["filename"])
    _verify_rows(rows, parent)
    row = next(row for row in rows if row["role"] == "primary_injection")
    morphology = parent["population"]["roles"]["primary_injection"]["morphologies"][0]
    target_snr = parent["population"]["roles"]["primary_injection"]["target_snr"][0]
    torch_device = torch.device(device)
    model = load_dinov2_model(torch_device, allow_download=False)
    transform = build_dinov2_transform(
        int(parent["representation"]["encoder_input_size"])
    )
    native, short, thresholds = _load_reference_inputs(
        runner=runner,
        reference_run_dir=reference_run_dir,
        device=torch_device,
        root=root,
    )
    clean_images, clean_replay = _preprocess_clean_task(
        (row, str(raw_root.resolve()), parent)
    )
    trial_groups = _preprocess_morphology_task(
        (
            row,
            str(raw_root.resolve()),
            parent,
            morphology,
            float(runner["waveform"]["duration_s_by_morphology"][morphology]),
            [target_snr],
            runner["contract_digest"],
        )
    )
    all_groups = [clean_images, trial_groups[0][0]]
    score_rows = _score_image_groups(
        all_groups,
        model=model,
        transform=transform,
        device=torch_device,
        native_centroids=native,
        short_centroids=short[str(row["detector"])],
        parent=parent,
        encoder_batch=10,
    )
    endpoint = classify_trial_endpoints(
        clean_scores=score_rows[0],
        injected_scores=score_rows[1],
        primary_threshold=float(thresholds["primary"][str(row["detector"])]["p99"]),
        scale_thresholds={
            label: float(
                thresholds["conditional"][str(row["detector"])][label]["point_p99"]
            )
            for label in SCALE_LABELS
        },
    )
    del (
        endpoint
    )  # preflight validates endpoint construction without publishing outcomes
    return {
        "status": "PASS_MULTISCALE_EFFICIENCY_V2_RUNNER_PREFLIGHT",
        "runner_contract_digest": runner["contract_digest"],
        "cohort_artifact_digest": cohort_summary["artifact_digest"],
        "reference_artifact_digest": runner["frozen_inputs"]["reference_build"][
            "artifact_digest"
        ],
        "runtime": _runtime_identity(device=device, model=model),
        "clean_control": clean_replay,
        "trial_replay": trial_groups[0][1],
        "image_group_count": len(all_groups),
        "images_per_group": len(IMAGE_LABELS),
    }


def run_paired_injections(
    *,
    cohort_run_dir: Path,
    reference_run_dir: Path,
    raw_root: Path,
    output_root: Path,
    device: str = "cuda",
    workers: int = 8,
    encoder_batch: int = 10,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    import multiprocessing as mp

    import torch

    from src.core.encoder import build_dinov2_transform
    from src.core.model_loader import load_dinov2_model

    root = root.resolve()
    runner = load_runner_contract(root)
    parent = load_contract(root)
    cohort_summary = verify_cohort(run_dir=cohort_run_dir, root=root)
    if (
        cohort_summary["artifact_digest"]
        != runner["frozen_inputs"]["cohort"]["artifact_digest"]
    ):
        raise ContractError("multiscale runner cohort changed")
    rows = _read_jsonl(cohort_run_dir / cohort_summary["ledger"]["filename"])
    _verify_rows(rows, parent)
    injection_rows = [
        row
        for row in rows
        if row["role"] in {"primary_injection", "secondary_dsd_control"}
    ]
    verify_raw_sources(injection_rows, raw_root=raw_root, workers=workers)

    torch_device = torch.device(device)
    model = load_dinov2_model(torch_device, allow_download=False)
    transform = build_dinov2_transform(
        int(parent["representation"]["encoder_input_size"])
    )
    runtime = _runtime_identity(device=device, model=model)
    reference_artifact = runner["frozen_inputs"]["reference_build"]["artifact_digest"]
    run_key = _runner_run_key(
        runner_contract_digest=runner["contract_digest"],
        cohort_artifact_digest=cohort_summary["artifact_digest"],
        reference_artifact_digest=reference_artifact,
        runtime_environment_digest=runtime["environment_digest"],
    )
    run_dir = output_root.resolve() / f"injections_{run_key}"
    summary_path = run_dir / "injection_summary.json"
    if summary_path.is_file():
        return verify_injection_run(run_dir=run_dir, root=root), run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("previous multiscale injection failure must be preserved")

    native, short, thresholds = _load_reference_inputs(
        runner=runner,
        reference_run_dir=reference_run_dir,
        device=torch_device,
        root=root,
    )
    clean_path = run_dir / "paired_clean_controls.jsonl"
    progress_path = run_dir / "progress.json"
    started = time.monotonic()
    role_contracts = parent["population"]["roles"]
    total = sum(
        len(role_contracts[row["role"]]["morphologies"])
        * len(role_contracts[row["role"]]["target_snr"])
        for row in injection_rows
    )
    try:
        clean_records: list[dict[str, Any]] = []
        clean_by_identity: dict[str, dict[str, Any]] = {}
        context = mp.get_context("spawn")
        clean_arguments = [
            (row, str(raw_root.resolve()), parent) for row in injection_rows
        ]
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            clean_results = executor.map(_preprocess_clean_task, clean_arguments)
            for row, (images, replay) in zip(
                injection_rows, clean_results, strict=True
            ):
                scores = _score_image_groups(
                    [images],
                    model=model,
                    transform=transform,
                    device=torch_device,
                    native_centroids=native,
                    short_centroids=short[str(row["detector"])],
                    parent=parent,
                    encoder_batch=encoder_batch,
                )[0]
                clean_id = _clean_id(row, runner["contract_digest"])
                record = {"clean_control_id": clean_id, **replay, "scores": scores}
                clean_records.append(record)
                clean_by_identity[str(row["identity_digest"])] = record
        _atomic_jsonl(clean_path, clean_records)

        tasks = []
        for row in injection_rows:
            role = role_contracts[str(row["role"])]
            for morphology in role["morphologies"]:
                tasks.append(
                    (
                        row,
                        str(raw_root.resolve()),
                        parent,
                        str(morphology),
                        float(
                            runner["waveform"]["duration_s_by_morphology"][morphology]
                        ),
                        list(role["target_snr"]),
                        runner["contract_digest"],
                    )
                )

        completed = 0
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            results = executor.map(_preprocess_morphology_task, tasks)
            for arguments, morphology_results in zip(tasks, results, strict=True):
                row = arguments[0]
                expected_ids = [item[1]["trial_id"] for item in morphology_results]
                chunk_path = _chunk_path(run_dir, morphology_results[0][1])
                if chunk_path.is_file():
                    _verified_chunk(chunk_path, expected_ids)
                else:
                    image_groups = [item[0] for item in morphology_results]
                    score_rows = _score_image_groups(
                        image_groups,
                        model=model,
                        transform=transform,
                        device=torch_device,
                        native_centroids=native,
                        short_centroids=short[str(row["detector"])],
                        parent=parent,
                        encoder_batch=encoder_batch,
                    )
                    clean = clean_by_identity[str(row["identity_digest"])]
                    detector = str(row["detector"])
                    primary_threshold = float(thresholds["primary"][detector]["p99"])
                    scale_thresholds = {
                        label: float(
                            thresholds["conditional"][detector][label]["point_p99"]
                        )
                        for label in SCALE_LABELS
                    }
                    trial_rows = []
                    for (_, replay), scores in zip(
                        morphology_results, score_rows, strict=True
                    ):
                        trial_rows.append(
                            {
                                **replay,
                                "paired_clean_control_id": clean["clean_control_id"],
                                "endpoints": classify_trial_endpoints(
                                    clean_scores=clean["scores"],
                                    injected_scores=scores,
                                    primary_threshold=primary_threshold,
                                    scale_thresholds=scale_thresholds,
                                ),
                            }
                        )
                    chunk_body = {
                        "schema_version": SCHEMA_VERSION,
                        "status": "PASS_MULTISCALE_EFFICIENCY_V2_TRIAL_CHUNK",
                        "runner_contract_digest": runner["contract_digest"],
                        "trials": trial_rows,
                    }
                    _atomic_json(
                        chunk_path,
                        {
                            **chunk_body,
                            "artifact_digest": canonical_json_sha256(chunk_body),
                        },
                    )
                completed += len(expected_ids)
                _update_progress(
                    progress_path,
                    stage=f"injections:{row['role']}:{row['detector']}",
                    completed=completed,
                    total=total,
                    started=started,
                )

        all_trials: list[dict[str, Any]] = []
        for arguments in tasks:
            row, _, _, morphology, _, snrs, digest = arguments
            expected_ids = []
            for target_snr in snrs:
                expected_ids.append(
                    canonical_json_sha256(
                        {
                            "contract_digest": digest,
                            "role": str(row["role"]),
                            "detector": str(row["detector"]),
                            "identity_digest": str(row["identity_digest"]),
                            "morphology": morphology,
                            "target_snr": float(target_snr),
                        }
                    )
                )
            seed, seed_digest = derive_waveform_seed(digest, row, morphology)
            del seed, seed_digest
            chunk = (
                run_dir
                / "chunks"
                / str(row["role"])
                / str(row["detector"])
                / f"{int(row['role_index']):04d}_{morphology}.json"
            )
            all_trials.extend(_verified_chunk(chunk, expected_ids))
        if (
            len(all_trials) != total
            or len({row["trial_id"] for row in all_trials}) != total
        ):
            raise ContractError("multiscale injection final cardinality mismatch")
        ledger_path = run_dir / "paired_injection_trials.jsonl"
        _atomic_jsonl(ledger_path, all_trials)
        summary_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_MULTISCALE_EFFICIENCY_V2_PAIRED_INJECTIONS",
            "run_key": run_key,
            "runner_contract_digest": runner["contract_digest"],
            "cohort_artifact_digest": cohort_summary["artifact_digest"],
            "reference_artifact_digest": reference_artifact,
            "runtime": runtime,
            "clean_controls": {
                "filename": clean_path.name,
                "row_total": len(clean_records),
                "sha256": sha256_file(clean_path),
            },
            "trials": {
                "filename": ledger_path.name,
                "row_total": len(all_trials),
                "sha256": sha256_file(ledger_path),
            },
            "cardinality_by_role": {
                role: sum(row["role"] == role for row in all_trials)
                for role in ("primary_injection", "secondary_dsd_control")
            },
            "scientific_boundary": {
                "primary_endpoint": "32s_detector_native_threshold",
                "multiscale_endpoint": "conditional_diagnostic_only",
                "scale_or_fusion_applied": False,
                "rate_upper_limit_computed": False,
                "legacy_artifacts_consumed": False,
            },
        }
        summary = {
            **summary_body,
            "artifact_digest": canonical_json_sha256(summary_body),
        }
        _atomic_json(summary_path, summary)
        _update_progress(
            progress_path,
            stage="complete",
            completed=total,
            total=total,
            started=started,
        )
        return verify_injection_run(run_dir=run_dir, root=root), run_dir
    except BaseException as exc:
        _atomic_json(
            failure_path,
            {
                "status": "FAILED_MULTISCALE_EFFICIENCY_V2_PAIRED_INJECTIONS",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "run_key": run_key,
            },
        )
        raise


def verify_injection_run(*, run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    runner = load_runner_contract(root.resolve())
    parent = load_contract(root.resolve())
    summary_path = run_dir / "injection_summary.json"
    if (run_dir / "failure.json").is_file():
        raise ContractError("multiscale injection failure artifact is present")
    if not summary_path.is_file():
        raise ContractError("multiscale injection summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("multiscale injection artifact digest mismatch")
    expected_run_key = _runner_run_key(
        runner_contract_digest=runner["contract_digest"],
        cohort_artifact_digest=runner["frozen_inputs"]["cohort"]["artifact_digest"],
        reference_artifact_digest=runner["frozen_inputs"]["reference_build"][
            "artifact_digest"
        ],
        runtime_environment_digest=str(
            summary.get("runtime", {}).get("environment_digest", "")
        ),
    )
    if (
        summary.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_PAIRED_INJECTIONS"
        or summary.get("runner_contract_digest") != runner["contract_digest"]
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"injections_{expected_run_key}"
    ):
        raise ContractError("multiscale injection run identity changed")
    for key in ("clean_controls", "trials"):
        entry = summary[key]
        path = run_dir / entry["filename"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ContractError(f"multiscale injection {key} hash mismatch")
        rows = _read_jsonl(path)
        if len(rows) != int(entry["row_total"]):
            raise ContractError(f"multiscale injection {key} cardinality mismatch")
    roles = parent["population"]["roles"]
    detector_count = len(parent["population"]["detectors"])
    expected_clean = detector_count * sum(
        int(roles[role]["source_blocks_per_detector"])
        for role in ("primary_injection", "secondary_dsd_control")
    )
    expected_trials = detector_count * sum(
        int(roles[role]["source_blocks_per_detector"])
        * len(roles[role]["morphologies"])
        * len(roles[role]["target_snr"])
        for role in ("primary_injection", "secondary_dsd_control")
    )
    if (
        int(summary["clean_controls"]["row_total"]) != expected_clean
        or int(summary["trials"]["row_total"]) != expected_trials
        or summary["scientific_boundary"]["scale_or_fusion_applied"] is not False
        or summary["scientific_boundary"]["rate_upper_limit_computed"] is not False
    ):
        raise ContractError("multiscale injection scientific gate failed")
    return summary


__all__ = [
    "IMAGE_LABELS",
    "RUNNER_CONTRACT_REL",
    "classify_trial_endpoints",
    "derive_waveform_seed",
    "load_runner_contract",
    "preflight_runner",
    "run_paired_injections",
    "validate_runner_contract",
    "verify_injection_run",
]
