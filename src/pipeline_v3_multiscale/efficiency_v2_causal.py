"""Causal stage-trace diagnostic for the frozen multiscale efficiency v2 run.

This module does not alter the production representation, index, thresholds,
or populations.  It replays an outcome-blind subset of the already frozen
paired injections and measures where injected/clean pairs diverge along the
existing raw -> Q-transform -> DINO -> VQ -> threshold chain.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import warnings
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
    _encode_images,
    _read_raw_context,
    _runtime_identity,
    verify_raw_sources,
)
from src.pipeline_v3_multiscale.efficiency_v2_runner import (
    _environment_path,
    _generate_unit_waveform,
    derive_waveform_seed,
    load_runner_contract,
    verify_injection_run,
)

CAUSAL_CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2_causal.json")
SCHEMA_VERSION = 1


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
        raise ContractError(f"multiscale causal {label} reference mismatch")


def validate_causal_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("multiscale causal contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported multiscale causal schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-causal":
        raise ContractError("multiscale causal contract id changed")
    if value.get("status") != "APPROVED_OUTCOME_BLIND_CAUSAL_DIAGNOSTIC_INPUT":
        raise ContractError("multiscale causal diagnostic is not approved")

    root = root.resolve()
    parent = load_contract(root)
    runner = load_runner_contract(root)
    parent_ref = value.get("parent_contract", {})
    runner_ref = value.get("runner_contract", {})
    if (
        parent_ref.get("contract_digest") != parent["contract_digest"]
        or runner_ref.get("contract_digest") != runner["contract_digest"]
    ):
        raise ContractError("multiscale causal parent contract changed")
    _assert_file_reference(root, parent_ref, "parent contract")
    _assert_file_reference(root, runner_ref, "runner contract")

    selection = value.get("selection", {})
    if selection != {
        "algorithm": "lowest_frozen_role_index",
        "rows_per_detector_role": 20,
        "reads_outcomes": False,
        "roles": {
            "primary_injection": [
                "Blip",
                "NarrowChirp",
                "Whistle",
                "NoiseBlob",
            ],
            "secondary_dsd_control": ["WallOfLines"],
        },
        "target_snr": [8, 12, 16, 24, 32, 48],
    }:
        raise ContractError("approved multiscale causal selection changed")

    trace = value.get("trace", {})
    expected_stages = [
        "whitened_time_series",
        "resized_q_before_normalization",
        "normalized_q",
        "rendered_rgb",
        "dinov2_patch_tokens",
        "vq_assignment_and_anomaly",
        "top_k_score",
        "frozen_detector_p99",
    ]
    if (
        trace.get("stages") != expected_stages
        or trace.get("primary_window_only") is not True
        or trace.get("changes_production_outputs") is not False
    ):
        raise ContractError("multiscale causal trace boundary changed")

    uncertainty = value.get("uncertainty", {})
    if (
        uncertainty.get("method") != "paired_raw_source_block_bootstrap"
        or uncertainty.get("resamples") != 2000
        or uncertainty.get("confidence") != 0.95
        or uncertainty.get("seed") != 42
        or uncertainty.get("iid_bootstrap_allowed") is not False
        or uncertainty.get("detectors_pooled") is not False
        or uncertainty.get("morphologies_pooled") is not False
    ):
        raise ContractError("multiscale causal uncertainty contract changed")

    tolerance = value.get("replay", {}).get("score_absolute_tolerance")
    if tolerance != 2e-7:
        raise ContractError("multiscale causal replay tolerance changed")
    if (
        value.get("scientific_boundary", {}).get("automatic_causal_label_allowed")
        is not False
    ):
        raise ContractError("multiscale causal interpretation gate changed")
    for label, reference in value.get("references", {}).items():
        _assert_file_reference(root, reference, label)
    frozen = value.get("frozen_input", {})
    compact = root / str(frozen.get("compact_summary_path", ""))
    if not compact.is_file() or sha256_file(compact) != frozen.get(
        "compact_summary_sha256"
    ):
        raise ContractError("multiscale causal frozen injection summary changed")
    compact_value = json.loads(compact.read_text(encoding="utf-8"))
    if (
        compact_value.get("run_key") != frozen.get("run_key")
        or compact_value.get("external_artifact_digest")
        != frozen.get("artifact_digest")
        or compact_value.get("trials", {}).get("sha256") != frozen.get("trials_sha256")
        or compact_value.get("clean_controls", {}).get("sha256")
        != frozen.get("clean_controls_sha256")
    ):
        raise ContractError("multiscale causal frozen injection identity changed")
    return value


def load_causal_contract(root: Path = ROOT) -> dict[str, Any]:
    path = root.resolve() / CAUSAL_CONTRACT_REL
    return validate_causal_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root.resolve()
    )


def select_diagnostic_rows(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    limit = int(contract["selection"]["rows_per_detector_role"])
    roles = contract["selection"]["roles"]
    selected: list[dict[str, Any]] = []
    for role in roles:
        for detector in ("H1", "L1"):
            group = sorted(
                (
                    dict(row)
                    for row in rows
                    if row["role"] == role and row["detector"] == detector
                ),
                key=lambda row: int(row["role_index"]),
            )
            expected = list(range(limit))
            observed = [int(row["role_index"]) for row in group[:limit]]
            if observed != expected:
                raise ContractError(
                    f"multiscale causal role-index selection changed: {role}/{detector}"
                )
            selected.extend(group[:limit])
    if len(selected) != limit * 2 * len(roles):
        raise ContractError("multiscale causal selected-row cardinality changed")
    return selected


def _raw_q_stages(
    series: Any, *, parent: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import matplotlib.pyplot as plt
    from scipy.ndimage import zoom

    from src.core.utils import normalize_spectrogram

    representation = parent["representation"]
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=(
                r"upper frequency of .* Hz is too high for the given Q range, "
                r"resetting to .* Hz"
            ),
            category=UserWarning,
            module=r"gwpy\.signal\.qtransform",
        )
        q_gram = series.q_transform(
            qrange=tuple(representation["discovery"]["qrange"]),
            frange=tuple(representation["frequency_range_hz"]),
            logf=True,
            whiten=False,
        )
    raw = np.asarray(q_gram.value, dtype=np.float64)
    output_size = tuple(representation["image_shape"][:2])
    resized = np.ascontiguousarray(
        zoom(
            raw,
            (output_size[0] / raw.shape[0], output_size[1] / raw.shape[1]),
            order=1,
        )
    )
    normalized = np.ascontiguousarray(normalize_spectrogram(resized))
    cmap = plt.get_cmap(str(representation["colormap"]))
    image = np.ascontiguousarray((cmap(normalized)[:, :, :3] * 255).astype(np.uint8))
    if list(image.shape) != representation["image_shape"]:
        raise ContractError("multiscale causal image shape changed")
    return resized, normalized, image


def _rms(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values, dtype=np.float64))))


def _relative_l2(delta: np.ndarray, reference: np.ndarray) -> float:
    denominator = float(np.linalg.norm(reference.ravel()))
    if denominator <= 0 or not math.isfinite(denominator):
        raise ContractError("multiscale causal reference norm is invalid")
    return float(np.linalg.norm(delta.ravel()) / denominator)


def _stage_metrics(
    *,
    clean_whitened: np.ndarray,
    injected_whitened: np.ndarray,
    clean_raw_q: np.ndarray,
    injected_raw_q: np.ndarray,
    clean_normalized_q: np.ndarray,
    injected_normalized_q: np.ndarray,
    clean_image: np.ndarray,
    injected_image: np.ndarray,
) -> dict[str, float]:
    whitened_delta = injected_whitened - clean_whitened
    raw_q_delta = injected_raw_q - clean_raw_q
    normalized_delta = injected_normalized_q - clean_normalized_q
    image_delta = np.abs(injected_image.astype(np.int16) - clean_image.astype(np.int16))
    clean_q_energy = float(np.sum(np.square(clean_raw_q, dtype=np.float64)))
    injected_q_energy = float(np.sum(np.square(injected_raw_q, dtype=np.float64)))
    if clean_q_energy <= 0:
        raise ContractError("multiscale causal clean Q energy is invalid")
    return {
        "whitened_delta_rms_over_clean_rms": _rms(whitened_delta)
        / _rms(clean_whitened),
        "raw_q_relative_l2_delta": _relative_l2(raw_q_delta, clean_raw_q),
        "raw_q_energy_ratio": injected_q_energy / clean_q_energy,
        "normalized_q_mean_absolute_delta": float(np.mean(np.abs(normalized_delta))),
        "normalized_q_relative_l2_delta": _relative_l2(
            normalized_delta, clean_normalized_q
        ),
        "rgb_mean_absolute_delta_over_255": float(np.mean(image_delta)) / 255.0,
        "rgb_changed_fraction": float(np.mean(np.any(image_delta > 0, axis=2))),
    }


def _render_primary_stages(
    series: Any, *, gps_start: float, parent: Mapping[str, Any]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    from src.core.preprocessor import extract_clean_subwindow, whiten_context

    preprocessing = parent["preprocessing"]
    sample_rate = int(preprocessing["sample_rate_hz"])
    duration = float(preprocessing["analysis_duration_s"])
    pad = float(preprocessing["whitening_pad_s"])
    whitened, pad_info = whiten_context(
        series, gps_start, gps_start + duration, pad=pad
    )
    tolerance = 1.0 / sample_rate
    if (
        float(pad_info["effective_left"]) < pad - tolerance
        or float(pad_info["effective_right"]) < pad - tolerance
    ):
        raise ContractError("multiscale causal whitening context is incomplete")
    analysis = extract_clean_subwindow(whitened, gps_start, gps_start + duration)
    whitened_values = np.ascontiguousarray(analysis.value, dtype=np.float64)
    expected = round(duration * sample_rate)
    if whitened_values.shape != (expected,) or np.any(~np.isfinite(whitened_values)):
        raise ContractError("multiscale causal whitened window is invalid")
    raw_q, normalized_q, image = _raw_q_stages(analysis, parent=parent)
    return (
        whitened_values,
        raw_q,
        normalized_q,
        image,
        {
            "analysis_window_sha256": hashlib.sha256(
                whitened_values.tobytes()
            ).hexdigest(),
            "primary_image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        },
    )


def _diagnostic_trial_id(causal_digest: str, frozen_trial_id: str) -> str:
    return canonical_json_sha256(
        {
            "causal_contract_digest": causal_digest,
            "frozen_trial_id": frozen_trial_id,
        }
    )


def _preprocess_diagnostic_row(
    arguments: tuple[
        Mapping[str, Any],
        str,
        Mapping[str, Any],
        Mapping[str, Any],
        Mapping[str, Mapping[str, Any]],
    ],
) -> tuple[list[np.ndarray], list[dict[str, Any]], dict[str, Any]]:
    from src.core.injection import InjectionEngine

    row, raw_root_value, parent, runner, frozen_trials = arguments
    sample_rate = int(parent["preprocessing"]["sample_rate_hz"])
    raw_series, raw_values = _read_raw_context(
        row, raw_root=Path(raw_root_value), sample_rate_hz=sample_rate
    )
    gps = float(row["gps_start"])
    clean_whitened, clean_raw_q, clean_normalized_q, clean_image, clean_replay = (
        _render_primary_stages(raw_series, gps_start=gps, parent=parent)
    )
    if clean_replay["primary_image_sha256"] != row["expected_clean_image_sha256"]:
        raise ContractError("multiscale causal clean image hash mismatch")

    role = str(row["role"])
    morphologies = list(
        frozen_trials["__selection__"]["roles"][role]  # type: ignore[index]
    )
    target_snrs = list(frozen_trials["__selection__"]["target_snr"])  # type: ignore[index]
    duration_map = runner["waveform"]["duration_s_by_morphology"]
    analysis_duration = float(parent["preprocessing"]["analysis_duration_s"])
    center = gps + analysis_duration / 2.0
    engine = InjectionEngine(sample_rate=sample_rate)
    clean_raw = raw_series.crop(gps, gps + analysis_duration)
    images = [clean_image]
    records: list[dict[str, Any]] = []
    for morphology in morphologies:
        seed, seed_digest = derive_waveform_seed(
            str(runner["contract_digest"]), row, morphology
        )
        unit = _generate_unit_waveform(
            morphology=morphology,
            duration_s=float(duration_map[morphology]),
            sample_rate_hz=sample_rate,
            seed=seed,
        )
        unit_snr = float(engine.compute_snr(clean_raw, unit))
        if not math.isfinite(unit_snr) or unit_snr <= 0:
            raise ContractError("multiscale causal unit SNR is invalid")
        for target_snr_value in target_snrs:
            target_snr = float(target_snr_value)
            frozen_key = f"{morphology}|{target_snr:g}"
            frozen = frozen_trials.get(frozen_key)
            if frozen is None:
                raise ContractError("multiscale causal frozen trial is absent")
            scaled = np.ascontiguousarray(unit * (target_snr / unit_snr))
            injected = engine.inject(raw_series.copy(), scaled, center)
            (
                injected_whitened,
                injected_raw_q,
                injected_normalized_q,
                injected_image,
                injected_replay,
            ) = _render_primary_stages(injected, gps_start=gps, parent=parent)
            images.append(injected_image)
            records.append(
                {
                    "diagnostic_trial_id": _diagnostic_trial_id(
                        str(frozen_trials["__causal_digest__"]),  # type: ignore[index]
                        str(frozen["trial_id"]),
                    ),
                    "frozen_trial_id": str(frozen["trial_id"]),
                    "detector": str(row["detector"]),
                    "role": role,
                    "role_index": int(row["role_index"]),
                    "identity_digest": str(row["identity_digest"]),
                    "raw_source_sha256": str(row["raw_block"]["source_sha256"]),
                    "gps_start": gps,
                    "morphology": morphology,
                    "target_snr": target_snr,
                    "waveform_seed": seed,
                    "waveform_seed_digest": seed_digest,
                    "unit_snr": unit_snr,
                    "amplitude_scale": target_snr / unit_snr,
                    "scaled_waveform_sha256": hashlib.sha256(
                        scaled.tobytes()
                    ).hexdigest(),
                    "primary_image_sha256": injected_replay["primary_image_sha256"],
                    "frozen_primary_image_sha256": frozen["image_sha256_by_endpoint"][
                        "primary_32"
                    ],
                    "frozen_primary_score": float(
                        frozen["endpoints"]["primary"]["injected_score"]
                    ),
                    "frozen_primary_threshold": float(
                        frozen["endpoints"]["primary"]["threshold"]
                    ),
                    "frozen_primary_recovered": bool(
                        frozen["endpoints"]["primary"]["end_to_end_recovered"]
                    ),
                    "pre_embedding": _stage_metrics(
                        clean_whitened=clean_whitened,
                        injected_whitened=injected_whitened,
                        clean_raw_q=clean_raw_q,
                        injected_raw_q=injected_raw_q,
                        clean_normalized_q=clean_normalized_q,
                        injected_normalized_q=injected_normalized_q,
                        clean_image=clean_image,
                        injected_image=injected_image,
                    ),
                }
            )
    return (
        images,
        records,
        {
            "detector": str(row["detector"]),
            "role": role,
            "role_index": int(row["role_index"]),
            "identity_digest": str(row["identity_digest"]),
            "raw_context_sha256": hashlib.sha256(raw_values.tobytes()).hexdigest(),
            **clean_replay,
        },
    )


def _vq_metrics(
    clean_tokens: np.ndarray,
    injected_tokens: np.ndarray,
    *,
    centroids: Any,
    device: Any,
    top_k: int,
) -> dict[str, float]:
    import torch

    clean = torch.from_numpy(clean_tokens).to(device)
    injected = torch.from_numpy(injected_tokens).to(device)
    with torch.inference_mode():
        displacement = 1.0 - torch.sum(clean * injected, dim=1)
        clean_similarity = torch.matmul(clean, centroids.T)
        injected_similarity = torch.matmul(injected, centroids.T)
        clean_best, clean_assignment = clean_similarity.max(dim=1)
        injected_best, injected_assignment = injected_similarity.max(dim=1)
        clean_anomaly = 1.0 - clean_best
        injected_anomaly = 1.0 - injected_best
        clean_top = torch.topk(clean_anomaly, k=top_k).indices
        injected_top = torch.topk(injected_anomaly, k=top_k).indices
        clean_score = torch.topk(clean_anomaly, k=top_k).values.mean()
        injected_score = torch.topk(injected_anomaly, k=top_k).values.mean()
    displacement_np = displacement.detach().cpu().numpy().astype(np.float64)
    clean_top_set = set(clean_top.detach().cpu().numpy().tolist())
    injected_top_set = set(injected_top.detach().cpu().numpy().tolist())
    union = clean_top_set | injected_top_set
    jaccard = len(clean_top_set & injected_top_set) / len(union)
    return {
        "token_cosine_distance_mean": float(np.mean(displacement_np)),
        "token_cosine_distance_median": float(np.median(displacement_np)),
        "token_cosine_distance_max": float(np.max(displacement_np)),
        "token_cosine_distance_top_k_mean": float(
            np.mean(np.sort(displacement_np)[-top_k:])
        ),
        "vq_assignment_change_fraction": float(
            torch.mean((clean_assignment != injected_assignment).float()).item()
        ),
        "vq_mean_anomaly_delta": float(
            torch.mean(injected_anomaly - clean_anomaly).item()
        ),
        "clean_primary_score": float(clean_score.item()),
        "injected_primary_score": float(injected_score.item()),
        "primary_score_delta": float((injected_score - clean_score).item()),
        "top_k_patch_position_jaccard": float(jaccard),
    }


def paired_block_bootstrap(
    rows: Sequence[Mapping[str, Any]],
    *,
    metrics: Sequence[str],
    n_resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, dict[str, float]]:
    if not rows:
        raise ContractError("multiscale causal bootstrap cell is empty")
    blocks = [str(row["raw_source_sha256"]) for row in rows]
    if len(set(blocks)) != len(rows):
        raise ContractError("multiscale causal bootstrap unit is not one row per block")
    matrix = np.asarray(
        [[float(row["metrics"][metric]) for metric in metrics] for row in rows],
        dtype=np.float64,
    )
    if np.any(~np.isfinite(matrix)):
        raise ContractError("multiscale causal bootstrap contains non-finite values")
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(rows), size=(n_resamples, len(rows)))
    boot = matrix[draws].mean(axis=1)
    alpha = (1.0 - confidence) * 50.0
    result: dict[str, dict[str, float]] = {}
    for index, metric in enumerate(metrics):
        result[metric] = {
            "mean": float(matrix[:, index].mean()),
            "ci_lower": float(np.percentile(boot[:, index], alpha)),
            "ci_upper": float(np.percentile(boot[:, index], 100.0 - alpha)),
        }
    return result


def _cell_seed(
    base_seed: int, detector: str, morphology: str, target_snr: float
) -> int:
    digest = canonical_json_sha256(
        {
            "seed": base_seed,
            "detector": detector,
            "morphology": morphology,
            "target_snr": target_snr,
        }
    )
    return int.from_bytes(bytes.fromhex(digest[:8]), "big", signed=False)


def summarize_diagnostic_rows(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    metric_names = list(contract["trace"]["reported_metrics"])
    uncertainty = contract["uncertainty"]
    cells: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            str(row["detector"]),
            str(row["morphology"]),
            float(row["target_snr"]),
        )
        cells.setdefault(key, []).append(dict(row))
    result = []
    expected_n = int(contract["selection"]["rows_per_detector_role"])
    for (detector, morphology, target_snr), group in sorted(cells.items()):
        if len(group) != expected_n:
            raise ContractError("multiscale causal cell cardinality changed")
        estimates = paired_block_bootstrap(
            group,
            metrics=metric_names,
            n_resamples=int(uncertainty["resamples"]),
            confidence=float(uncertainty["confidence"]),
            seed=_cell_seed(int(uncertainty["seed"]), detector, morphology, target_snr),
        )
        result.append(
            {
                "detector": detector,
                "morphology": morphology,
                "target_snr": target_snr,
                "raw_source_block_count": len(group),
                "recovered_count": sum(bool(row["recovered"]) for row in group),
                "metrics": estimates,
            }
        )
    return result


def _run_key(
    *,
    contract_digest: str,
    injection_artifact_digest: str,
    runtime_environment_digest: str,
) -> str:
    return canonical_json_sha256(
        {
            "stage": "diagnose_multiscale_efficiency_v2_causal_trace",
            "contract_digest": contract_digest,
            "injection_artifact_digest": injection_artifact_digest,
            "runtime_environment_digest": runtime_environment_digest,
        }
    )


def _chunk_path(run_dir: Path, row: Mapping[str, Any]) -> Path:
    return (
        run_dir
        / "chunks"
        / str(row["role"])
        / str(row["detector"])
        / f"{int(row['role_index']):04d}.json"
    )


def _verified_chunk(path: Path, expected_ids: Sequence[str]) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"multiscale causal chunk digest mismatch: {path}")
    rows = list(payload.get("rows", []))
    if [row.get("diagnostic_trial_id") for row in rows] != list(expected_ids):
        raise ContractError(f"multiscale causal chunk identities changed: {path}")
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


def _frozen_trials_for_row(
    row: Mapping[str, Any],
    *,
    frozen_trials: Mapping[tuple[str, str, str, float], Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {
        "__selection__": contract["selection"],
        "__causal_digest__": contract["contract_digest"],
    }
    role = str(row["role"])
    detector = str(row["detector"])
    identity = str(row["identity_digest"])
    for morphology in contract["selection"]["roles"][role]:
        for target_snr in contract["selection"]["target_snr"]:
            key = (detector, identity, str(morphology), float(target_snr))
            frozen = frozen_trials.get(key)
            if frozen is None:
                raise ContractError("multiscale causal frozen trial lookup failed")
            result[f"{morphology}|{float(target_snr):g}"] = frozen
    return result


def run_causal_diagnostic(
    *,
    cohort_run_dir: Path,
    injection_run_dir: Path,
    raw_root: Path,
    output_root: Path,
    device: str = "cuda",
    workers: int = 8,
    encoder_batch: int = 8,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    import multiprocessing as mp

    import torch

    from src.core.encoder import build_dinov2_transform
    from src.core.model_loader import load_dinov2_model

    root = root.resolve()
    contract = load_causal_contract(root)
    parent = load_contract(root)
    runner = load_runner_contract(root)
    cohort_summary = verify_cohort(run_dir=cohort_run_dir, root=root)
    if (
        cohort_summary["artifact_digest"]
        != runner["frozen_inputs"]["cohort"]["artifact_digest"]
    ):
        raise ContractError("multiscale causal cohort changed")
    injection_summary = verify_injection_run(run_dir=injection_run_dir, root=root)
    frozen = contract["frozen_input"]
    if (
        injection_summary["run_key"] != frozen["run_key"]
        or injection_summary["artifact_digest"] != frozen["artifact_digest"]
    ):
        raise ContractError("multiscale causal injection run changed")

    cohort_rows = _read_jsonl(cohort_run_dir / cohort_summary["ledger"]["filename"])
    _verify_rows(cohort_rows, parent)
    selected = select_diagnostic_rows(cohort_rows, contract)
    verify_raw_sources(selected, raw_root=raw_root, workers=workers)
    frozen_trial_rows = _read_jsonl(
        injection_run_dir / injection_summary["trials"]["filename"]
    )
    trial_lookup = {
        (
            str(row["detector"]),
            str(row["identity_digest"]),
            str(row["morphology"]),
            float(row["target_snr"]),
        ): row
        for row in frozen_trial_rows
    }
    clean_rows = _read_jsonl(
        injection_run_dir / injection_summary["clean_controls"]["filename"]
    )
    clean_lookup = {
        (str(row["detector"]), str(row["identity_digest"])): row for row in clean_rows
    }

    torch_device = torch.device(device)
    model = load_dinov2_model(torch_device, allow_download=False)
    transform = build_dinov2_transform(
        int(parent["representation"]["encoder_input_size"])
    )
    runtime = _runtime_identity(device=device, model=model)
    run_key = _run_key(
        contract_digest=contract["contract_digest"],
        injection_artifact_digest=injection_summary["artifact_digest"],
        runtime_environment_digest=runtime["environment_digest"],
    )
    run_dir = output_root.resolve() / f"causal_{run_key}"
    summary_path = run_dir / "causal_summary.json"
    if summary_path.is_file():
        return verify_causal_diagnostic(run_dir=run_dir, root=root), run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("previous multiscale causal failure must be preserved")

    native_ref = runner["frozen_inputs"]["canonical_native_index"]
    native_path = _environment_path(native_ref)
    if not native_path.is_file() or sha256_file(native_path) != native_ref["sha256"]:
        raise ContractError("multiscale causal native index changed")
    with np.load(native_path, allow_pickle=False) as data:
        centroids_np = np.ascontiguousarray(data["embeddings"], dtype=np.float32)
    centroids = torch.from_numpy(centroids_np).to(torch_device)
    top_k = int(parent["representation"]["discovery"]["top_k"])
    tolerance = float(contract["replay"]["score_absolute_tolerance"])
    total = sum(
        len(contract["selection"]["roles"][str(row["role"])])
        * len(contract["selection"]["target_snr"])
        for row in selected
    )
    progress_path = run_dir / "progress.json"
    started = time.monotonic()

    try:
        completed = 0
        pending: list[dict[str, Any]] = []
        for row in selected:
            frozen_for_row = _frozen_trials_for_row(
                row,
                frozen_trials=trial_lookup,
                contract=contract,
            )
            expected_ids = [
                _diagnostic_trial_id(contract["contract_digest"], item["trial_id"])
                for key, item in frozen_for_row.items()
                if not key.startswith("__")
            ]
            chunk = _chunk_path(run_dir, row)
            if chunk.is_file():
                _verified_chunk(chunk, expected_ids)
                completed += len(expected_ids)
            else:
                pending.append(row)
        _update_progress(
            progress_path,
            stage="resume_check",
            completed=completed,
            total=total,
            started=started,
        )

        arguments = [
            (
                row,
                str(raw_root.resolve()),
                parent,
                runner,
                _frozen_trials_for_row(
                    row, frozen_trials=trial_lookup, contract=contract
                ),
            )
            for row in pending
        ]
        context = mp.get_context("spawn")
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            results = executor.map(_preprocess_diagnostic_row, arguments)
            for row, (images, records, clean_replay) in zip(
                pending, results, strict=True
            ):
                frozen_for_row = _frozen_trials_for_row(
                    row, frozen_trials=trial_lookup, contract=contract
                )
                expected_ids = [
                    _diagnostic_trial_id(contract["contract_digest"], item["trial_id"])
                    for key, item in frozen_for_row.items()
                    if not key.startswith("__")
                ]
                if [
                    record["diagnostic_trial_id"] for record in records
                ] != expected_ids:
                    raise ContractError("multiscale causal worker ordering changed")
                tokens: list[np.ndarray] = []
                for start in range(0, len(images), encoder_batch):
                    tokens.extend(
                        _encode_images(
                            images[start : start + encoder_batch],
                            model=model,
                            transform=transform,
                            device=torch_device,
                        )
                    )
                if len(tokens) != len(records) + 1:
                    raise ContractError("multiscale causal encoder cardinality changed")
                clean_tokens = tokens[0]
                frozen_clean = clean_lookup[
                    (str(row["detector"]), str(row["identity_digest"]))
                ]
                completed_rows: list[dict[str, Any]] = []
                for record, injected_tokens in zip(records, tokens[1:], strict=True):
                    if (
                        record["primary_image_sha256"]
                        != record["frozen_primary_image_sha256"]
                    ):
                        raise ContractError(
                            "multiscale causal injected image replay failed"
                        )
                    vq = _vq_metrics(
                        clean_tokens,
                        injected_tokens,
                        centroids=centroids,
                        device=torch_device,
                        top_k=top_k,
                    )
                    score_delta = abs(
                        vq["injected_primary_score"]
                        - float(record["frozen_primary_score"])
                    )
                    clean_score_delta = abs(
                        vq["clean_primary_score"]
                        - float(frozen_clean["scores"]["primary_32"])
                    )
                    if score_delta > tolerance or clean_score_delta > tolerance:
                        raise ContractError("multiscale causal score replay failed")
                    threshold_margin = vq["injected_primary_score"] - float(
                        record["frozen_primary_threshold"]
                    )
                    recovered = threshold_margin > 0.0
                    if recovered != bool(record["frozen_primary_recovered"]):
                        raise ContractError("multiscale causal endpoint replay failed")
                    metrics = {
                        **record.pop("pre_embedding"),
                        **vq,
                        "threshold_margin": threshold_margin,
                    }
                    completed_rows.append(
                        {
                            **record,
                            "metrics": metrics,
                            "recovered": recovered,
                            "replay": {
                                "injected_score_absolute_delta": score_delta,
                                "clean_score_absolute_delta": clean_score_delta,
                                "score_absolute_tolerance": tolerance,
                            },
                        }
                    )
                chunk_body = {
                    "schema_version": SCHEMA_VERSION,
                    "status": "PASS_MULTISCALE_EFFICIENCY_V2_CAUSAL_CHUNK",
                    "contract_digest": contract["contract_digest"],
                    "clean_replay": clean_replay,
                    "rows": completed_rows,
                }
                _atomic_json(
                    _chunk_path(run_dir, row),
                    {
                        **chunk_body,
                        "artifact_digest": canonical_json_sha256(chunk_body),
                    },
                )
                completed += len(completed_rows)
                _update_progress(
                    progress_path,
                    stage=f"trace:{row['role']}:{row['detector']}",
                    completed=completed,
                    total=total,
                    started=started,
                )

        all_rows: list[dict[str, Any]] = []
        for row in selected:
            frozen_for_row = _frozen_trials_for_row(
                row, frozen_trials=trial_lookup, contract=contract
            )
            expected_ids = [
                _diagnostic_trial_id(contract["contract_digest"], item["trial_id"])
                for key, item in frozen_for_row.items()
                if not key.startswith("__")
            ]
            all_rows.extend(_verified_chunk(_chunk_path(run_dir, row), expected_ids))
        if (
            len(all_rows) != total
            or len({row["diagnostic_trial_id"] for row in all_rows}) != total
        ):
            raise ContractError("multiscale causal final cardinality changed")
        ledger_path = run_dir / "causal_trace_rows.jsonl"
        _atomic_jsonl(ledger_path, all_rows)
        cell_rows = summarize_diagnostic_rows(all_rows, contract)
        cells_path = run_dir / "causal_trace_cells.jsonl"
        _atomic_jsonl(cells_path, cell_rows)
        maximum_score_delta = max(
            max(
                float(row["replay"]["injected_score_absolute_delta"]),
                float(row["replay"]["clean_score_absolute_delta"]),
            )
            for row in all_rows
        )
        summary_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_MULTISCALE_EFFICIENCY_V2_CAUSAL_DIAGNOSTIC",
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "injection_run_key": injection_summary["run_key"],
            "injection_artifact_digest": injection_summary["artifact_digest"],
            "runtime": runtime,
            "selected_clean_controls": len(selected),
            "trace_rows": {
                "filename": ledger_path.name,
                "row_total": len(all_rows),
                "sha256": sha256_file(ledger_path),
            },
            "trace_cells": {
                "filename": cells_path.name,
                "row_total": len(cell_rows),
                "sha256": sha256_file(cells_path),
            },
            "replay": {
                "maximum_score_absolute_delta": maximum_score_delta,
                "score_absolute_tolerance": tolerance,
                "all_primary_image_hashes_match": True,
                "all_endpoints_match": True,
            },
            "scientific_boundary": {
                "outcome_blind_selection": True,
                "production_outputs_changed": False,
                "index_changed": False,
                "thresholds_changed": False,
                "populations_changed": False,
                "automatic_causal_label_assigned": False,
                "detectors_pooled": False,
                "morphologies_pooled": False,
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
        return verify_causal_diagnostic(run_dir=run_dir, root=root), run_dir
    except BaseException as exc:
        _atomic_json(
            failure_path,
            {
                "status": "FAILED_MULTISCALE_EFFICIENCY_V2_CAUSAL_DIAGNOSTIC",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "run_key": run_key,
            },
        )
        raise


def verify_causal_diagnostic(*, run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    contract = load_causal_contract(root.resolve())
    summary_path = run_dir / "causal_summary.json"
    if (run_dir / "failure.json").is_file():
        raise ContractError("multiscale causal failure artifact is present")
    if not summary_path.is_file():
        raise ContractError("multiscale causal summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("multiscale causal artifact digest mismatch")
    expected_run_key = _run_key(
        contract_digest=contract["contract_digest"],
        injection_artifact_digest=contract["frozen_input"]["artifact_digest"],
        runtime_environment_digest=str(
            summary.get("runtime", {}).get("environment_digest", "")
        ),
    )
    expected_rows = 1200
    expected_cells = 2 * 5 * 6
    if (
        summary.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_CAUSAL_DIAGNOSTIC"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"causal_{expected_run_key}"
        or int(summary.get("selected_clean_controls", -1)) != 80
        or int(summary.get("trace_rows", {}).get("row_total", -1)) != expected_rows
        or int(summary.get("trace_cells", {}).get("row_total", -1)) != expected_cells
    ):
        raise ContractError("multiscale causal run identity or cardinality changed")
    for key in ("trace_rows", "trace_cells"):
        entry = summary[key]
        path = run_dir / entry["filename"]
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ContractError(f"multiscale causal {key} hash mismatch")
        if len(_read_jsonl(path)) != int(entry["row_total"]):
            raise ContractError(f"multiscale causal {key} cardinality mismatch")
    replay = summary["replay"]
    if (
        float(replay["maximum_score_absolute_delta"])
        > float(replay["score_absolute_tolerance"])
        or replay["all_primary_image_hashes_match"] is not True
        or replay["all_endpoints_match"] is not True
    ):
        raise ContractError("multiscale causal replay gate failed")
    boundary = summary["scientific_boundary"]
    if any(
        boundary[key] is not False
        for key in (
            "production_outputs_changed",
            "index_changed",
            "thresholds_changed",
            "populations_changed",
            "automatic_causal_label_assigned",
            "detectors_pooled",
            "morphologies_pooled",
        )
    ):
        raise ContractError("multiscale causal scientific boundary failed")
    return summary


__all__ = [
    "CAUSAL_CONTRACT_REL",
    "load_causal_contract",
    "paired_block_bootstrap",
    "run_causal_diagnostic",
    "select_diagnostic_rows",
    "summarize_diagnostic_rows",
    "validate_causal_contract",
    "verify_causal_diagnostic",
]
