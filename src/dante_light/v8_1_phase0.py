from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import struct
from typing import Any

import numpy as np

from src.core.index_contract import sha256_file
from src.dante_light.contracts import ContractError, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config/dante_light_v8_1_phase0_audit.json"
DEFAULT_RESULT = (
    ROOT / "artifacts/dante_light/v8_1_phase0/phase0_summary_v8_1.json"
)
PROFILE_FILES = ("run_manifest.json", "records.jsonl", "summary.json")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _root_member(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if path != root and root not in path.parents:
        raise ContractError(f"path escapes repository root: {relative}")
    return path


def _verify_bound_input(root: Path, item: dict[str, str]) -> Path:
    path = _root_member(root, item["path"])
    if not path.is_file():
        raise ContractError(f"missing bound input: {item['path']}")
    actual = sha256_file(path)
    if actual != item["sha256"]:
        raise ContractError(
            f"bound input hash mismatch: {item['path']} expected={item['sha256']} "
            f"actual={actual}"
        )
    return path


def _load_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ContractError(f"invalid record at {path}:{line_number}") from exc
        body = dict(record)
        declared = body.pop("record_id", None)
        expected = f"dlr1-{canonical_json_sha256(body)[:24]}"
        if declared != expected:
            raise ContractError(f"record digest mismatch at {path}:{line_number}")
        window_id = record["window"]["window_id"]
        if window_id in records:
            raise ContractError(f"duplicate window identity in {path}: {window_id}")
        records[window_id] = record
    return records


def _validate_profile_run(
    root: Path,
    relative: str,
    *,
    expected_engine: str,
    expected_commit: str,
    expected_role: str,
    expected_limit_per_detector: int,
    required_detectors: list[str],
) -> dict[str, Any]:
    directory = _root_member(root, relative)
    for name in PROFILE_FILES:
        if not (directory / name).is_file():
            raise ContractError(f"incomplete profile snapshot: {directory / name}")

    manifest = _read_json(directory / "run_manifest.json")
    body = dict(manifest)
    declared = body.pop("manifest_sha256", None)
    if declared != canonical_json_sha256(body):
        raise ContractError(f"profile manifest digest mismatch: {relative}")
    if manifest.get("scientific_engine") != expected_engine:
        raise ContractError(f"unexpected profile engine: {relative}")
    if manifest.get("prospective") is not False or manifest.get("prefilter") != "none":
        raise ContractError("phase-zero profile must use exact historical no-prefilter replay")
    if manifest.get("roles") != [expected_role]:
        raise ContractError("profile role does not match contract")
    if manifest.get("limit_per_detector") != expected_limit_per_detector:
        raise ContractError("profile detector cap does not match contract")
    code_state = manifest["runtime_provenance"]["code_state"]
    if code_state.get("commit") != expected_commit or code_state.get("tracked_dirty") is not False:
        raise ContractError("profile does not bind the clean frozen code commit")

    records = _load_records(directory / "records.jsonl")
    summary = _read_json(directory / "summary.json")
    executor = summary["executor"]
    if summary.get("status") != "complete":
        raise ContractError(f"profile run not complete: {relative}")
    if executor.get("drops") != 0 or executor.get("deferred") != 0:
        raise ContractError(f"profile run dropped or deferred work: {relative}")
    if executor.get("failures") or executor.get("submitted") != executor.get("written"):
        raise ContractError(f"profile run has failures or incomplete writes: {relative}")
    if summary.get("records_total") != len(records) or executor.get("written") != len(records):
        raise ContractError(f"profile record count mismatch: {relative}")

    detectors = Counter(record["window"]["detector"] for record in records.values())
    expected_counts = {detector: expected_limit_per_detector for detector in required_detectors}
    if dict(sorted(detectors.items())) != dict(sorted(expected_counts.items())):
        raise ContractError(f"profile is not detector-balanced: {relative}")
    for record in records.values():
        if expected_role not in record["evidence"].get("roles", []):
            raise ContractError(f"profile record lacks required role: {relative}")

    artifacts = {
        name: {
            "path": f"{relative}/{name}",
            "sha256": sha256_file(directory / name),
        }
        for name in PROFILE_FILES
    }
    return {
        "manifest": manifest,
        "summary": summary,
        "records": records,
        "artifacts": artifacts,
    }


def _float32_bytes(value: float) -> str:
    return struct.pack("<f", float(value)).hex()


def _profile_equivalence(
    canonical: dict[str, Any], shared: dict[str, Any]
) -> dict[str, Any]:
    canonical_ids = set(canonical["records"])
    shared_ids = set(shared["records"])
    if canonical_ids != shared_ids:
        raise ContractError("canonical/shared profile identity sets differ")
    if canonical["manifest"]["representation"] != shared["manifest"]["representation"]:
        raise ContractError("canonical/shared representation contracts differ")

    mismatches: Counter[str] = Counter()
    score_max_abs_delta = {"native": 0.0, "primary": 0.0}
    required_evidence = (
        "strain_sha256",
        "image_sha256",
        "primary_top_k_sha256",
        "primary_mil_vector_sha256",
    )
    for window_id in sorted(canonical_ids):
        left = canonical["records"][window_id]
        right = shared["records"][window_id]
        for key in ("window", "representation_sha256", "disposition", "defer_reason"):
            if left[key] != right[key]:
                mismatches[key] += 1
        for key in required_evidence:
            if left["evidence"].get(key) != right["evidence"].get(key):
                mismatches[key] += 1
        if left["evidence"].get("primary_top_k_indices") != right["evidence"].get(
            "primary_top_k_indices"
        ):
            mismatches["primary_top_k_indices"] += 1
        for score_name in ("native", "primary"):
            left_score = float(left["scores"][score_name])
            right_score = float(right["scores"][score_name])
            score_max_abs_delta[score_name] = max(
                score_max_abs_delta[score_name], abs(left_score - right_score)
            )
            if _float32_bytes(left_score) != _float32_bytes(right_score):
                mismatches[f"{score_name}_float32_bytes"] += 1

    return {
        "windows": len(canonical_ids),
        "detectors": dict(
            sorted(
                Counter(
                    row["window"]["detector"]
                    for row in canonical["records"].values()
                ).items()
            )
        ),
        "mismatches": dict(sorted(mismatches.items())),
        "max_abs_score_delta": score_max_abs_delta,
        "pass": not mismatches,
    }


def _latency_summary(summary: dict[str, Any]) -> dict[str, float]:
    values = np.asarray(summary["executor"]["latency_s"], dtype=np.float64)
    return {
        "elapsed_s": float(summary["executor"]["elapsed_s"]),
        "throughput_windows_per_s": float(len(values) / summary["executor"]["elapsed_s"]),
        "latency_p50_s": float(np.percentile(values, 50)),
        "latency_p95_s": float(np.percentile(values, 95)),
        "latency_max_s": float(np.max(values)),
    }


def _isolated_bottleneck_profile(root: Path, cost: dict[str, Any]) -> dict[str, Any]:
    ledger_ref = cost["ledger"]
    ledger_path = _root_member(root, ledger_ref["path"])
    if sha256_file(ledger_path) != ledger_ref["sha256"]:
        raise ContractError("v7 cost ledger hash mismatch")
    rows = [
        json.loads(line)["sequential_isolated"]
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != int(ledger_ref["record_count"]):
        raise ContractError("v7 cost ledger record count mismatch")

    names = ("q_transform_s", "rendering_s", "score_total_s", "avoidable_exact_path_s")
    statistics: dict[str, dict[str, float]] = {}
    for name in names:
        values = np.asarray([row[name] for row in rows], dtype=np.float64)
        statistics[name] = {
            "mean_s": float(np.mean(values)),
            "median_s": float(np.median(values)),
            "p95_s": float(np.percentile(values, 95)),
        }
    total_mean = statistics["avoidable_exact_path_s"]["mean_s"]
    fractions = {
        name: statistics[name]["mean_s"] / total_mean
        for name in ("q_transform_s", "rendering_s", "score_total_s")
    }
    return {
        "windows": len(rows),
        "statistics": statistics,
        "mean_fraction_of_avoidable_exact_path": fractions,
        "dominant_measured_stage": max(fractions, key=fractions.get),
        "not_separately_measured": [
            "dino_forward_within_score_total_s",
            "index_scoring_within_score_total_s",
            "result_materialization_within_score_total_s",
            "cold_model_start",
            "peak_cpu_memory",
            "peak_gpu_memory",
            "disk_io_for_cache_candidates"
        ],
    }


def _capacity_audit(root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    cost = _read_json(
        root
        / "artifacts/dante_light/prefilter_l4_v7_risk_calibration/cost_reaudit_summary_v7.json"
    )
    o4b_summary = _read_json(root / "runs/dante_light/o4b_v2/shared/summary.json")
    o4b_canonical_summary = _read_json(
        root / "runs/dante_light/o4b_v2/canonical/summary.json"
    )
    o4b_records = _load_records(root / "runs/dante_light/o4b_v2/shared/records.jsonl")
    prospective = _read_json(root / "artifacts/dante_light/prospective_validation_v1.json")

    prospective_hashes = {
        item["path"]: item["sha256"] for item in prospective["artifacts"]
    }
    for relative in (
        "runs/dante_light/o4b_v2/canonical/summary.json",
        "runs/dante_light/o4b_v2/shared/summary.json",
        "runs/dante_light/o4b_v2/shared/records.jsonl",
    ):
        if prospective_hashes.get(relative) != sha256_file(root / relative):
            raise ContractError(f"O4b source is not the frozen prospective artifact: {relative}")

    duration = float(contract["capacity_estimands"]["nominal_window_duration_s"])
    detectors = int(contract["capacity_estimands"]["detectors"])
    nominal_rate = detectors / duration
    exact_mean = float(cost["sequential_isolated"]["mean_avoidable_exact_path_s"])
    compute_rate = 1.0 / exact_mean
    staged_elapsed = float(o4b_summary["executor"]["elapsed_s"])
    canonical_elapsed = float(o4b_canonical_summary["executor"]["elapsed_s"])
    staged_windows = int(o4b_summary["executor"]["written"])
    staged_rate = staged_windows / staged_elapsed
    dispositions = Counter(row["disposition"] for row in o4b_records.values())

    if len(o4b_records) != staged_windows or o4b_summary.get("status") != "complete":
        raise ContractError("O4b staged source is incomplete")
    if o4b_summary["executor"].get("drops") != 0 or o4b_summary["executor"].get(
        "failures"
    ):
        raise ContractError("O4b staged source has drops or failures")

    return {
        "nominal_input": {
            "detectors": detectors,
            "nonoverlapping_window_duration_s": duration,
            "windows_per_s": nominal_rate,
        },
        "compute_only": {
            "mean_exact_path_s_per_window": exact_mean,
            "service_rate_windows_per_s": compute_rate,
            "point_estimate_headroom_over_nominal": compute_rate / nominal_rate,
            "excludes": ["data_read", "whitening", "model_load"],
            "interpretation": "point_estimate_not_an_end_to_end_capacity_guarantee",
        },
        "staged_o4b_executor": {
            "windows": staged_windows,
            "elapsed_s": staged_elapsed,
            "throughput_windows_per_s": staged_rate,
            "point_estimate_headroom_over_nominal": staged_rate / nominal_rate,
            "drops": int(o4b_summary["executor"]["drops"]),
            "deferred": int(o4b_summary["executor"]["deferred"]),
            "interpretation": (
                "already_open_cached_shadow_executor_point_estimate; acquisition was separate "
                "and this is not an arrival-process stress test"
            ),
            "canonical_elapsed_s": canonical_elapsed,
            "shared_to_canonical_throughput_ratio": canonical_elapsed / staged_elapsed,
            "shared_end_to_end_speedup_demonstrated": canonical_elapsed > staged_elapsed,
        },
        "human_review": {
            "observed_exact_escalations": int(dispositions.get("ESCALATE", 0)),
            "observed_windows": staged_windows,
            "observed_escalation_fraction": dispositions.get("ESCALATE", 0) / staged_windows,
            "review_completion_timestamps_available": False,
            "operator_service_time_available": False,
            "operator_capacity_status": "UNMEASURED",
        },
        "verdict": "EXACT_COMPUTE_CAPACITY_OBSERVED_OPERATOR_REVIEW_CAPACITY_UNMEASURED",
        "prioritizer_budget_freeze_allowed": False,
    }


def build_result(*, root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    contract = _read_json(root / DEFAULT_CONTRACT.relative_to(ROOT))
    if contract.get("status") != "FROZEN_ENGINEERING_AUDIT_NO_SCIENTIFIC_GATES":
        raise ContractError("phase-zero audit contract is not frozen")
    for item in contract["bound_repository_inputs"]:
        _verify_bound_input(root, item)

    profile = contract["exact_profile"]
    common = {
        "expected_commit": profile["code_commit"],
        "expected_role": profile["role"],
        "expected_limit_per_detector": int(profile["limit_per_detector"]),
        "required_detectors": list(profile["required_detectors"]),
    }
    canonical = _validate_profile_run(
        root,
        profile["canonical_snapshot"],
        expected_engine="canonical",
        **common,
    )
    shared = _validate_profile_run(
        root,
        profile["shared_snapshot"],
        expected_engine="shared_encoder_score_only",
        **common,
    )

    teacher = _read_json(root / "config/dante_light_prefilter_v7_teacher_stability.json")
    representation = canonical["manifest"]["representation"]
    if representation != teacher["teacher_fingerprint"]["representation"]:
        raise ContractError("profile representation differs from the frozen teacher fingerprint")
    if int(representation["top_k"]) <= 0:
        raise ContractError("invalid representation top_k")

    equivalence = _profile_equivalence(canonical, shared)
    if not equivalence["pass"]:
        raise ContractError("canonical/shared exact profile mismatch")

    result: dict[str, Any] = {
        "schema_version": 1,
        "audit_id": contract["audit_id"],
        "status": "PASS_PHASE0_ENGINEERING_AUDIT",
        "contract": {
            "path": DEFAULT_CONTRACT.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(root / DEFAULT_CONTRACT.relative_to(ROOT)),
        },
        "access_boundary": {
            "opened": ["already_open_o4a_threshold_boundary_replay", "already_open_o4b_shadow_v2"],
            "confirmation": [],
            "new_later_epoch_holdout": [],
        },
        "top_k_source_of_truth": {
            "value": int(representation["top_k"]),
            "source": "versioned_representation_contract",
            "profile_code_commit": profile["code_commit"],
            "output_equivalence_on_profile_corpus": True,
        },
        "exact_profile": {
            "scope": profile["interpretation"],
            "equivalence": equivalence,
            "canonical": {
                "artifacts": canonical["artifacts"],
                "performance": _latency_summary(canonical["summary"]),
            },
            "shared_encoder_score_only": {
                "artifacts": shared["artifacts"],
                "performance": _latency_summary(shared["summary"]),
            },
            "isolated_bottleneck_profile": _isolated_bottleneck_profile(
                root,
                _read_json(
                    root
                    / "artifacts/dante_light/prefilter_l4_v7_risk_calibration/cost_reaudit_summary_v7.json"
                ),
            ),
        },
        "capacity_audit": _capacity_audit(root, contract),
        "decision": {
            "default_engine_promoted": False,
            "prioritizer_implemented": False,
            "review_budget_frozen": False,
            "next_checkpoint": "MEASURE_OR_JUSTIFY_HUMAN_REVIEW_CAPACITY_BEFORE_GATE_FREEZE",
        },
        "scientific_boundary": contract["decision_boundary"],
    }
    body = dict(result)
    result["phase0_result_digest"] = canonical_json_sha256(body)
    return result


def verify_result(*, root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    saved = _read_json(root / DEFAULT_RESULT.relative_to(ROOT))
    body = dict(saved)
    declared = body.pop("phase0_result_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("saved phase-zero result digest mismatch")
    expected = build_result(root=root)
    if saved != expected:
        raise ContractError("saved phase-zero result differs from recomputed evidence")
    if not saved["exact_profile"]["equivalence"]["pass"]:
        raise ContractError("phase-zero exact equivalence did not pass")
    if saved["capacity_audit"]["prioritizer_budget_freeze_allowed"] is not False:
        raise ContractError("phase-zero result illegally freezes a review budget")
    return saved


def write_result(*, root: Path = ROOT) -> dict[str, Any]:
    root = Path(root).resolve()
    result = build_result(root=root)
    destination = root / DEFAULT_RESULT.relative_to(ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
