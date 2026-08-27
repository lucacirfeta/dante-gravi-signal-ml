"""One-shot risk calibration for the frozen DANTE-Light v7 ensemble."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

import numpy as np
import torch

from src.dante_light.contracts import ContractError, RepresentationContract, WindowIdentity, canonical_json_sha256
from src.dante_light.prefilter_evaluation import wilson_interval
from src.dante_light.prefilter_v5_development import (
    _digest_array,
    _fetch_development_strain,
    _prepare_from_strain,
    _prepare_injection,
)
from src.dante_light.prefilter_v5_screening import _audit_selected
from src.dante_light.prefilter_v5_teacher import ExactNativeTeacher
from src.dante_light.prefilter_v7_freeze import verify_freeze
from src.dante_light.prefilter_v7_teacher_stability import verify_stability_contract, verify_stability_receipt
from src.dante_light.prefilter_v7_threshold_search import (
    DEFAULT_THRESHOLD_CONTRACT,
    _load_ensemble,
    verify_threshold_search_result,
)
from src.dante_light.prefilter_v7_training import _atomic_json, _atomic_jsonl, _cache_raw_windows, _thresholds, strict_defer_label
from src.dante_light.prefilter_v7_training_freeze import ROOT, file_sha256, repository_reference
from src.dante_light.prefilter_v7_waveforms import DEFAULT_CACHE, DEFAULT_SUMMARY as DEFAULT_WAVEFORM_SUMMARY, verify_waveform_cache


SCHEMA_VERSION = 1
DETECTORS = ("H1", "L1")
PROTECTED_ROLES = ("robust_candidate", "known_glitch", "injection")
DEFAULT_TRAINING_CACHE = Path("E:/dante_cache/dante_light/prefilter_l4_v7_training")
DEFAULT_AUTHORIZATION = ROOT / "config/dante_light_prefilter_v7_risk_calibration_authorization.json"
DEFAULT_RECEIPT = ROOT / "artifacts/dante_light/prefilter_l4_v7_risk_calibration/teacher_stability_receipt_risk_calibration_v7.json"
DEFAULT_ROWS = ROOT / "artifacts/dante_light/prefilter_l4_v7_risk_calibration/risk_calibration_scores_compact_v7.jsonl"
DEFAULT_RESULT = ROOT / "artifacts/dante_light/prefilter_l4_v7_risk_calibration/risk_calibration_summary_v7.json"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _verify_digest(payload: Mapping[str, Any], field: str, label: str) -> None:
    body = dict(payload)
    if body.pop(field, None) != canonical_json_sha256(body):
        raise ContractError(f"{label} digest mismatch")


def risk_calibration_rows(*, root: Path = ROOT) -> list[dict[str, Any]]:
    verify_freeze(root)
    rows = [
        row for row in _read_jsonl(root / "config/dante_light_prefilter_v7_identities.jsonl")
        if row.get("partition") == "risk_calibration"
    ]
    rows.sort(key=lambda row: (row["detector"], row["role"], row["morphology"], row["identity_id"]))
    if len(rows) != 1620 or len({row["identity_id"] for row in rows}) != 1620:
        raise ContractError("v7 risk-calibration identities are incomplete")
    expected = {
        "background": 150, "teacher_positive": 60, "robust_candidate": 60,
        "known_glitch": 180, "injection": 360,
    }
    for detector in DETECTORS:
        for role, count in expected.items():
            if sum(row["detector"] == detector and row["role"] == role for row in rows) != count:
                raise ContractError(f"v7 risk-calibration count changed: {detector}/{role}")
    return rows


def risk_code_references(root: Path = ROOT) -> dict[str, dict[str, str]]:
    paths = {
        "risk_implementation": root / "src/dante_light/prefilter_v7_risk_calibration.py",
        "risk_freezer": root / "scripts/freeze_dante_light_prefilter_v7_risk_calibration.py",
        "risk_runner": root / "scripts/run_dante_light_prefilter_v7_risk_calibration.py",
        "risk_verifier": root / "scripts/verify_dante_light_prefilter_v7_risk_calibration.py",
        "waveform_cache": root / "src/dante_light/prefilter_v7_waveforms.py",
        "waveform_reconstruction": root / "src/dante_light/prefilter_v5_injections.py",
        "student_architecture": root / "src/dante_light/prefilter_v6_phase_a.py",
        "exact_teacher": root / "src/dante_light/prefilter_v5_teacher.py",
        "preprocessor": root / "src/core/preprocessor.py",
        "data_loader": root / "src/core/data_loader.py",
    }
    return {name: repository_reference(root, path) for name, path in paths.items()}


def build_authorization(*, root: Path = ROOT, code_references: Mapping[str, Mapping[str, str]]) -> dict[str, Any]:
    frozen = verify_freeze(root)
    search = verify_threshold_search_result(root=root)
    stability = verify_stability_contract(root=root)
    _, _, waveforms = verify_waveform_cache(root=root, cache_root=DEFAULT_CACHE)
    threshold = _read_json(root / DEFAULT_THRESHOLD_CONTRACT.relative_to(ROOT))
    _verify_digest(threshold, "threshold_contract_digest", "v7 threshold contract")
    if threshold.get("status") != "FROZEN_PRE_RISK_CALIBRATION" or any(threshold["accessed"].values()):
        raise ContractError("v7 threshold contract is not sealed before risk calibration")
    for reference in code_references.values():
        path = root / reference["path"]
        if not path.is_file() or file_sha256(path) != reference["sha256"]:
            raise ContractError("v7 risk-calibration code reference changed")
    identity_path = root / "config/dante_light_prefilter_v7_identities.jsonl"
    bootstrap_seed = int(canonical_json_sha256({
        "purpose": "v7_risk_calibration_detector_gps_block_bootstrap",
        "outcome_contract_digest": frozen["contract_digest"],
        "threshold_contract_digest": threshold["threshold_contract_digest"],
        "identity_manifest_sha256": file_sha256(identity_path),
        "waveform_artifact_digest": waveforms["artifact_digest"],
    })[:16], 16)
    sources = {
        "outcome_contract": root / "config/dante_light_prefilter_v7_outcome_blind_contract.json",
        "identity_manifest": identity_path,
        "identity_header": root / "config/dante_light_prefilter_v7_identities.json",
        "threshold_contract": root / DEFAULT_THRESHOLD_CONTRACT.relative_to(ROOT),
        "threshold_result": root / "artifacts/dante_light/prefilter_l4_v7_threshold_search/threshold_search_summary_v7.json",
        "training_summary": root / "artifacts/dante_light/prefilter_l4_v7_training/student_training_summary_v7.json",
        "teacher_stability_contract": root / "config/dante_light_prefilter_v7_teacher_stability.json",
        "confirmation_seal": root / "config/dante_light_prefilter_v7_confirmation_seal.json",
        "waveform_summary": root / DEFAULT_WAVEFORM_SUMMARY.relative_to(ROOT),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "AUTHORIZED_RISK_CALIBRATION_ONLY",
        "authorization_id": "dante-light-l4-prefilter-v7-risk-calibration-2026-08-27",
        "authorization_source": {"actor": "Luca Cirfeta", "date": "2026-08-27", "instruction": "procedi"},
        "outcome_contract_digest": frozen["contract_digest"],
        "threshold_search_result_digest": search["threshold_search_result_digest"],
        "threshold_contract_digest": threshold["threshold_contract_digest"],
        "teacher_stability_contract_digest": stability["stability_contract_digest"],
        "waveform_artifact_digest": waveforms["artifact_digest"],
        "allowed": {
            "partition": "risk_calibration",
            "fixed_threshold_evaluation_once": True,
            "exact_teacher_on_background_and_teacher_positive": True,
            "protected_control_retention": True,
            "paired_cost_measurement": True,
        },
        "gate_interpretation": {
            "safety": "pre_audit_light_defer_only",
            "teacher_positive": "separate_detector_current_exact_teacher_positives_within_frozen_catalog",
            "protected": "separate_detector_role_and_morphology_no_pooling",
            "background_reduction": "realized_post_audit_separate_by_detector_gte_0.50",
            "net_saving": "combined_detector_gps_4096s_block_bootstrap_lower_gt_0",
            "net_saving_per_detector": "diagnostic_only",
            "bootstrap_resamples": 2000,
            "bootstrap_confidence": 0.95,
            "bootstrap_quantile_method": "linear",
            "bootstrap_seed_uint64": bootstrap_seed,
            "threshold_adjustment_allowed": False,
        },
        "forbidden": {"confirmation": [], "o4b": [], "routing": False, "retuning": False, "fallback_threshold": False, "member_selection": False},
        "code_references": {name: dict(value) for name, value in code_references.items()},
        "source_references": {name: repository_reference(root, path) for name, path in sources.items()},
    }
    return {**body, "authorization_digest": canonical_json_sha256(body)}


def load_authorization(path: Path = DEFAULT_AUTHORIZATION, *, root: Path = ROOT) -> dict[str, Any]:
    payload = _read_json(root / path.relative_to(ROOT) if path.is_absolute() else path)
    _verify_digest(payload, "authorization_digest", "v7 risk-calibration authorization")
    if (
        payload.get("status") != "AUTHORIZED_RISK_CALIBRATION_ONLY"
        or payload.get("allowed", {}).get("partition") != "risk_calibration"
        or payload.get("forbidden") != {"confirmation": [], "o4b": [], "routing": False, "retuning": False, "fallback_threshold": False, "member_selection": False}
        or payload["gate_interpretation"].get("threshold_adjustment_allowed") is not False
    ):
        raise ContractError("v7 risk-calibration authorization boundary widened")
    for group in ("code_references", "source_references"):
        for reference in payload[group].values():
            candidate = root / reference["path"]
            if not candidate.is_file() or file_sha256(candidate) != reference["sha256"]:
                raise ContractError("v7 risk-calibration frozen reference changed")
    return payload


def retention_gate(retained: int, total: int, *, confidence: float = 0.95) -> dict[str, Any]:
    if total <= 0 or retained < 0 or retained > total:
        raise ContractError("v7 risk-calibration retention count is invalid")
    lower, upper = wilson_interval(retained, total, confidence)
    point = retained / total
    return {"retained": retained, "total": total, "point_retention": point, "wilson95": [float(lower), float(upper)], "pass": bool(point >= 0.90 and lower >= 0.80)}


def _bootstrap_mean(rows: Sequence[Mapping[str, Any]], values: np.ndarray, *, seed: int, n_resamples: int = 2000) -> dict[str, Any]:
    blocks: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        blocks[str(row["block_key"])].append(index)
    keys = sorted(blocks)
    if len(keys) < 2:
        raise ContractError("v7 risk-calibration bootstrap has fewer than two blocks")
    rng = np.random.default_rng(seed)
    estimates = np.empty(n_resamples, dtype=np.float64)
    for index in range(n_resamples):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        indices = [item for key in sampled for item in blocks[str(key)]]
        estimates[index] = float(np.mean(values[indices]))
    interval = np.quantile(estimates, [0.025, 0.975], method="linear")
    return {"interval95": [float(interval[0]), float(interval[1])], "lower95": float(interval[0]), "n_resamples": n_resamples, "block_count": len(keys)}


def evaluate_rows(rows: Sequence[Mapping[str, Any]], *, authorization: Mapping[str, Any], threshold_contract: Mapping[str, Any]) -> dict[str, Any]:
    if len(rows) != 1620 or len({row["identity_id"] for row in rows}) != 1620:
        raise ContractError("v7 risk-calibration compact ledger is incomplete")
    thresholds = {detector: float(threshold_contract["detector_thresholds"][detector]["defer_score_threshold"]) for detector in DETECTORS}
    primary = {}
    protected = {}
    for detector in DETECTORS:
        current = [row for row in rows if row["detector"] == detector and row["role"] == "teacher_positive" and row["teacher_target"]["defer_label"] == 1]
        primary[detector] = retention_gate(sum(row["student"]["pre_audit_defer"] for row in current), len(current))
        for role in PROTECTED_ROLES:
            morphologies = sorted({row["morphology"] for row in rows if row["detector"] == detector and row["role"] == role})
            for morphology in morphologies:
                cell = [row for row in rows if row["detector"] == detector and row["role"] == role and row["morphology"] == morphology]
                protected[f"{detector}|{role}|{morphology}"] = retention_gate(sum(row["student"]["pre_audit_defer"] for row in cell), len(cell))
    background = [row for row in rows if row["role"] == "background"]
    reduction = {}
    for detector in DETECTORS:
        cell = [row for row in background if row["detector"] == detector]
        avoided = sum(not row["student"]["post_audit_exact_call"] for row in cell)
        audited = sum(row["student"]["audit_selected"] and not row["student"]["pre_audit_defer"] for row in cell)
        reduction[detector] = {"avoided_exact_calls": avoided, "exact_calls": len(cell) - avoided, "total": len(cell), "realized_post_audit_reduction": avoided / len(cell), "audited_model_discards": audited, "pass": avoided / len(cell) >= 0.50}
    net = np.asarray([float(row["cost"]["net_saving_s"]) for row in background], dtype=np.float64)
    seed = int(authorization["gate_interpretation"]["bootstrap_seed_uint64"])
    combined = _bootstrap_mean(background, net, seed=seed)
    combined.update({"mean_net_saving_s": float(np.mean(net)), "pass": combined["lower95"] > 0.0})
    by_detector = {}
    for detector in DETECTORS:
        cell = [row for row in background if row["detector"] == detector]
        values = np.asarray([float(row["cost"]["net_saving_s"]) for row in cell])
        diagnostic = _bootstrap_mean(cell, values, seed=int.from_bytes(hashlib.sha256(f"{seed}:{detector}".encode()).digest()[:8], "big"))
        diagnostic["mean_net_saving_s"] = float(np.mean(values))
        by_detector[detector] = diagnostic
    background_teacher = {}
    for detector in DETECTORS:
        cell = [row for row in background if row["detector"] == detector]
        positives = [row for row in cell if row["teacher_target"]["defer_label"] == 1]
        background_teacher[detector] = {"current_exact_teacher_positives": len(positives), "light_deferred": sum(row["student"]["pre_audit_defer"] for row in positives), "role": "secondary_descriptive_not_a_gate"}
    all_primary = all(value["pass"] for value in primary.values())
    all_protected = all(value["pass"] for value in protected.values())
    operational_pass = all(value["pass"] for value in reduction.values()) and combined["pass"]
    return {
        "primary_teacher_positive": primary,
        "protected_morphology": protected,
        "operational": {"background_by_detector": reduction, "combined_net_saving": combined, "net_saving_by_detector_diagnostic": by_detector},
        "background_teacher_positive_secondary": background_teacher,
        "analytic_baselines": {"always_defer": {"retention": 1.0, "post_audit_reduction": 0.0}, "always_discard_nominal": {"retention": 0.0, "expected_post_audit_reduction": 0.95}},
        "gate_summary": {"primary_pass": all_primary, "protected_pass": all_protected, "operational_pass": operational_pass, "all_pass": all_primary and all_protected and operational_pass},
    }


def _run_key(authorization: Mapping[str, Any], receipt: Mapping[str, Any], checkpoints: Sequence[Mapping[str, Any]]) -> str:
    return canonical_json_sha256({"authorization_digest": authorization["authorization_digest"], "stability_receipt_digest": receipt["stability_receipt_digest"], "checkpoints": list(checkpoints), "stage": "risk_calibration", "schema_version": SCHEMA_VERSION})


def _cpu_score_cost(ensemble: torch.nn.Module, clean: np.ndarray, *, threshold: float, audit_seed: int, window_id: str) -> tuple[float, float, bool]:
    began = time.perf_counter()
    values = torch.from_numpy(np.ascontiguousarray(clean, dtype=np.float32)).view(1, 1, -1)
    with torch.inference_mode():
        score = float(torch.sigmoid(ensemble.member_logits(values)).mean().item())
    _ = score >= threshold
    audited = _audit_selected(audit_seed, 0.05, window_id)
    elapsed = time.perf_counter() - began
    return score, elapsed, audited


def run_risk_calibration(*, root: Path = ROOT, cache_root: Path = DEFAULT_CACHE, training_cache_root: Path = DEFAULT_TRAINING_CACHE, receipt_path: Path = DEFAULT_RECEIPT, workers: int = 4, retries: int = 3, device_name: str = "cuda") -> dict[str, Any]:
    authorization = load_authorization(root=root)
    stability = verify_stability_contract(root=root)
    receipt = _read_json(receipt_path)
    verify_stability_receipt(receipt, contract=stability)
    if receipt.get("requested_partition") != "risk_calibration" or receipt.get("partition_rows_accessed_before_check") != 0:
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: invalid risk-calibration stability receipt")
    threshold_contract = _read_json(root / DEFAULT_THRESHOLD_CONTRACT.relative_to(ROOT))
    _verify_digest(threshold_contract, "threshold_contract_digest", "v7 threshold contract")
    if threshold_contract["threshold_contract_digest"] != authorization["threshold_contract_digest"]:
        raise ContractError("STOP_NO_ACCESS_NO_RETUNE: frozen threshold changed")
    device = torch.device(device_name)
    gpu_ensemble, checkpoints, training = _load_ensemble(root=root, training_cache_root=training_cache_root, device=device)
    began = time.perf_counter()
    cpu_ensemble, cpu_checkpoints, _ = _load_ensemble(root=root, training_cache_root=training_cache_root, device=torch.device("cpu"))
    startup_s = time.perf_counter() - began
    if cpu_checkpoints != checkpoints:
        raise ContractError("v7 CPU/GPU ensemble identities differ")
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    zero = np.zeros(4096 * 32, dtype=np.float32)
    for _ in range(50):
        _cpu_score_cost(cpu_ensemble, zero, threshold=0.5, audit_seed=0, window_id="warmup")
    run_key = _run_key(authorization, receipt, checkpoints)
    run_dir = cache_root.resolve() / f"risk_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    marker = {"schema_version": SCHEMA_VERSION, "status": "RISK_CALIBRATION_ACCESS_STARTED_AFTER_STABILITY_PASS", "run_key": run_key, "stability_receipt_digest": receipt["stability_receipt_digest"], "partition_rows_accessed_before_check": 0, "confirmation": [], "o4b": []}
    marker_path = run_dir / "access_started.json"
    if marker_path.is_file() and _read_json(marker_path) != marker:
        raise ContractError("v7 risk-calibration access-marker collision")
    if not marker_path.is_file():
        _atomic_json(marker_path, marker)
    rows = risk_calibration_rows(root=root)
    unique = {}
    for row in rows:
        key = (row["detector"], float(row["window"]["gps_start"]), float(row["window"]["duration_s"]))
        unique.setdefault(key, row)
    raw_dir = run_dir / "raw"
    raw_records = _cache_raw_windows(list(unique.values()), raw_dir=raw_dir, workers=workers, retries=retries)
    _atomic_jsonl(run_dir / "raw_manifest_risk_calibration_v7.jsonl", raw_records)
    from src.core import data_loader
    if raw_dir not in data_loader._DATA_DIRECTORIES:
        data_loader._DATA_DIRECTORIES.insert(0, raw_dir)
    waveform_dir, waveforms, waveform_summary = verify_waveform_cache(root=root, cache_root=cache_root)
    representation = RepresentationContract.from_reference_manifest(root / "config/reference_artifacts.json")
    teacher = ExactNativeTeacher(root=root, representation=representation, device=str(device))
    teacher.score([np.zeros(representation.image_shape, dtype=np.uint8)])
    exact_thresholds = _thresholds(root)
    audit_seed = int(threshold_contract["audit_stream"]["seed_uint64"])
    thresholds = {detector: float(threshold_contract["detector_thresholds"][detector]["defer_score_threshold"]) for detector in DETECTORS}
    batch_dir = run_dir / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    payloads = []

    def prepare(row: Mapping[str, Any]):
        if row["role"] == "injection":
            source_id = row["source"]["source_id"]
            return _prepare_injection(row, representation=representation, waveform_run_dir=waveform_dir, waveform_record=waveforms[source_id], raw_cache_dir=raw_dir)
        window = WindowIdentity.from_dict(row["window"])
        began_read = time.perf_counter()
        strain, metadata = _fetch_development_strain(window, representation=representation, raw_cache_dir=raw_dir)
        data_read_s = time.perf_counter() - began_read
        raw = np.ascontiguousarray(strain.value)
        prepared = _prepare_from_strain(strain, window=window, representation=representation, raw_sha256=_digest_array(raw))
        prepared.timings["data_read_s"] = data_read_s
        return prepared, metadata

    for start in range(0, len(rows), 8):
        batch_rows = rows[start:start + 8]
        batch_index = start // 8
        path = batch_dir / f"batch_{batch_index:04d}.json"
        expected = [row["identity_id"] for row in batch_rows]
        if path.is_file():
            payload = _read_json(path)
            _verify_digest(payload, "batch_digest", "v7 risk-calibration batch")
            if payload.get("run_key") != run_key or [row["identity_id"] for row in payload["rows"]] != expected:
                raise ContractError("v7 risk-calibration cached batch changed")
            payloads.append(payload)
            continue
        prepared_by_id = {}
        failures = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(prepare, row): row for row in batch_rows}
            for future in as_completed(futures):
                row = futures[future]
                try:
                    prepared_by_id[row["identity_id"]] = future.result()
                except Exception as exc:
                    failures.append({"identity_id": row["identity_id"], "exception_type": type(exc).__name__, "message": str(exc)})
        if failures:
            raise ContractError(f"v7 risk-calibration preparation failed: {failures}")
        prepared = [prepared_by_id[row["identity_id"]][0] for row in batch_rows]
        values = torch.from_numpy(np.stack([item.clean_strain for item in prepared]).astype(np.float32, copy=False)).unsqueeze(1).to(device)
        with torch.inference_mode():
            members = torch.sigmoid(gpu_ensemble.member_logits(values))
            scores = members.mean(dim=-1)
        score_values = scores.detach().cpu().numpy()
        member_values = members.detach().cpu().numpy()
        result_rows = []
        for offset, (row, item) in enumerate(zip(batch_rows, prepared, strict=True)):
            score = float(score_values[offset])
            threshold = thresholds[row["detector"]]
            pre_audit_defer = bool(score >= threshold)
            audited = bool((not pre_audit_defer) and _audit_selected(audit_seed, 0.05, row["window"]["window_id"]))
            teacher_target = {"native_score": None, "historical_detector_threshold": exact_thresholds[row["detector"]], "defer_label": None}
            exact_cost = None
            if row["role"] in {"background", "teacher_positive"}:
                teacher_scores, teacher_timings = teacher.score([item.image])
                native = float(teacher_scores[0])
                teacher_target = {"native_score": native, "native_score_float32_hex": np.float32(native).tobytes().hex(), "historical_detector_threshold": exact_thresholds[row["detector"]], "defer_label": strict_defer_label(native, exact_thresholds[row["detector"]])}
                exact_cost = float(item.timings["q_transform_s"] + item.timings["rendering_s"] + teacher_timings["score_total_s"])
            light_cost = None
            cpu_score = None
            if row["role"] == "background":
                cpu_score, light_cost, cpu_audit = _cpu_score_cost(cpu_ensemble, item.clean_strain, threshold=threshold, audit_seed=audit_seed, window_id=row["window"]["window_id"])
                if cpu_audit != _audit_selected(audit_seed, 0.05, row["window"]["window_id"]):
                    raise ContractError("v7 risk-calibration audit decision is unstable")
            avoided = bool(row["role"] == "background" and not (pre_audit_defer or audited))
            result_rows.append({
                "identity_id": row["identity_id"], "window_id": row["window"]["window_id"], "detector": row["detector"], "role": row["role"], "morphology": row["morphology"], "block_key": row["block_key"],
                "raw_strain_sha256": item.raw_strain_sha256, "clean_strain_sha256": item.clean_strain_sha256, "image_sha256": item.image_sha256,
                "teacher_target": teacher_target,
                "student": {"ensemble_defer_score": score, "member_defer_scores": [float(value) for value in member_values[offset]], "threshold": threshold, "pre_audit_defer": pre_audit_defer, "audit_selected": audited, "post_audit_exact_call": bool(pre_audit_defer or audited), "cpu_ensemble_score_diagnostic": cpu_score},
                "cost": {"light_path_s": light_cost, "avoidable_exact_path_s": exact_cost, "net_saving_s": (float(exact_cost) if avoided else 0.0) - float(light_cost) if row["role"] == "background" else None},
                "preparation_metadata": prepared_by_id[row["identity_id"]][1],
            })
        body = {"schema_version": SCHEMA_VERSION, "status": "COMPLETE_RISK_CALIBRATION_BATCH", "run_key": run_key, "batch_index": batch_index, "rows": result_rows, "confirmation": [], "o4b": []}
        payload = {**body, "batch_digest": canonical_json_sha256(body)}
        _atomic_json(path, payload)
        payloads.append(payload)
    compact = sorted([row for payload in payloads for row in payload["rows"]], key=lambda row: row["identity_id"])
    _atomic_jsonl(DEFAULT_ROWS, compact)
    evaluation = evaluate_rows(compact, authorization=authorization, threshold_contract=threshold_contract)
    status = "RISK_CALIBRATION_PASS_AWAIT_CONFIRMATION_AUTHORIZATION" if evaluation["gate_summary"]["all_pass"] else "V7_NOT_READY_RISK_CALIBRATION"
    ledger_path = run_dir / "risk_calibration_rows_v7.jsonl"
    _atomic_jsonl(ledger_path, compact)
    result_body = {
        "schema_version": SCHEMA_VERSION, "status": status, "run_key": run_key, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "authorization_digest": authorization["authorization_digest"], "teacher_stability_receipt_digest": receipt["stability_receipt_digest"], "threshold_contract_digest": threshold_contract["threshold_contract_digest"], "training_artifact_digest": training["artifact_digest"], "waveform_artifact_digest": waveform_summary["artifact_digest"], "checkpoint_contract": checkpoints,
        "row_count": len(compact), "evaluation": evaluation, "cpu_model_load_startup_s": startup_s,
        "compact_rows": {"path": DEFAULT_ROWS.relative_to(root).as_posix(), "sha256": file_sha256(DEFAULT_ROWS), "records_digest": canonical_json_sha256(compact)},
        "full_cache": {"environment_alias": "DANTE_V7_RISK_CALIBRATION_CACHE_ROOT", "run_subdirectory": run_dir.name, "ledger_sha256": file_sha256(ledger_path), "raw_manifest_sha256": file_sha256(run_dir / "raw_manifest_risk_calibration_v7.jsonl"), "access_marker_sha256": file_sha256(marker_path)},
        "accessed": {"risk_calibration_identity_ids": [row["identity_id"] for row in compact], "confirmation": [], "o4b": []}, "routing_enabled": False, "candidate_promoted": False,
    }
    result = {**result_body, "risk_calibration_result_digest": canonical_json_sha256(result_body)}
    _atomic_json(DEFAULT_RESULT, result)
    return result


def verify_result(*, root: Path = ROOT, cache_root: Path | None = None) -> dict[str, Any]:
    authorization = load_authorization(root=root)
    threshold = _read_json(root / DEFAULT_THRESHOLD_CONTRACT.relative_to(ROOT))
    _verify_digest(threshold, "threshold_contract_digest", "v7 threshold contract")
    receipt = _read_json(DEFAULT_RECEIPT)
    verify_stability_receipt(receipt, contract=verify_stability_contract(root=root))
    if receipt.get("requested_partition") != "risk_calibration":
        raise ContractError("v7 risk-calibration receipt stage mismatch")
    result = _read_json(DEFAULT_RESULT)
    _verify_digest(result, "risk_calibration_result_digest", "v7 risk-calibration result")
    if result.get("authorization_digest") != authorization["authorization_digest"] or result.get("teacher_stability_receipt_digest") != receipt["stability_receipt_digest"] or result.get("threshold_contract_digest") != threshold["threshold_contract_digest"] or result.get("routing_enabled") is not False or result.get("candidate_promoted") is not False or result["accessed"].get("confirmation") or result["accessed"].get("o4b"):
        raise ContractError("v7 risk-calibration boundary or provenance changed")
    rows_path = root / result["compact_rows"]["path"]
    if file_sha256(rows_path) != result["compact_rows"]["sha256"]:
        raise ContractError("v7 risk-calibration compact ledger changed")
    rows = _read_jsonl(rows_path)
    if len(rows) != 1620 or canonical_json_sha256(rows) != result["compact_rows"]["records_digest"]:
        raise ContractError("v7 risk-calibration compact ledger is incomplete")
    replayed = evaluate_rows(rows, authorization=authorization, threshold_contract=threshold)
    if replayed != result["evaluation"]:
        raise ContractError("v7 risk-calibration gates do not replay exactly")
    if cache_root is not None:
        run_dir = cache_root.resolve() / result["full_cache"]["run_subdirectory"]
        checks = {"ledger_sha256": run_dir / "risk_calibration_rows_v7.jsonl", "raw_manifest_sha256": run_dir / "raw_manifest_risk_calibration_v7.jsonl", "access_marker_sha256": run_dir / "access_started.json"}
        for field, path in checks.items():
            if file_sha256(path) != result["full_cache"][field]:
                raise ContractError("v7 risk-calibration full cache changed")
    return {"status": "PASS_VERIFIED_RISK_CALIBRATION", "scientific_status": result["status"], "risk_calibration_result_digest": result["risk_calibration_result_digest"], "gate_summary": result["evaluation"]["gate_summary"], "confirmation": [], "o4b": [], "routing_enabled": False}
