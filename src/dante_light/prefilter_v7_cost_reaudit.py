"""Cost-only re-audit for the closed DANTE-Light v7 risk calibration.

The original one-shot outcome artifact remains immutable.  This module only
re-measures latency on its already-open background identities after the
original per-window timing was found to mix contended preprocessing wall time
with serial teacher latency.
"""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.prefilter_v5_screening import _audit_selected
from src.dante_light.prefilter_v5_teacher import ExactNativeTeacher
from src.dante_light.prefilter_v7_risk_calibration import (
    DEFAULT_RESULT as ORIGINAL_RESULT,
    DEFAULT_ROWS as ORIGINAL_ROWS,
    DEFAULT_TRAINING_CACHE,
    _bootstrap_mean,
    _cpu_score_cost,
    _digest_array,
    _fetch_development_strain,
)
from src.dante_light.prefilter_v7_threshold_search import (
    DEFAULT_THRESHOLD_CONTRACT,
    _load_ensemble,
)
from src.dante_light.prefilter_v7_training import _atomic_json, _atomic_jsonl
from src.dante_light.prefilter_v7_training_freeze import (
    ROOT,
    file_sha256,
    repository_reference,
)


SCHEMA_VERSION = 1
DETECTORS = ("H1", "L1")
DEFAULT_CACHE = Path("E:/dante_cache/dante_light/prefilter_l4_v7_risk_calibration")
DEFAULT_CONTRACT = ROOT / "config/dante_light_prefilter_v7_cost_reaudit.json"
DEFAULT_LEDGER = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_risk_calibration"
    / "cost_reaudit_timings_v7.jsonl"
)
DEFAULT_RESULT = (
    ROOT
    / "artifacts/dante_light/prefilter_l4_v7_risk_calibration"
    / "cost_reaudit_summary_v7.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _verify_digest(payload: Mapping[str, Any], field: str, label: str) -> None:
    body = dict(payload)
    if body.pop(field, None) != canonical_json_sha256(body):
        raise ContractError(f"{label} digest mismatch")


def _background_rows(root: Path = ROOT) -> list[dict[str, Any]]:
    rows = [
        row
        for row in _read_jsonl(root / ORIGINAL_ROWS.relative_to(ROOT))
        if row.get("role") == "background"
    ]
    rows.sort(key=lambda row: row["identity_id"])
    if len(rows) != 300 or len({row["identity_id"] for row in rows}) != 300:
        raise ContractError("v7 cost re-audit requires exactly 300 background rows")
    if any(row["detector"] not in DETECTORS for row in rows):
        raise ContractError("v7 cost re-audit detector set changed")
    if any(row["cost"]["avoidable_exact_path_s"] is None for row in rows):
        raise ContractError("v7 cost re-audit source timings are incomplete")
    return rows


def _background_identity_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    return canonical_json_sha256(
        [
            {
                "block_key": row["block_key"],
                "detector": row["detector"],
                "identity_id": row["identity_id"],
                "post_audit_exact_call": row["student"]["post_audit_exact_call"],
                "window_id": row["window_id"],
            }
            for row in rows
        ]
    )


def cost_code_references(root: Path = ROOT) -> dict[str, dict[str, str]]:
    paths = {
        "cost_implementation": root / "src/dante_light/prefilter_v7_cost_reaudit.py",
        "cost_freezer": root / "scripts/freeze_dante_light_prefilter_v7_cost_reaudit.py",
        "cost_runner": root / "scripts/run_dante_light_prefilter_v7_cost_reaudit.py",
        "cost_verifier": root / "scripts/verify_dante_light_prefilter_v7_cost_reaudit.py",
        "risk_implementation": root / "src/dante_light/prefilter_v7_risk_calibration.py",
        "exact_teacher": root / "src/dante_light/prefilter_v5_teacher.py",
        "preprocessor": root / "src/core/preprocessor.py",
        "student_architecture": root / "src/dante_light/prefilter_v6_phase_a.py",
    }
    return {name: repository_reference(root, path) for name, path in paths.items()}


def build_contract(
    *, root: Path = ROOT, code_references: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    original_result_path = root / ORIGINAL_RESULT.relative_to(ROOT)
    original_rows_path = root / ORIGINAL_ROWS.relative_to(ROOT)
    original = _read_json(original_result_path)
    _verify_digest(original, "risk_calibration_result_digest", "v7 risk result")
    rows = _background_rows(root)
    seed = int(
        canonical_json_sha256(
            {
                "purpose": "v7_cost_reaudit_block_bootstrap",
                "original_result_digest": original["risk_calibration_result_digest"],
                "background_identity_digest": _background_identity_digest(rows),
            }
        )[:16],
        16,
    )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_COST_ONLY_REAUDIT",
        "contract_id": "dante-light-l4-prefilter-v7-cost-reaudit-2026-08-27",
        "authorization": {
            "actor": "Luca Cirfeta",
            "date": "2026-08-27",
            "scope": "cost-only re-audit on the 300 already-open risk-calibration background blocks",
        },
        "source_result": {
            "path": ORIGINAL_RESULT.relative_to(ROOT).as_posix(),
            "sha256": file_sha256(original_result_path),
            "result_digest": original["risk_calibration_result_digest"],
            "scientific_status": original["status"],
            "immutable": True,
        },
        "source_rows": {
            "path": ORIGINAL_ROWS.relative_to(ROOT).as_posix(),
            "sha256": file_sha256(original_rows_path),
            "background_count": len(rows),
            "background_identity_and_route_digest": _background_identity_digest(rows),
        },
        "erratum": {
            "original_operational_cost_interpretation": "INDETERMINATE_COST_ACCOUNTING",
            "cause": (
                "per-window q-transform and rendering wall times were measured inside a "
                "four-worker thread pool and then added to serial teacher latency"
            ),
            "original_numbers_preserved": True,
            "safety_results_unchanged": True,
            "routing_or_promotion_change": False,
        },
        "measurement": {
            "row_order": "identity_id_ascending",
            "background_count": 300,
            "workers": 4,
            "batch_size": 8,
            "teacher_score_batch_size": 1,
            "light_device": "cpu",
            "exact_device": "cuda",
            "torch_cpu_threads": 1,
            "light_warmup_iterations": 50,
            "exact_warmup_iterations": 2,
            "data_read_excluded": True,
            "whitening_excluded": True,
            "model_load_excluded": True,
            "sequential_isolated": (
                "paired per-window q-transform plus rendering plus serial exact-teacher "
                "latency versus single-window five-member CPU Light latency"
            ),
            "batch_throughput": (
                "baseline exact makespan minus Light makespan minus residual exact makespan, "
                "divided by batch size; q-transform/rendering use four workers and teacher "
                "scoring remains serial at batch size one"
            ),
            "batch_statistical_role": "point_and_batch_distribution_diagnostic_no_iid_bootstrap",
        },
        "decision": {
            "sequential_gate": "detector_gps_block_bootstrap_95pct_lower_gt_0",
            "batch_gate": "combined_measured_net_throughput_s_per_window_gt_0",
            "positive_saving_supported": "both_sequential_and_batch_gates_pass",
            "promotion_allowed": False,
            "confirmation_access_allowed": False,
            "o4b_access_allowed": False,
            "threshold_or_model_change_allowed": False,
        },
        "bootstrap": {
            "unit": "detector_gps_4096s_block",
            "resamples": 2000,
            "confidence": 0.95,
            "quantile_method": "linear",
            "seed_uint64": seed,
        },
        "code_references": {name: dict(value) for name, value in code_references.items()},
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def verify_contract(path: Path = DEFAULT_CONTRACT, *, root: Path = ROOT) -> dict[str, Any]:
    resolved = root / path.relative_to(ROOT) if path.is_absolute() else path
    payload = _read_json(resolved)
    _verify_digest(payload, "contract_digest", "v7 cost re-audit contract")
    if payload.get("status") != "FROZEN_COST_ONLY_REAUDIT":
        raise ContractError("v7 cost re-audit contract is not frozen")
    if payload["erratum"].get("original_operational_cost_interpretation") != "INDETERMINATE_COST_ACCOUNTING":
        raise ContractError("v7 cost re-audit did not fail closed")
    if payload["decision"] != {
        "batch_gate": "combined_measured_net_throughput_s_per_window_gt_0",
        "confirmation_access_allowed": False,
        "o4b_access_allowed": False,
        "positive_saving_supported": "both_sequential_and_batch_gates_pass",
        "promotion_allowed": False,
        "sequential_gate": "detector_gps_block_bootstrap_95pct_lower_gt_0",
        "threshold_or_model_change_allowed": False,
    }:
        raise ContractError("v7 cost re-audit decision boundary changed")
    for reference in payload["code_references"].values():
        candidate = root / reference["path"]
        if not candidate.is_file() or file_sha256(candidate) != reference["sha256"]:
            raise ContractError("v7 cost re-audit code reference changed")
    source_result = root / payload["source_result"]["path"]
    source_rows = root / payload["source_rows"]["path"]
    if (
        file_sha256(source_result) != payload["source_result"]["sha256"]
        or file_sha256(source_rows) != payload["source_rows"]["sha256"]
    ):
        raise ContractError("v7 cost re-audit source evidence changed")
    rows = _background_rows(root)
    if _background_identity_digest(rows) != payload["source_rows"]["background_identity_and_route_digest"]:
        raise ContractError("v7 cost re-audit background identity or route changed")
    return payload


def _clean_inputs(
    rows: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    raw_dir: Path,
    representation: RepresentationContract,
) -> list[dict[str, Any]]:
    from src.core import data_loader
    from src.core.preprocessor import extract_clean_subwindow, whiten_context

    if raw_dir not in data_loader._DATA_DIRECTORIES:
        data_loader._DATA_DIRECTORIES.insert(0, raw_dir)
    cleaned = []
    identities = {
        item["identity_id"]: item
        for item in _read_jsonl(root / "config/dante_light_prefilter_v7_identities.jsonl")
    }
    for row in rows:
        frozen = identities.get(row["identity_id"])
        if frozen is None or frozen.get("role") != "background":
            raise ContractError("v7 cost re-audit identity lookup failed")
        window = WindowIdentity.from_dict(frozen["window"])
        strain, _ = _fetch_development_strain(
            window,
            representation=representation,
            raw_cache_dir=raw_dir,
        )
        raw = np.ascontiguousarray(strain.value)
        if _digest_array(raw) != row["raw_strain_sha256"]:
            raise ContractError("v7 cost re-audit raw strain digest mismatch")
        whitened, padding = whiten_context(
            strain,
            window.gps_start,
            window.gps_start + window.duration_s,
            pad=representation.whitening_pad_s,
        )
        clean = extract_clean_subwindow(
            whitened,
            window.gps_start,
            window.gps_start + window.duration_s,
        )
        if min(float(padding["effective_left"]), float(padding["effective_right"])) < representation.whitening_pad_s:
            raise ContractError("v7 cost re-audit whitening context changed")
        values = np.ascontiguousarray(clean.value, dtype=np.float32)
        if _digest_array(values) != row["clean_strain_sha256"]:
            raise ContractError("v7 cost re-audit clean strain digest mismatch")
        cleaned.append({"row": row, "window": window, "clean": values})
    return cleaned


def _q_render(
    item: Mapping[str, Any], representation: RepresentationContract
) -> tuple[np.ndarray, dict[str, float]]:
    import matplotlib.pyplot as plt
    from gwpy.timeseries import TimeSeries
    from src.core.preprocessor import generate_qtransform

    clean = TimeSeries(
        item["clean"],
        sample_rate=representation.sample_rate_hz,
        t0=item["window"].gps_start,
    )
    began = time.perf_counter()
    spectrogram = generate_qtransform(
        clean,
        save_path=None,
        cmap=representation.colormap,
        qrange=representation.query_qrange,
        frange=representation.frequency_range_hz,
        output_size=representation.image_shape[:2],
    )
    q_s = time.perf_counter() - began
    began = time.perf_counter()
    rgba = plt.get_cmap(representation.colormap)(spectrogram)
    image = np.ascontiguousarray((rgba[:, :, :3] * 255).astype(np.uint8))
    rendering_s = time.perf_counter() - began
    if _digest_array(image) != item["row"]["image_sha256"]:
        raise ContractError("v7 cost re-audit rendered image digest mismatch")
    return image, {"q_transform_s": q_s, "rendering_s": rendering_s}


def _exact_sequential(
    items: Sequence[Mapping[str, Any]],
    *,
    teacher: ExactNativeTeacher,
    representation: RepresentationContract,
) -> list[dict[str, float]]:
    output = []
    for item in items:
        image, prep = _q_render(item, representation)
        scores, teacher_timing = teacher.score([image])
        expected = float(item["row"]["teacher_target"]["native_score"])
        if abs(float(scores[0]) - expected) > 2e-7:
            raise ContractError("v7 cost re-audit exact teacher score changed")
        output.append(
            {
                **prep,
                "score_total_s": float(teacher_timing["score_total_s"]),
                "avoidable_exact_path_s": float(
                    prep["q_transform_s"]
                    + prep["rendering_s"]
                    + teacher_timing["score_total_s"]
                ),
            }
        )
    return output


def _light_sequential(
    items: Sequence[Mapping[str, Any]],
    *,
    ensemble: torch.nn.Module,
    thresholds: Mapping[str, float],
    audit_seed: int,
) -> list[float]:
    output = []
    for item in items:
        row = item["row"]
        score, elapsed, audited = _cpu_score_cost(
            ensemble,
            item["clean"],
            threshold=thresholds[row["detector"]],
            audit_seed=audit_seed,
            window_id=row["window_id"],
        )
        if audited != bool(row["student"]["audit_selected"]):
            raise ContractError("v7 cost re-audit audit decision changed")
        expected_score = float(row["student"]["cpu_ensemble_score_diagnostic"])
        if abs(score - expected_score) > 2e-5:
            raise ContractError("v7 cost re-audit CPU ensemble score changed")
        output.append(float(elapsed))
    return output


def _exact_batch_makespan(
    items: Sequence[Mapping[str, Any]],
    *,
    teacher: ExactNativeTeacher,
    representation: RepresentationContract,
    workers: int,
) -> float:
    if not items:
        return 0.0
    began = time.perf_counter()
    images: dict[str, np.ndarray] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_q_render, item, representation): item for item in items}
        for future in as_completed(futures):
            item = futures[future]
            image, _ = future.result()
            images[item["row"]["identity_id"]] = image
    for item in items:
        scores, _ = teacher.score([images[item["row"]["identity_id"]]])
        expected = float(item["row"]["teacher_target"]["native_score"])
        if abs(float(scores[0]) - expected) > 2e-7:
            raise ContractError("v7 cost re-audit batched exact score changed")
    return float(time.perf_counter() - began)


