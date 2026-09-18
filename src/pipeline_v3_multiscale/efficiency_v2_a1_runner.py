"""Frozen joint-null and held-out runner for multiscale efficiency A1.

The A1 statistic is the maximum endpoint surprise across the detector-native
32 s endpoint and the four detector/scale-specific short endpoints.  Its p99
is calibrated from a joint background population, so scale multiplicity is
inside the null rather than handled by a naive OR.  Production remains
unchanged regardless of the confirmatory outcome.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import (
    ROOT,
    _atomic_json,
    _atomic_jsonl,
    _read_jsonl,
    load_contract,
    sha256_file,
    verify_cohort,
)
from src.pipeline_v3_multiscale.efficiency_v2_a1_cohort import verify_a1_cohort
from src.pipeline_v3_multiscale.efficiency_v2_causal import _render_primary_stages
from src.pipeline_v3_multiscale.efficiency_v2_reference import (
    SCALE_LABELS,
    _encode_images,
    _read_raw_context,
    _runtime_identity,
    _score_tokens,
    raw_block_bootstrap_p99,
    verify_raw_sources,
    verify_reference,
)
from src.pipeline_v3_multiscale.efficiency_v2_runner import (
    _load_reference_inputs,
    _preprocess_clean_task,
    _preprocess_morphology_task,
    _score_image_groups,
    load_runner_contract,
)

A1_CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2_a1.json")
SCHEMA_VERSION = 1
ENDPOINT_LABELS = ("primary_32", *SCALE_LABELS)
PASS_CI = "PASS_PAIRED_RAW_BLOCK_BOOTSTRAP_CI"
BOUNDARY_CI = "DEGENERATE_EMPIRICAL_BOUNDARY"


def _environment_path(reference: Mapping[str, Any]) -> Path:
    key = "windows" if os.name == "nt" else "wsl"
    return Path(reference["path_by_environment"][key])


def _assert_file_reference(
    root: Path, reference: Mapping[str, Any], label: str
) -> None:
    path = root / str(reference.get("path", ""))
    if not path.is_file() or sha256_file(path) != str(reference.get("sha256", "")):
        raise ContractError(f"A1 {label} mismatch")


def _assert_external_reference(reference: Mapping[str, Any], label: str) -> Path:
    path = _environment_path(reference)
    if not path.is_file() or sha256_file(path) != str(reference.get("sha256", "")):
        raise ContractError(f"A1 external {label} mismatch")
    return path


def validate_a1_contract(
    payload: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("A1 contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported A1 schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2-a1":
        raise ContractError("A1 contract id changed")
    if value.get("status") != "APPROVED_CONFIRMATORY_JOINT_NULL_INPUT":
        raise ContractError("A1 is not approved")
    if value.get("authorization") != {
        "authorized_on": "2026-09-18",
        "decision": (
            "calibrate a detector-specific joint empirical max-null over "
            "32, 0.5, 1, 2, and 4 second endpoints, then evaluate the frozen "
            "raw-block-disjoint A1 held-out cohort without automatic production "
            "promotion"
        ),
    }:
        raise ContractError("A1 authorization changed")

    root = root.resolve()
    for label in ("parent_contract", "runner_contract", "reference_contract"):
        _assert_file_reference(root, value[label], label)
    for label, reference in value.get("references", {}).items():
        _assert_file_reference(root, reference, label)
    external_inputs = value.get("external_inputs", {})
    for label in ("reference_summary", "exploratory_cohort_summary"):
        _assert_external_reference(external_inputs[label], label)

    cohort = value.get("heldout_cohort", {})
    summary_path = _assert_external_reference(cohort["summary"], "heldout summary")
    ledger_path = _assert_external_reference(cohort["ledger"], "heldout ledger")
    summary = verify_a1_cohort(run_dir=summary_path.parent, root=root)
    if (
        summary["run_key"] != cohort["run_key"]
        or summary["artifact_digest"] != cohort["artifact_digest"]
        or summary["ledger"]["sha256"] != sha256_file(ledger_path)
    ):
        raise ContractError("A1 held-out cohort identity changed")

    statistic = value.get("joint_statistic", {})
    if statistic != {
        "endpoints": ["primary_32", "0.5", "1", "2", "4"],
        "marginal_transform": "empirical_upper_tail_probability",
        "calibration_probability": "count_greater_or_equal_divided_by_n",
        "heldout_probability": "one_plus_count_greater_or_equal_divided_by_n_plus_one",
        "combination": "maximum_negative_log10_tail_probability",
        "detector_specific": True,
        "joint_null_preserves_cross_scale_dependence": True,
        "naive_scale_or_allowed": False,
    }:
        raise ContractError("approved A1 joint statistic changed")

    calibration = value.get("joint_null_calibration", {})
    if calibration != {
        "source_role": "short_scale_calibration",
        "rows_per_detector": 5000,
        "existing_short_scores_reused_by_hash": True,
        "primary_32_score_replayed": True,
        "candidate_or_injection_scores_used": False,
        "percentile": 99.0,
        "bootstrap_unit": "raw_source_block",
        "bootstrap_resamples": 2000,
        "bootstrap_confidence": 0.95,
        "bootstrap_seed": 42,
        "point_threshold_used_for_heldout_decision": True,
    }:
        raise ContractError("approved A1 joint-null calibration changed")

    waveform = value.get("waveform", {})
    if waveform != {
        "duration_s_by_morphology": {
            "Blip": 1.0,
            "NarrowChirp": 1.0,
            "Whistle": 1.0,
            "KoiFish": 1.0,
            "ScatteredLight": 2.0,
            "NoiseBlob": 4.0,
            "HarmonicComb": 4.0,
            "WallOfLines": 4.0,
        },
        "injection_alignment": "center_of_32s_analysis_window",
        "injection_domain": "raw_strain_before_whitening",
        "snr_reference": "paired_clean_raw_32s_window",
        "seed_algorithm": (
            "sha256(contract+detector+raw_block+morphology+identity)_uint32_be"
        ),
    }:
        raise ContractError("approved A1 waveform reconstruction changed")

    confirmation = value.get("heldout_confirmation", {})
    if confirmation != {
        "background_blocks_per_detector": 1000,
        "primary_blocks_per_detector": 100,
        "secondary_blocks_per_detector": 40,
        "roles": {
            "heldout_primary_injection": {
                "morphologies": [
                    "Blip",
                    "NarrowChirp",
                    "Whistle",
                    "ScatteredLight",
                    "NoiseBlob",
                ],
            },
            "heldout_secondary_control": {
                "morphologies": ["HarmonicComb", "WallOfLines", "KoiFish"],
            },
        },
        "target_snr": [8, 12, 16, 24, 32, 48],
        "confirmatory_morphologies": ["Blip", "Whistle"],
        "confirmatory_statistic": "paired_mean_recovery_gain_across_snr_grid",
        "paired_sign_flip_resamples": 2000,
        "shared_sign_flips_within_detector": True,
        "hypothesis_family": "detector_cross_confirmatory_morphology",
        "hypothesis_correction": "holm",
        "familywise_alpha": 0.05,
        "background_nominal_fpr": 0.01,
        "background_test": "one_sided_exact_binomial_greater",
        "background_hypothesis_correction": "holm_across_detectors",
        "other_morphologies_are_descriptive": True,
        "automatic_production_promotion": False,
    }:
        raise ContractError("approved A1 held-out confirmation changed")

    uncertainty = value.get("uncertainty", {})
    if uncertainty != {
        "method": "paired_detector_raw_source_block_bootstrap",
        "resamples": 2000,
        "confidence": 0.95,
        "seed": 42,
        "iid_bootstrap_allowed": False,
        "detectors_pooled": False,
        "morphologies_pooled": False,
    }:
        raise ContractError("approved A1 uncertainty changed")
    boundary = value.get("scientific_boundary", {})
    if (
        boundary.get("production_endpoint_changed") is not False
        or boundary.get("automatic_endpoint_promotion") is not False
        or boundary.get("global_detection_significance_established") is not False
        or boundary.get("O3_transfer_validity_established") is not False
    ):
        raise ContractError("A1 scientific boundary changed")
    return value


def load_a1_contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    return validate_a1_contract(
        json.loads((root / A1_CONTRACT_REL).read_text(encoding="utf-8")), root=root
    )


def empirical_tail_probability(
    value: float, calibration_scores: Sequence[float], *, heldout: bool
) -> float:
    scores = np.asarray(calibration_scores, dtype=np.float64)
    if scores.ndim != 1 or scores.size == 0 or np.any(~np.isfinite(scores)):
        raise ContractError("A1 empirical tail calibration is invalid")
    if not math.isfinite(float(value)):
        raise ContractError("A1 score is non-finite")
    if np.any(scores[1:] < scores[:-1]):
        raise ContractError("A1 empirical tail calibration must be sorted")
    count = int(scores.size - np.searchsorted(scores, value, side="left"))
    if heldout:
        return float((count + 1) / (scores.size + 1))
    if count <= 0:
        raise ContractError("A1 calibration self-rank is empty")
    return float(count / scores.size)


def joint_surprise(
    scores: Mapping[str, float],
    calibration_by_endpoint: Mapping[str, Sequence[float]],
    *,
    heldout: bool,
) -> tuple[float, dict[str, float]]:
    probabilities = {
        endpoint: empirical_tail_probability(
            float(scores[endpoint]),
            calibration_by_endpoint[endpoint],
            heldout=heldout,
        )
        for endpoint in ENDPOINT_LABELS
    }
    surprise = max(-math.log10(value) for value in probabilities.values())
    return float(surprise), probabilities


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    if not p_values:
        raise ContractError("A1 Holm family is empty")
    ordered = sorted((float(value), key) for key, value in p_values.items())
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (value, key) in enumerate(ordered):
        if value < 0 or value > 1 or not math.isfinite(value):
            raise ContractError("A1 p-value is invalid")
        running = max(running, min(1.0, (count - index) * value))
        adjusted[key] = running
    return adjusted


def _percentile_interval(values: np.ndarray, confidence: float) -> list[float]:
    alpha = (1.0 - confidence) / 2.0
    lower, upper = np.quantile(values, [alpha, 1.0 - alpha], method="linear")
    return [float(lower), float(upper)]


def paired_gain_statistic(
    differences: Sequence[float],
    draws: np.ndarray,
    *,
    confidence: float,
) -> dict[str, Any]:
    values = np.asarray(differences, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or np.any(~np.isfinite(values)):
        raise ContractError("A1 paired differences are invalid")
    point = float(values.mean())
    if np.all(values == values[0]):
        return {
            "mean_gain": point,
            "confidence_interval_95": None,
            "bootstrap_replicates": 0,
            "status": BOUNDARY_CI,
        }
    boot = values[draws].mean(axis=1)
    return {
        "mean_gain": point,
        "confidence_interval_95": _percentile_interval(boot, confidence),
        "bootstrap_replicates": int(draws.shape[0]),
        "status": PASS_CI,
    }


def paired_sign_flip_pvalue(differences: Sequence[float], signs: np.ndarray) -> float:
    values = np.asarray(differences, dtype=np.float64)
    if values.ndim != 1 or values.size == 0 or signs.shape[1] != values.size:
        raise ContractError("A1 sign-flip inputs are invalid")
    observed = float(values.mean())
    permuted = (signs * values[None, :]).mean(axis=1)
    return float((1 + np.sum(permuted >= observed)) / (signs.shape[0] + 1))


def _preprocess_primary_only(
    arguments: tuple[Mapping[str, Any], str, Mapping[str, Any]],
) -> tuple[np.ndarray, dict[str, Any]]:
    row, raw_root_value, parent = arguments
    sample_rate = int(parent["preprocessing"]["sample_rate_hz"])
    raw_series, raw_values = _read_raw_context(
        row, raw_root=Path(raw_root_value), sample_rate_hz=sample_rate
    )
    _, _, _, image, replay = _render_primary_stages(
        raw_series, gps_start=float(row["gps_start"]), parent=parent
    )
    if replay["primary_image_sha256"] != row["expected_clean_image_sha256"]:
        raise ContractError("A1 calibration primary image hash mismatch")
    return image, {
        "detector": str(row["detector"]),
        "role_index": int(row["role_index"]),
        "identity_digest": str(row["identity_digest"]),
        "raw_source_sha256": str(row["raw_block"]["source_sha256"]),
        "raw_context_sha256": hashlib.sha256(raw_values.tobytes()).hexdigest(),
        **replay,
    }


def _chunk_payload(
    path: Path,
    expected_ids: Sequence[str],
    *,
    expected_status: str,
    contract_digest: str,
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"A1 chunk digest mismatch: {path}")
    if (
        payload.get("status") != expected_status
        or payload.get("contract_digest") != contract_digest
    ):
        raise ContractError(f"A1 chunk contract mismatch: {path}")
    rows = payload.get("rows", [])
    if [str(row["identity_digest"]) for row in rows] != list(expected_ids):
        raise ContractError(f"A1 chunk identity mismatch: {path}")
    return rows


def _write_chunk(
    path: Path,
    *,
    status: str,
    contract_digest: str,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "contract_digest": contract_digest,
        "rows": list(rows),
    }
    _atomic_json(path, {**body, "artifact_digest": canonical_json_sha256(body)})


def _update_progress(
    path: Path, *, stage: str, completed: int, total: int, started: float
) -> None:
    elapsed = max(0.0, time.monotonic() - started)
    rate = completed / elapsed if elapsed else 0.0
    _atomic_json(
        path,
        {
            "stage": stage,
            "completed": completed,
            "total": total,
            "fraction": completed / total if total else 1.0,
            "elapsed_seconds": elapsed,
            "estimated_remaining_seconds": (total - completed) / rate if rate else None,
        },
    )


def _joint_null_run_key(
    contract_digest: str, runtime_digest: str, reference_artifact: str
) -> str:
    return canonical_json_sha256(
        {
            "stage": "multiscale_efficiency_v2_a1_joint_null",
            "contract_digest": contract_digest,
            "runtime_environment_digest": runtime_digest,
            "reference_artifact_digest": reference_artifact,
        }
    )


def _heldout_run_key(
    contract_digest: str,
    runtime_digest: str,
    cohort_artifact: str,
    joint_null_artifact: str,
) -> str:
    return canonical_json_sha256(
        {
            "stage": "multiscale_efficiency_v2_a1_heldout",
            "contract_digest": contract_digest,
            "runtime_environment_digest": runtime_digest,
            "cohort_artifact_digest": cohort_artifact,
            "joint_null_artifact_digest": joint_null_artifact,
        }
    )


def _load_exploratory_calibration(
    contract: Mapping[str, Any], *, root: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    reference_input = contract["external_inputs"]["reference_summary"]
    reference_dir = _environment_path(reference_input).parent
    reference = verify_reference(run_dir=reference_dir, root=root)
    if reference["artifact_digest"] != reference_input["artifact_digest"]:
        raise ContractError("A1 reference artifact changed")
    calibration_path = reference_dir / reference["calibration"]["filename"]
    stored = _read_jsonl(calibration_path)
    cohort_input = contract["external_inputs"]["exploratory_cohort_summary"]
    cohort_dir = _environment_path(cohort_input).parent
    cohort = verify_cohort(run_dir=cohort_dir, root=root)
    if cohort["artifact_digest"] != cohort_input["artifact_digest"]:
        raise ContractError("A1 exploratory cohort artifact changed")
    rows = _read_jsonl(cohort_dir / cohort["ledger"]["filename"])
    calibration_rows = [row for row in rows if row["role"] == "short_scale_calibration"]
    by_identity = {str(row["identity_digest"]): row for row in stored}
    if len(calibration_rows) != 10000 or len(by_identity) != 10000:
        raise ContractError("A1 joint-null calibration cardinality changed")
    if any(str(row["identity_digest"]) not in by_identity for row in calibration_rows):
        raise ContractError("A1 short-scale calibration identity mismatch")
    return calibration_rows, stored, reference


def run_joint_null(
    *,
    raw_root: Path,
    output_root: Path,
    device: str = "cuda",
    workers: int = 8,
    encoder_batch: int = 32,
    root: Path = ROOT,
) -> tuple[dict[str, Any], Path]:
    import multiprocessing as mp

    import torch

    from src.core.encoder import build_dinov2_transform
    from src.core.model_loader import load_dinov2_model

    root = root.resolve()
    contract = load_a1_contract(root)
    parent = load_contract(root)
    runner = load_runner_contract(root)
    calibration_rows, short_rows, reference = _load_exploratory_calibration(
        contract, root=root
    )
    verify_raw_sources(calibration_rows, raw_root=raw_root, workers=workers)
    torch_device = torch.device(device)
    model = load_dinov2_model(torch_device, allow_download=False)
    transform = build_dinov2_transform(
        int(parent["representation"]["encoder_input_size"])
    )
    runtime = _runtime_identity(device=device, model=model)
    run_key = _joint_null_run_key(
        contract["contract_digest"],
        runtime["environment_digest"],
        reference["artifact_digest"],
    )
    run_dir = output_root.resolve() / f"joint_null_{run_key}"
    summary_path = run_dir / "joint_null_summary.json"
    if summary_path.is_file():
        return verify_joint_null(run_dir=run_dir, root=root), run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("previous A1 joint-null failure must be preserved")
    progress_path = run_dir / "progress.json"
    started = time.monotonic()
    try:
        native, _, _ = _load_reference_inputs(
            runner=runner,
            reference_run_dir=_environment_path(
                contract["external_inputs"]["reference_summary"]
            ).parent,
            device=torch_device,
            root=root,
        )
        short_by_identity = {str(row["identity_digest"]): row for row in short_rows}
        context = mp.get_context("spawn")
        completed = 0
        chunk_size = int(contract["execution"]["calibration_chunk_rows"])
        all_rows: list[dict[str, Any]] = []
        executor = ProcessPoolExecutor(max_workers=workers, mp_context=context)
        for detector in ("H1", "L1"):
            detector_rows = [
                row for row in calibration_rows if row["detector"] == detector
            ]
            for start in range(0, len(detector_rows), chunk_size):
                batch_rows = detector_rows[start : start + chunk_size]
                chunk_path = (
                    run_dir / "chunks" / detector / f"{start // chunk_size:04d}.json"
                )
                expected_ids = [str(row["identity_digest"]) for row in batch_rows]
                if chunk_path.is_file():
                    records = _chunk_payload(
                        chunk_path,
                        expected_ids,
                        expected_status=("PASS_MULTISCALE_EFFICIENCY_V2_A1_NULL_CHUNK"),
                        contract_digest=contract["contract_digest"],
                    )
                else:
                    arguments = [
                        (row, str(raw_root.resolve()), parent) for row in batch_rows
                    ]
                    preprocessed = list(
                        executor.map(_preprocess_primary_only, arguments)
                    )
                    images = [item[0] for item in preprocessed]
                    tokens = np.concatenate(
                        [
                            _encode_images(
                                images[start : start + encoder_batch],
                                model=model,
                                transform=transform,
                                device=torch_device,
                            )
                            for start in range(0, len(images), encoder_batch)
                        ],
                        axis=0,
                    )
                    scores = _score_tokens(
                        torch.from_numpy(tokens).to(torch_device),
                        native,
                        int(parent["representation"]["discovery"]["top_k"]),
                    )
                    records = []
                    for row, (_, replay), primary_score in zip(
                        batch_rows, preprocessed, scores, strict=True
                    ):
                        short = short_by_identity[str(row["identity_digest"])]
                        records.append(
                            {
                                **replay,
                                "scores": {
                                    "primary_32": float(primary_score),
                                    **{
                                        label: float(short["score_by_scale"][label])
                                        for label in SCALE_LABELS
                                    },
                                },
                            }
                        )
                    _write_chunk(
                        chunk_path,
                        status="PASS_MULTISCALE_EFFICIENCY_V2_A1_NULL_CHUNK",
                        contract_digest=contract["contract_digest"],
                        rows=records,
                    )
                all_rows.extend(records)
                completed += len(batch_rows)
                _update_progress(
                    progress_path,
                    stage=f"joint-null:{detector}",
                    completed=completed,
                    total=len(calibration_rows),
                    started=started,
                )
        executor.shutdown(wait=True)

        calibration_lookup: dict[str, dict[str, np.ndarray]] = {}
        enriched: list[dict[str, Any]] = []
        thresholds: dict[str, Any] = {}
        spec = contract["joint_null_calibration"]
        for detector in ("H1", "L1"):
            detector_rows = [row for row in all_rows if row["detector"] == detector]
            calibration_lookup[detector] = {
                endpoint: np.sort(
                    np.asarray(
                        [float(row["scores"][endpoint]) for row in detector_rows]
                    )
                )
                for endpoint in ENDPOINT_LABELS
            }
            detector_enriched = []
            for row in detector_rows:
                statistic, probabilities = joint_surprise(
                    row["scores"], calibration_lookup[detector], heldout=False
                )
                detector_enriched.append(
                    {
                        **row,
                        "tail_probability_by_endpoint": probabilities,
                        "joint_surprise": statistic,
                    }
                )
            enriched.extend(detector_enriched)
            thresholds[detector] = raw_block_bootstrap_p99(
                [row["joint_surprise"] for row in detector_enriched],
                [row["raw_source_sha256"] for row in detector_enriched],
                n_resamples=int(spec["bootstrap_resamples"]),
                seed=int(spec["bootstrap_seed"]),
                confidence=float(spec["bootstrap_confidence"]),
                percentile=float(spec["percentile"]),
            )
        enriched.sort(key=lambda row: (row["detector"], row["role_index"]))
        ledger_path = run_dir / "joint_null_calibration.jsonl"
        threshold_path = run_dir / "joint_null_thresholds.json"
        _atomic_jsonl(ledger_path, enriched)
        threshold_body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_MULTISCALE_EFFICIENCY_V2_A1_JOINT_THRESHOLDS",
            "contract_digest": contract["contract_digest"],
            "thresholds": thresholds,
        }
        _atomic_json(
            threshold_path,
            {
                **threshold_body,
                "artifact_digest": canonical_json_sha256(threshold_body),
            },
        )
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_MULTISCALE_EFFICIENCY_V2_A1_JOINT_NULL",
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "reference_artifact_digest": reference["artifact_digest"],
            "runtime": runtime,
            "calibration": {
                "filename": ledger_path.name,
                "row_total": len(enriched),
                "sha256": sha256_file(ledger_path),
            },
            "thresholds": {
                "filename": threshold_path.name,
                "sha256": sha256_file(threshold_path),
            },
            "scientific_boundary": {
                "candidate_or_injection_scores_used": False,
                "detectors_pooled": False,
                "scale_dependence_preserved": True,
                "production_endpoint_changed": False,
            },
        }
        _atomic_json(
            summary_path, {**body, "artifact_digest": canonical_json_sha256(body)}
        )
        _update_progress(
            progress_path,
            stage="complete",
            completed=len(calibration_rows),
            total=len(calibration_rows),
            started=started,
        )
        return verify_joint_null(run_dir=run_dir, root=root), run_dir
    except BaseException as exc:
        _atomic_json(
            failure_path,
            {
                "status": "FAILED_MULTISCALE_EFFICIENCY_V2_A1_JOINT_NULL",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "run_key": run_key,
            },
        )
        raise


def verify_joint_null(*, run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    contract = load_a1_contract(root)
    summary_path = run_dir / "joint_null_summary.json"
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("A1 joint-null failure artifact is present")
    if not summary_path.is_file():
        raise ContractError("A1 joint-null summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("A1 joint-null artifact digest mismatch")
    expected_run_key = _joint_null_run_key(
        contract["contract_digest"],
        summary["runtime"]["environment_digest"],
        summary["reference_artifact_digest"],
    )
    if (
        summary.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_A1_JOINT_NULL"
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"joint_null_{expected_run_key}"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("reference_artifact_digest")
        != contract["external_inputs"]["reference_summary"]["artifact_digest"]
    ):
        raise ContractError("A1 joint-null identity changed")
    ledger_path = run_dir / summary["calibration"]["filename"]
    threshold_path = run_dir / summary["thresholds"]["filename"]
    for path, entry in (
        (ledger_path, summary["calibration"]),
        (threshold_path, summary["thresholds"]),
    ):
        if not path.is_file() or sha256_file(path) != entry["sha256"]:
            raise ContractError(f"A1 joint-null output mismatch: {path.name}")
    rows = _read_jsonl(ledger_path)
    expected_rows = 2 * int(contract["joint_null_calibration"]["rows_per_detector"])
    if (
        len(rows) != expected_rows
        or summary["calibration"]["row_total"] != expected_rows
        or len({row["identity_digest"] for row in rows}) != expected_rows
    ):
        raise ContractError("A1 joint-null ledger cardinality changed")
    thresholds = json.loads(threshold_path.read_text(encoding="utf-8"))
    threshold_body = dict(thresholds)
    threshold_digest = threshold_body.pop("artifact_digest", None)
    if (
        threshold_digest != canonical_json_sha256(threshold_body)
        or thresholds.get("status")
        != "PASS_MULTISCALE_EFFICIENCY_V2_A1_JOINT_THRESHOLDS"
        or thresholds.get("contract_digest") != contract["contract_digest"]
    ):
        raise ContractError("A1 joint threshold artifact digest mismatch")
    spec = contract["joint_null_calibration"]
    for detector in ("H1", "L1"):
        detector_rows = [row for row in rows if row["detector"] == detector]
        if len(detector_rows) != int(
            contract["joint_null_calibration"]["rows_per_detector"]
        ):
            raise ContractError("A1 detector calibration cardinality changed")
        lookup = {
            endpoint: sorted(float(row["scores"][endpoint]) for row in detector_rows)
            for endpoint in ENDPOINT_LABELS
        }
        replay = [
            joint_surprise(row["scores"], lookup, heldout=False)
            for row in detector_rows
        ]
        expected_statistics = [item[0] for item in replay]
        if not np.allclose(
            expected_statistics,
            [float(row["joint_surprise"]) for row in detector_rows],
            rtol=0,
            atol=0,
        ):
            raise ContractError("A1 joint statistic replay mismatch")
        if [item[1] for item in replay] != [
            row["tail_probability_by_endpoint"] for row in detector_rows
        ]:
            raise ContractError("A1 marginal probability replay mismatch")
        expected_threshold = raw_block_bootstrap_p99(
            expected_statistics,
            [row["raw_source_sha256"] for row in detector_rows],
            n_resamples=int(spec["bootstrap_resamples"]),
            seed=int(spec["bootstrap_seed"]),
            confidence=float(spec["bootstrap_confidence"]),
            percentile=float(spec["percentile"]),
        )
        if thresholds["thresholds"][detector] != expected_threshold:
            raise ContractError("A1 joint threshold replay mismatch")
    return summary


def _load_joint_null(
    run_dir: Path, *, root: Path
) -> tuple[dict[str, Any], dict[str, dict[str, np.ndarray]], dict[str, float]]:
    summary = verify_joint_null(run_dir=run_dir, root=root)
    rows = _read_jsonl(run_dir / summary["calibration"]["filename"])
    thresholds_payload = json.loads(
        (run_dir / summary["thresholds"]["filename"]).read_text(encoding="utf-8")
    )
    lookup = {
        detector: {
            endpoint: np.sort(
                np.asarray(
                    [
                        float(row["scores"][endpoint])
                        for row in rows
                        if row["detector"] == detector
                    ]
                )
            )
            for endpoint in ENDPOINT_LABELS
        }
        for detector in ("H1", "L1")
    }
    thresholds = {
        detector: float(thresholds_payload["thresholds"][detector]["point_p99"])
        for detector in ("H1", "L1")
    }
    return summary, lookup, thresholds


def _classify_scores(
    scores: Mapping[str, float],
    *,
    calibration: Mapping[str, Sequence[float]],
    joint_threshold: float,
    baseline_threshold: float,
) -> dict[str, Any]:
    statistic, probabilities = joint_surprise(scores, calibration, heldout=True)
    return {
        "scores": {label: float(scores[label]) for label in ENDPOINT_LABELS},
        "tail_probability_by_endpoint": probabilities,
        "joint_surprise": statistic,
        "joint_threshold": float(joint_threshold),
        "a1_recovered": statistic > float(joint_threshold),
        "baseline_32_threshold": float(baseline_threshold),
        "baseline_32_recovered": float(scores["primary_32"])
        > float(baseline_threshold),
    }


def _heldout_clean_chunk(
    path: Path, expected_ids: Sequence[str], *, contract_digest: str
) -> list[dict[str, Any]]:
    return _chunk_payload(
        path,
        expected_ids,
        expected_status="PASS_MULTISCALE_EFFICIENCY_V2_A1_CLEAN_CHUNK",
        contract_digest=contract_digest,
    )


def _trial_chunk(
    path: Path, expected_ids: Sequence[str], *, contract_digest: str
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"A1 trial chunk digest mismatch: {path}")
    if (
        payload.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_A1_TRIAL_CHUNK"
        or payload.get("contract_digest") != contract_digest
    ):
        raise ContractError(f"A1 trial chunk contract mismatch: {path}")
    rows = payload.get("trials", [])
    if [str(row["trial_id"]) for row in rows] != list(expected_ids):
        raise ContractError(f"A1 trial chunk identities changed: {path}")
    return rows


def _trial_id(
    contract_digest: str,
    row: Mapping[str, Any],
    morphology: str,
    target_snr: float,
) -> str:
    return canonical_json_sha256(
        {
            "contract_digest": contract_digest,
            "role": str(row["role"]),
            "detector": str(row["detector"]),
            "identity_digest": str(row["identity_digest"]),
            "morphology": morphology,
            "target_snr": float(target_snr),
        }
    )


def _trial_chunk_path(run_dir: Path, row: Mapping[str, Any], morphology: str) -> Path:
    return (
        run_dir
        / "trial_chunks"
        / str(row["role"])
        / str(row["detector"])
        / f"{int(row['role_index']):04d}_{morphology}.json"
    )


def _expected_trial_ids(
    contract_digest: str,
    row: Mapping[str, Any],
    morphology: str,
    target_snrs: Sequence[float],
) -> list[str]:
    return [
        _trial_id(contract_digest, row, morphology, float(target_snr))
        for target_snr in target_snrs
    ]


def _expected_heldout_cardinalities(
    contract: Mapping[str, Any],
) -> tuple[int, int, int]:
    confirmation = contract["heldout_confirmation"]
    detector_count = 2
    snr_count = len(confirmation["target_snr"])
    primary_morphologies = len(
        confirmation["roles"]["heldout_primary_injection"]["morphologies"]
    )
    secondary_morphologies = len(
        confirmation["roles"]["heldout_secondary_control"]["morphologies"]
    )
    clean_total = detector_count * (
        int(confirmation["background_blocks_per_detector"])
        + int(confirmation["primary_blocks_per_detector"])
        + int(confirmation["secondary_blocks_per_detector"])
    )
    trial_total = (
        detector_count
        * snr_count
        * (
            int(confirmation["primary_blocks_per_detector"]) * primary_morphologies
            + int(confirmation["secondary_blocks_per_detector"])
            * secondary_morphologies
        )
    )
    cell_total = (
        detector_count * snr_count * (primary_morphologies + secondary_morphologies)
    )
    return clean_total, trial_total, cell_total


def _analyze_heldout(
    *,
    clean_rows: Sequence[Mapping[str, Any]],
    trial_rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    from scipy.stats import binomtest

    confirmation = contract["heldout_confirmation"]
    expected_clean, expected_trials, expected_cells = _expected_heldout_cardinalities(
        contract
    )
    if len(clean_rows) != expected_clean or len(trial_rows) != expected_trials:
        raise ContractError("A1 held-out analysis cardinality changed")
    clean_expected_by_role = {
        "heldout_background": int(confirmation["background_blocks_per_detector"]),
        "heldout_primary_injection": int(confirmation["primary_blocks_per_detector"]),
        "heldout_secondary_control": int(confirmation["secondary_blocks_per_detector"]),
    }
    for detector in ("H1", "L1"):
        for role, count in clean_expected_by_role.items():
            role_rows = [
                row
                for row in clean_rows
                if row["detector"] == detector and row["role"] == role
            ]
            if len(role_rows) != count or {
                int(row["role_index"]) for row in role_rows
            } != set(range(count)):
                raise ContractError("A1 held-out clean role cardinality changed")
    alpha = float(confirmation["familywise_alpha"])
    nominal = float(confirmation["background_nominal_fpr"])
    background: dict[str, Any] = {}
    raw_background_p: dict[str, float] = {}
    for detector in ("H1", "L1"):
        rows = [
            row
            for row in clean_rows
            if row["detector"] == detector and row["role"] == "heldout_background"
        ]
        if len(rows) != int(confirmation["background_blocks_per_detector"]):
            raise ContractError("A1 held-out background cardinality changed")
        count = sum(bool(row["endpoint"]["a1_recovered"]) for row in rows)
        baseline_count = sum(
            bool(row["endpoint"]["baseline_32_recovered"]) for row in rows
        )
        pvalue = float(
            binomtest(count, len(rows), nominal, alternative="greater").pvalue
        )
        raw_background_p[detector] = pvalue
        background[detector] = {
            "row_total": len(rows),
            "a1_exceeds": count,
            "a1_fpr": count / len(rows),
            "baseline_32_exceeds": baseline_count,
            "baseline_32_fpr": baseline_count / len(rows),
            "nominal_fpr": nominal,
            "one_sided_exact_binomial_pvalue": pvalue,
        }
    adjusted_background = holm_adjust(raw_background_p)
    for detector in ("H1", "L1"):
        background[detector]["holm_adjusted_pvalue"] = adjusted_background[detector]
        background[detector]["excess_fpr_detected"] = (
            adjusted_background[detector] < alpha
        )

    cells: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str, float], list[Mapping[str, Any]]] = defaultdict(
        list
    )
    for row in trial_rows:
        grouped[
            (
                str(row["detector"]),
                str(row["role"]),
                str(row["morphology"]),
                float(row["target_snr"]),
            )
        ].append(row)
    expected_group_keys = {
        (detector, role, morphology, float(target_snr))
        for detector in ("H1", "L1")
        for role, role_spec in confirmation["roles"].items()
        for morphology in role_spec["morphologies"]
        for target_snr in confirmation["target_snr"]
    }
    if set(grouped) != expected_group_keys:
        raise ContractError("A1 held-out trial cells changed")
    uncertainty = contract["uncertainty"]
    rng = np.random.default_rng(int(uncertainty["seed"]))
    for key, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda row: int(row["role_index"]))
        expected_count = (
            int(confirmation["primary_blocks_per_detector"])
            if key[1] == "heldout_primary_injection"
            else int(confirmation["secondary_blocks_per_detector"])
        )
        if len(rows) != expected_count or {
            int(row["role_index"]) for row in rows
        } != set(range(expected_count)):
            raise ContractError("A1 held-out trial cell cardinality changed")
        differences = np.asarray(
            [
                int(bool(row["endpoint"]["a1_recovered"]))
                - int(bool(row["endpoint"]["baseline_32_recovered"]))
                for row in rows
            ],
            dtype=np.float64,
        )
        draws = rng.integers(
            0,
            len(rows),
            size=(int(uncertainty["resamples"]), len(rows)),
        )
        cells.append(
            {
                "detector": key[0],
                "role": key[1],
                "morphology": key[2],
                "target_snr": key[3],
                "raw_source_block_count": len(rows),
                "a1_recovered": sum(
                    bool(row["endpoint"]["a1_recovered"]) for row in rows
                ),
                "baseline_32_recovered": sum(
                    bool(row["endpoint"]["baseline_32_recovered"]) for row in rows
                ),
                "paired_gain": paired_gain_statistic(
                    differences,
                    draws,
                    confidence=float(uncertainty["confidence"]),
                ),
            }
        )
    if len(cells) != expected_cells:
        raise ContractError("A1 held-out cell cardinality changed")

    confirmatory: dict[str, Any] = {}
    raw_confirmatory_p: dict[str, float] = {}
    sign_rng = np.random.default_rng(int(uncertainty["seed"]))
    signs_by_detector = {
        detector: sign_rng.choice(
            np.asarray([-1.0, 1.0]),
            size=(
                int(confirmation["paired_sign_flip_resamples"]),
                int(confirmation["primary_blocks_per_detector"]),
            ),
        )
        for detector in ("H1", "L1")
    }
    for detector in ("H1", "L1"):
        for morphology in confirmation["confirmatory_morphologies"]:
            rows = [
                row
                for row in trial_rows
                if row["detector"] == detector
                and row["role"] == "heldout_primary_injection"
                and row["morphology"] == morphology
            ]
            by_block: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
            for row in rows:
                by_block[int(row["role_index"])].append(row)
            differences = []
            for role_index in range(int(confirmation["primary_blocks_per_detector"])):
                block_rows = by_block[role_index]
                if len(block_rows) != len(confirmation["target_snr"]):
                    raise ContractError("A1 confirmatory SNR grid is incomplete")
                differences.append(
                    float(
                        np.mean(
                            [
                                int(bool(row["endpoint"]["a1_recovered"]))
                                - int(bool(row["endpoint"]["baseline_32_recovered"]))
                                for row in block_rows
                            ]
                        )
                    )
                )
            label = f"{detector}|{morphology}"
            pvalue = paired_sign_flip_pvalue(differences, signs_by_detector[detector])
            raw_confirmatory_p[label] = pvalue
            draws = rng.integers(
                0,
                len(differences),
                size=(int(uncertainty["resamples"]), len(differences)),
            )
            confirmatory[label] = {
                "detector": detector,
                "morphology": morphology,
                "raw_source_block_count": len(differences),
                "paired_curve_gain": paired_gain_statistic(
                    differences,
                    draws,
                    confidence=float(uncertainty["confidence"]),
                ),
                "one_sided_sign_flip_pvalue": pvalue,
            }
    adjusted_confirmatory = holm_adjust(raw_confirmatory_p)
    for label, row in confirmatory.items():
        adjusted = adjusted_confirmatory[label]
        row["holm_adjusted_pvalue"] = adjusted
        row["confirmatory_improvement"] = (
            adjusted < alpha and row["paired_curve_gain"]["mean_gain"] > 0
        )

    fpr_pass = not any(row["excess_fpr_detected"] for row in background.values())
    sensitivity_pass = all(
        row["confirmatory_improvement"] for row in confirmatory.values()
    )
    return {
        "background_fpr": background,
        "cells": cells,
        "confirmatory_hypotheses": confirmatory,
        "decision": {
            "background_no_significant_excess": fpr_pass,
            "all_confirmatory_improvements_pass": sensitivity_pass,
            "a1_confirmatory_status": (
                "PASS_A1_CONFIRMATORY_EVIDENCE"
                if fpr_pass and sensitivity_pass
                else "FAIL_A1_CONFIRMATORY_EVIDENCE"
            ),
            "automatic_production_promotion": False,
        },
    }


def run_heldout(
    *,
    joint_null_run_dir: Path,
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
    contract = load_a1_contract(root)
    parent = load_contract(root)
    runner = load_runner_contract(root)
    cohort_dir = _environment_path(contract["heldout_cohort"]["summary"]).parent
    cohort_summary = verify_a1_cohort(run_dir=cohort_dir, root=root)
    cohort_rows = _read_jsonl(cohort_dir / cohort_summary["ledger"]["filename"])
    joint_summary, calibration, joint_thresholds = _load_joint_null(
        joint_null_run_dir, root=root
    )
    verify_raw_sources(cohort_rows, raw_root=raw_root, workers=workers)
    torch_device = torch.device(device)
    model = load_dinov2_model(torch_device, allow_download=False)
    transform = build_dinov2_transform(
        int(parent["representation"]["encoder_input_size"])
    )
    runtime = _runtime_identity(device=device, model=model)
    run_key = _heldout_run_key(
        contract["contract_digest"],
        runtime["environment_digest"],
        cohort_summary["artifact_digest"],
        joint_summary["artifact_digest"],
    )
    run_dir = output_root.resolve() / f"heldout_{run_key}"
    summary_path = run_dir / "heldout_summary.json"
    if summary_path.is_file():
        return verify_heldout(
            run_dir=run_dir, joint_null_run_dir=joint_null_run_dir, root=root
        ), run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("previous A1 held-out failure must be preserved")
    progress_path = run_dir / "progress.json"
    started = time.monotonic()
    try:
        native, short, baseline_thresholds = _load_reference_inputs(
            runner=runner,
            reference_run_dir=_environment_path(
                contract["external_inputs"]["reference_summary"]
            ).parent,
            device=torch_device,
            root=root,
        )
        context = mp.get_context("spawn")
        chunk_size = int(contract["execution"]["heldout_clean_chunk_rows"])
        clean_records: list[dict[str, Any]] = []
        completed = 0
        expected_clean, total_trials, expected_cells = _expected_heldout_cardinalities(
            contract
        )
        if len(cohort_rows) != expected_clean:
            raise ContractError("A1 held-out cohort cardinality changed")
        total_work = len(cohort_rows) + total_trials
        clean_executor = ProcessPoolExecutor(max_workers=workers, mp_context=context)
        for detector in ("H1", "L1"):
            detector_rows = [row for row in cohort_rows if row["detector"] == detector]
            for start in range(0, len(detector_rows), chunk_size):
                batch_rows = detector_rows[start : start + chunk_size]
                chunk_path = (
                    run_dir
                    / "clean_chunks"
                    / detector
                    / f"{start // chunk_size:04d}.json"
                )
                expected_ids = [str(row["identity_digest"]) for row in batch_rows]
                if chunk_path.is_file():
                    records = _heldout_clean_chunk(
                        chunk_path,
                        expected_ids,
                        contract_digest=contract["contract_digest"],
                    )
                else:
                    arguments = [
                        (row, str(raw_root.resolve()), parent) for row in batch_rows
                    ]
                    preprocessed = list(
                        clean_executor.map(_preprocess_clean_task, arguments)
                    )
                    score_rows = _score_image_groups(
                        [item[0] for item in preprocessed],
                        model=model,
                        transform=transform,
                        device=torch_device,
                        native_centroids=native,
                        short_centroids=short[detector],
                        parent=parent,
                        encoder_batch=encoder_batch,
                    )
                    records = []
                    for row, (_, replay), scores in zip(
                        batch_rows, preprocessed, score_rows, strict=True
                    ):
                        records.append(
                            {
                                **replay,
                                "endpoint": _classify_scores(
                                    scores,
                                    calibration=calibration[detector],
                                    joint_threshold=joint_thresholds[detector],
                                    baseline_threshold=float(
                                        baseline_thresholds["primary"][detector]["p99"]
                                    ),
                                ),
                            }
                        )
                    _write_chunk(
                        chunk_path,
                        status="PASS_MULTISCALE_EFFICIENCY_V2_A1_CLEAN_CHUNK",
                        contract_digest=contract["contract_digest"],
                        rows=records,
                    )
                clean_records.extend(records)
                completed += len(batch_rows)
                _update_progress(
                    progress_path,
                    stage=f"heldout-clean:{detector}",
                    completed=completed,
                    total=total_work,
                    started=started,
                )
        clean_executor.shutdown(wait=True)

        roles = contract["heldout_confirmation"]["roles"]
        injection_rows = [row for row in cohort_rows if row["role"] in roles]
        tasks = []
        for row in injection_rows:
            role = roles[str(row["role"])]
            for morphology in role["morphologies"]:
                tasks.append(
                    (
                        row,
                        str(raw_root.resolve()),
                        parent,
                        morphology,
                        float(
                            contract["waveform"]["duration_s_by_morphology"][morphology]
                        ),
                        list(contract["heldout_confirmation"]["target_snr"]),
                        contract["contract_digest"],
                    )
                )
        clean_by_identity = {str(row["identity_digest"]): row for row in clean_records}
        pending_tasks = []
        for arguments in tasks:
            row, _, _, morphology, _, target_snrs, _ = arguments
            expected_ids = _expected_trial_ids(
                contract["contract_digest"], row, morphology, target_snrs
            )
            chunk_path = _trial_chunk_path(run_dir, row, morphology)
            if chunk_path.is_file():
                _trial_chunk(
                    chunk_path,
                    expected_ids,
                    contract_digest=contract["contract_digest"],
                )
                completed += len(expected_ids)
            else:
                pending_tasks.append(arguments)
        _update_progress(
            progress_path,
            stage="heldout-injections:resume-check",
            completed=completed,
            total=total_work,
            started=started,
        )
        with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
            results = executor.map(_preprocess_morphology_task, pending_tasks)
            for arguments, morphology_results in zip(
                pending_tasks, results, strict=True
            ):
                row = arguments[0]
                morphology = arguments[3]
                expected_ids = _expected_trial_ids(
                    contract["contract_digest"], row, morphology, arguments[5]
                )
                if [item[1]["trial_id"] for item in morphology_results] != expected_ids:
                    raise ContractError("A1 preprocessed trial identities changed")
                chunk_path = _trial_chunk_path(run_dir, row, morphology)
                score_rows = _score_image_groups(
                    [item[0] for item in morphology_results],
                    model=model,
                    transform=transform,
                    device=torch_device,
                    native_centroids=native,
                    short_centroids=short[str(row["detector"])],
                    parent=parent,
                    encoder_batch=encoder_batch,
                )
                detector = str(row["detector"])
                trial_records = []
                for (_, replay), scores in zip(
                    morphology_results, score_rows, strict=True
                ):
                    trial_records.append(
                        {
                            **replay,
                            "paired_clean_identity_digest": str(row["identity_digest"]),
                            "paired_clean_endpoint": clean_by_identity[
                                str(row["identity_digest"])
                            ]["endpoint"],
                            "endpoint": _classify_scores(
                                scores,
                                calibration=calibration[detector],
                                joint_threshold=joint_thresholds[detector],
                                baseline_threshold=float(
                                    baseline_thresholds["primary"][detector]["p99"]
                                ),
                            ),
                        }
                    )
                body = {
                    "schema_version": SCHEMA_VERSION,
                    "status": "PASS_MULTISCALE_EFFICIENCY_V2_A1_TRIAL_CHUNK",
                    "contract_digest": contract["contract_digest"],
                    "trials": trial_records,
                }
                _atomic_json(
                    chunk_path,
                    {**body, "artifact_digest": canonical_json_sha256(body)},
                )
                completed += len(expected_ids)
                _update_progress(
                    progress_path,
                    stage=f"heldout-injections:{row['detector']}:{row['role']}",
                    completed=completed,
                    total=total_work,
                    started=started,
                )

        all_trials: list[dict[str, Any]] = []
        for arguments in tasks:
            row, _, _, morphology, _, target_snrs, _ = arguments
            expected_ids = _expected_trial_ids(
                contract["contract_digest"], row, morphology, target_snrs
            )
            chunk_path = _trial_chunk_path(run_dir, row, morphology)
            all_trials.extend(
                _trial_chunk(
                    chunk_path,
                    expected_ids,
                    contract_digest=contract["contract_digest"],
                )
            )
        if len(all_trials) != total_trials:
            raise ContractError("A1 held-out trial cardinality changed")
        clean_path = run_dir / "heldout_clean_controls.jsonl"
        trial_path = run_dir / "heldout_trials.jsonl"
        cells_path = run_dir / "heldout_cells.jsonl"
        _atomic_jsonl(clean_path, clean_records)
        _atomic_jsonl(trial_path, all_trials)
        analysis = _analyze_heldout(
            clean_rows=clean_records, trial_rows=all_trials, contract=contract
        )
        _atomic_jsonl(cells_path, analysis.pop("cells"))
        analysis_path = run_dir / "heldout_analysis.json"
        analysis_body = {
            "schema_version": SCHEMA_VERSION,
            "status": analysis["decision"]["a1_confirmatory_status"],
            "contract_digest": contract["contract_digest"],
            **analysis,
        }
        _atomic_json(
            analysis_path,
            {
                **analysis_body,
                "artifact_digest": canonical_json_sha256(analysis_body),
            },
        )
        body = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS_MULTISCALE_EFFICIENCY_V2_A1_HELDOUT_EXECUTION",
            "run_key": run_key,
            "contract_digest": contract["contract_digest"],
            "cohort_artifact_digest": cohort_summary["artifact_digest"],
            "joint_null_artifact_digest": joint_summary["artifact_digest"],
            "runtime": runtime,
            "clean_controls": {
                "filename": clean_path.name,
                "row_total": len(clean_records),
                "sha256": sha256_file(clean_path),
            },
            "trials": {
                "filename": trial_path.name,
                "row_total": len(all_trials),
                "sha256": sha256_file(trial_path),
            },
            "cells": {
                "filename": cells_path.name,
                "row_total": expected_cells,
                "sha256": sha256_file(cells_path),
            },
            "analysis": {
                "filename": analysis_path.name,
                "sha256": sha256_file(analysis_path),
                "confirmatory_status": analysis_body["status"],
            },
            "scientific_boundary": contract["scientific_boundary"],
        }
        _atomic_json(
            summary_path, {**body, "artifact_digest": canonical_json_sha256(body)}
        )
        _update_progress(
            progress_path,
            stage="complete",
            completed=total_work,
            total=total_work,
            started=started,
        )
        return verify_heldout(
            run_dir=run_dir, joint_null_run_dir=joint_null_run_dir, root=root
        ), run_dir
    except BaseException as exc:
        _atomic_json(
            failure_path,
            {
                "status": "FAILED_MULTISCALE_EFFICIENCY_V2_A1_HELDOUT",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "run_key": run_key,
            },
        )
        raise


def verify_heldout(
    *, run_dir: Path, joint_null_run_dir: Path, root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_a1_contract(root)
    summary_path = run_dir / "heldout_summary.json"
    failure_path = run_dir / "failure.json"
    if failure_path.is_file():
        raise ContractError("A1 held-out failure artifact is present")
    if not summary_path.is_file():
        raise ContractError("A1 held-out summary is absent")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("A1 held-out artifact digest mismatch")
    joint_summary = verify_joint_null(run_dir=joint_null_run_dir, root=root)
    expected_run_key = _heldout_run_key(
        contract["contract_digest"],
        summary["runtime"]["environment_digest"],
        summary["cohort_artifact_digest"],
        joint_summary["artifact_digest"],
    )
    if (
        summary.get("status") != "PASS_MULTISCALE_EFFICIENCY_V2_A1_HELDOUT_EXECUTION"
        or summary.get("run_key") != expected_run_key
        or run_dir.name != f"heldout_{expected_run_key}"
        or summary.get("contract_digest") != contract["contract_digest"]
        or summary.get("cohort_artifact_digest")
        != contract["heldout_cohort"]["artifact_digest"]
        or summary.get("joint_null_artifact_digest") != joint_summary["artifact_digest"]
    ):
        raise ContractError("A1 held-out identity changed")
    paths = {
        label: run_dir / summary[label]["filename"]
        for label in ("clean_controls", "trials", "cells", "analysis")
    }
    for label, path in paths.items():
        if not path.is_file() or sha256_file(path) != summary[label]["sha256"]:
            raise ContractError(f"A1 held-out output mismatch: {label}")
    clean_rows = _read_jsonl(paths["clean_controls"])
    trial_rows = _read_jsonl(paths["trials"])
    expected_clean, expected_trials, expected_cell_total = (
        _expected_heldout_cardinalities(contract)
    )
    if (
        len(clean_rows) != expected_clean
        or len(trial_rows) != expected_trials
        or summary["clean_controls"]["row_total"] != expected_clean
        or summary["trials"]["row_total"] != expected_trials
        or summary["cells"]["row_total"] != expected_cell_total
    ):
        raise ContractError("A1 held-out cardinality changed")
    expected_analysis = _analyze_heldout(
        clean_rows=clean_rows, trial_rows=trial_rows, contract=contract
    )
    replay_cells = expected_analysis.pop("cells")
    if (
        len(replay_cells) != expected_cell_total
        or _read_jsonl(paths["cells"]) != replay_cells
    ):
        raise ContractError("A1 held-out cell replay mismatch")
    analysis = json.loads(paths["analysis"].read_text(encoding="utf-8"))
    analysis_body = dict(analysis)
    analysis_digest = analysis_body.pop("artifact_digest", None)
    expected_body = {
        "schema_version": SCHEMA_VERSION,
        "status": expected_analysis["decision"]["a1_confirmatory_status"],
        "contract_digest": contract["contract_digest"],
        **expected_analysis,
    }
    if (
        analysis_digest != canonical_json_sha256(analysis_body)
        or analysis_body != expected_body
    ):
        raise ContractError("A1 held-out analysis replay mismatch")
    return summary


__all__ = [
    "A1_CONTRACT_REL",
    "ENDPOINT_LABELS",
    "empirical_tail_probability",
    "holm_adjust",
    "joint_surprise",
    "load_a1_contract",
    "paired_gain_statistic",
    "paired_sign_flip_pvalue",
    "run_heldout",
    "run_joint_null",
    "validate_a1_contract",
    "verify_heldout",
    "verify_joint_null",
]