def _light_batch_makespan(
    items: Sequence[Mapping[str, Any]],
    *,
    ensemble: torch.nn.Module,
    thresholds: Mapping[str, float],
    audit_seed: int,
) -> float:
    began = time.perf_counter()
    values = torch.from_numpy(
        np.stack([item["clean"] for item in items]).astype(np.float32, copy=False)
    ).unsqueeze(1)
    with torch.inference_mode():
        scores = torch.sigmoid(ensemble.member_logits(values)).mean(dim=-1).cpu().numpy()
    for item, score in zip(items, scores, strict=True):
        row = item["row"]
        pre_audit_defer = bool(float(score) >= thresholds[row["detector"]])
        audited = bool(
            (not pre_audit_defer)
            and _audit_selected(audit_seed, 0.05, row["window_id"])
        )
        if bool(pre_audit_defer or audited) != bool(row["student"]["post_audit_exact_call"]):
            raise ContractError("v7 cost re-audit batch route changed")
    return float(time.perf_counter() - began)


def _environment(device: torch.device) -> dict[str, Any]:
    gpu = None
    if device.type == "cuda":
        gpu = torch.cuda.get_device_name(device)
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "numpy": np.__version__,
        "torch": torch.__version__,
        "logical_cpu_count": os.cpu_count(),
        "torch_cpu_threads": torch.get_num_threads(),
        "exact_device": str(device),
        "gpu": gpu,
    }


def run_cost_reaudit(
    *,
    root: Path = ROOT,
    cache_root: Path = DEFAULT_CACHE,
    training_cache_root: Path = DEFAULT_TRAINING_CACHE,
) -> dict[str, Any]:
    contract = verify_contract(root=root)
    measurement = contract["measurement"]
    if measurement["data_read_excluded"] is not True or measurement["whitening_excluded"] is not True:
        raise ContractError("v7 cost re-audit measurement boundary changed")
    original = _read_json(root / ORIGINAL_RESULT.relative_to(ROOT))
    run_dir = cache_root.resolve() / original["full_cache"]["run_subdirectory"]
    raw_dir = run_dir / "raw"
    if not raw_dir.is_dir():
        raise ContractError("v7 cost re-audit raw cache is unavailable")
    rows = _background_rows(root)
    representation = RepresentationContract.from_reference_manifest(
        root / "config/reference_artifacts.json"
    )
    items = _clean_inputs(
        rows,
        root=root,
        raw_dir=raw_dir,
        representation=representation,
    )

    exact_device = torch.device(str(measurement["exact_device"]))
    teacher = ExactNativeTeacher(
        root=root, representation=representation, device=str(exact_device)
    )
    cpu_ensemble, checkpoints, _ = _load_ensemble(
        root=root,
        training_cache_root=training_cache_root,
        device=torch.device("cpu"),
    )
    torch.set_num_threads(int(measurement["torch_cpu_threads"]))
    torch.use_deterministic_algorithms(True)
    threshold_contract = _read_json(root / DEFAULT_THRESHOLD_CONTRACT.relative_to(ROOT))
    thresholds = {
        detector: float(
            threshold_contract["detector_thresholds"][detector]["defer_score_threshold"]
        )
        for detector in DETECTORS
    }
    audit_seed = int(threshold_contract["audit_stream"]["seed_uint64"])

    zero_image = np.zeros(representation.image_shape, dtype=np.uint8)
    for _ in range(int(measurement["exact_warmup_iterations"])):
        teacher.score([zero_image])
    zero = np.zeros(representation.sample_rate_hz * 32, dtype=np.float32)
    for _ in range(int(measurement["light_warmup_iterations"])):
        _cpu_score_cost(
            cpu_ensemble,
            zero,
            threshold=0.5,
            audit_seed=0,
            window_id="cost-reaudit-warmup",
        )

    sequential_exact = _exact_sequential(
        items, teacher=teacher, representation=representation
    )
    sequential_light = _light_sequential(
        items,
        ensemble=cpu_ensemble,
        thresholds=thresholds,
        audit_seed=audit_seed,
    )
    ledger = []
    for item, exact, light in zip(items, sequential_exact, sequential_light, strict=True):
        row = item["row"]
        avoided = not bool(row["student"]["post_audit_exact_call"])
        body = {
            "schema_version": SCHEMA_VERSION,
            "identity_id": row["identity_id"],
            "window_id": row["window_id"],
            "detector": row["detector"],
            "block_key": row["block_key"],
            "avoided_exact_call": avoided,
            "sequential_isolated": {
                **exact,
                "light_path_s": light,
                "net_saving_s": (exact["avoidable_exact_path_s"] if avoided else 0.0)
                - light,
            },
        }
        ledger.append({**body, "record_digest": canonical_json_sha256(body)})

    batch_size = int(measurement["batch_size"])
    workers = int(measurement["workers"])
    batches = []
    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        residual = [
            item
            for item in batch
            if bool(item["row"]["student"]["post_audit_exact_call"])
        ]
        baseline_exact = _exact_batch_makespan(
            batch,
            teacher=teacher,
            representation=representation,
            workers=workers,
        )
        light = _light_batch_makespan(
            batch,
            ensemble=cpu_ensemble,
            thresholds=thresholds,
            audit_seed=audit_seed,
        )
        residual_exact = _exact_batch_makespan(
            residual,
            teacher=teacher,
            representation=representation,
            workers=workers,
        )
        net = baseline_exact - light - residual_exact
        batches.append(
            {
                "batch_index": len(batches),
                "row_count": len(batch),
                "residual_exact_count": len(residual),
                "baseline_exact_makespan_s": baseline_exact,
                "light_makespan_s": light,
                "residual_exact_makespan_s": residual_exact,
                "net_saving_s": net,
                "net_saving_s_per_window": net / len(batch),
                "identity_ids_digest": canonical_json_sha256(
                    [item["row"]["identity_id"] for item in batch]
                ),
            }
        )

    _atomic_jsonl(DEFAULT_LEDGER, ledger)
    seq_values = np.asarray(
        [row["sequential_isolated"]["net_saving_s"] for row in ledger],
        dtype=np.float64,
    )
    bootstrap = _bootstrap_mean(
        ledger,
        seq_values,
        seed=int(contract["bootstrap"]["seed_uint64"]),
        n_resamples=int(contract["bootstrap"]["resamples"]),
    )
    bootstrap["mean_net_saving_s"] = float(np.mean(seq_values))
    bootstrap["pass"] = bool(bootstrap["lower95"] > 0.0)
    baseline_total = float(sum(batch["baseline_exact_makespan_s"] for batch in batches))
    light_total = float(sum(batch["light_makespan_s"] for batch in batches))
    residual_total = float(sum(batch["residual_exact_makespan_s"] for batch in batches))
    batch_net = baseline_total - light_total - residual_total
    batch_gate = batch_net / len(items) > 0.0
    sequential_gate = bool(bootstrap["pass"])
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "COMPLETE_COST_REAUDIT_POSITIVE_SAVING_SUPPORTED"
            if sequential_gate and batch_gate
            else "COMPLETE_COST_REAUDIT_SAVING_NOT_ESTABLISHED"
        ),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "contract_digest": contract["contract_digest"],
        "source_result_digest": original["risk_calibration_result_digest"],
        "erratum": contract["erratum"],
        "environment": _environment(exact_device),
        "checkpoint_contract": checkpoints,
        "sequential_isolated": {
            "paired_block_bootstrap": bootstrap,
            "mean_avoidable_exact_path_s": float(
                np.mean([row["avoidable_exact_path_s"] for row in sequential_exact])
            ),
            "mean_light_path_s": float(np.mean(sequential_light)),
        },
        "batch_throughput": {
            "batch_count": len(batches),
            "workers": workers,
            "batch_size": batch_size,
            "baseline_exact_total_makespan_s": baseline_total,
            "light_total_makespan_s": light_total,
            "residual_exact_total_makespan_s": residual_total,
            "net_saving_total_s": batch_net,
            "net_saving_s_per_window": batch_net / len(items),
            "pass": batch_gate,
            "batches": batches,
        },
        "decision": {
            "sequential_gate_pass": sequential_gate,
            "batch_gate_pass": batch_gate,
            "positive_saving_supported": sequential_gate and batch_gate,
            "original_cost_gate_superseded": True,
            "candidate_promoted": False,
            "routing_enabled": False,
            "confirmation": [],
            "o4b": [],
        },
        "ledger": {
            "path": DEFAULT_LEDGER.relative_to(ROOT).as_posix(),
            "sha256": file_sha256(DEFAULT_LEDGER),
            "record_count": len(ledger),
            "records_digest": canonical_json_sha256(ledger),
        },
    }
    result = {**body, "cost_reaudit_result_digest": canonical_json_sha256(body)}
    _atomic_json(DEFAULT_RESULT, result)
    return result


def verify_result(
    *, root: Path = ROOT, result_path: Path = DEFAULT_RESULT
) -> dict[str, Any]:
    contract = verify_contract(root=root)
    path = root / result_path.relative_to(ROOT) if result_path.is_absolute() else result_path
    result = _read_json(path)
    _verify_digest(result, "cost_reaudit_result_digest", "v7 cost re-audit result")
    if result.get("contract_digest") != contract["contract_digest"]:
        raise ContractError("v7 cost re-audit result contract changed")
    if result.get("source_result_digest") != contract["source_result"]["result_digest"]:
        raise ContractError("v7 cost re-audit source result changed")
    ledger_path = root / result["ledger"]["path"]
    if file_sha256(ledger_path) != result["ledger"]["sha256"]:
        raise ContractError("v7 cost re-audit ledger hash mismatch")
    ledger = _read_jsonl(ledger_path)
    if len(ledger) != 300 or canonical_json_sha256(ledger) != result["ledger"]["records_digest"]:
        raise ContractError("v7 cost re-audit ledger content changed")
    for row in ledger:
        _verify_digest(row, "record_digest", "v7 cost re-audit row")
    if result["decision"].get("original_cost_gate_superseded") is not True:
        raise ContractError("v7 original cost gate was not superseded")
    if result["decision"].get("candidate_promoted") is not False or result["decision"].get("routing_enabled") is not False:
        raise ContractError("v7 cost re-audit changed routing or promotion")
    if result["decision"].get("confirmation") != [] or result["decision"].get("o4b") != []:
        raise ContractError("v7 cost re-audit accessed a sealed successor")
    return {
        "status": "PASS_VERIFIED_COST_REAUDIT",
        "scientific_status": result["status"],
        "cost_reaudit_result_digest": result["cost_reaudit_result_digest"],
        "decision": result["decision"],
    }
