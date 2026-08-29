"""Persistent-pool and detector-parallel O4a performance audit."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import queue
import statistics
import subprocess
import threading
import time
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.evidence import SCORE_ATOL
from src.dante_light.o4a_corrected_execution import _primary_scorer, _score_only
from src.dante_light.o4a_corrected_performance import (
    RAW_MANIFEST_REL,
    _canary_spans,
)
from src.dante_light.o4a_corrected_protocol import (
    OUTPUT_REL as PROTOCOL_REL,
    ROOT,
    validate_corrected_protocol,
)
from src.dante_light.o4a_corrected_runtime import (
    OUTPUT_REL as RUNTIME_REL,
    load_canonical_runtime_contract,
)
from src.dante_light.prefilter_v5_protocol import repository_reference


SCHEMA_VERSION = 2
CONTRACT_ID = "dante-o4a-corrected-persistent-pool-performance-v2"
CONTRACT_REL = "config/dante_o4a_corrected_performance_v2.json"
COMPACT_RESULT_REL = (
    "artifacts/dante_light/o4a_v1_parity/corrected_performance_benchmark_v2.json"
)
V1_RESULT_REL = (
    "artifacts/dante_light/o4a_v1_parity/corrected_performance_benchmark.json"
)
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_performance_v2")
CONFIGURATIONS = (
    {
        "id": "serial_2x8",
        "detector_mode": "serial",
        "workers_per_detector": 2,
        "batch_size": 8,
    },
    {
        "id": "serial_8x32",
        "detector_mode": "serial",
        "workers_per_detector": 8,
        "batch_size": 32,
    },
    {
        "id": "parallel_4x16",
        "detector_mode": "parallel_shared_scorer",
        "workers_per_detector": 4,
        "batch_size": 16,
    },
    {
        "id": "parallel_8x32",
        "detector_mode": "parallel_shared_scorer",
        "workers_per_detector": 8,
        "batch_size": 32,
    },
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _reference_is_available(root: Path, reference: Mapping[str, Any]) -> bool:
    path = str(reference["path"])
    expected = str(reference["sha256"])
    if repository_reference(root, root / path) == dict(reference):
        return True
    try:
        commits = subprocess.check_output(
            ["git", "log", "--format=%H", "--all", "--", path],
            cwd=root,
            text=True,
        ).splitlines()
        return any(
            hashlib.sha256(
                subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=root)
            ).hexdigest()
            == expected
            for commit in commits
        )
    except (OSError, subprocess.SubprocessError):
        return False


def build_performance_contract_v2(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = validate_corrected_protocol(_load_json(root / PROTOCOL_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    v1 = _load_json(root / V1_RESULT_REL)
    if (
        v1["status"] != "STOP_NO_REFREEZE"
        or v1["artifact_digest"]
        != "ca36cae1a75c2df5a79960740dc74d71596faaa9023a9e3d66fbbbbb7f127e3e"
        or int(v1["database_probe"]["selected_commit_rows"]) != 1024
    ):
        raise ContractError("persistent-pool audit lacks the frozen v1 negative result")
    canary = _canary_spans(
        root,
        protocol_digest=protocol["protocol_digest"],
        spans_per_detector=8,
        windows_per_span=96,
    )
    references = {
        name: repository_reference(root, root / relative)
        for name, relative in {
            "protocol": PROTOCOL_REL,
            "runtime": RUNTIME_REL,
            "raw_manifest": RAW_MANIFEST_REL,
            "patch_producer": "src/core/patch_producer.py",
            "v1_negative_result": V1_RESULT_REL,
            "implementation": "src/dante_light/o4a_corrected_performance_v2.py",
            "runner": "scripts/benchmark_dante_o4a_corrected_performance_v2.py",
        }.items()
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_PERSISTENT_POOL_CONTRACT",
        "contract_id": CONTRACT_ID,
        "protocol_digest": protocol["protocol_digest"],
        "runtime_contract_digest": runtime["contract_digest"],
        "canary": {
            "selector": "sha256_ordered_eligible_unique_source_windows",
            "spans_per_detector": 8,
            "windows_per_span": 96,
            "spans": canary,
            "canary_digest": canonical_json_sha256(canary),
            "window_count": sum(len(row["expected_gps_starts"]) for row in canary),
        },
        "benchmark": {
            "configurations": list(CONFIGURATIONS),
            "warmup_repetitions": 1,
            "measured_repetitions": 2,
            "configuration_order": "cyclic_rotation_by_repetition",
            "producer_pool_lifetime": "one_pool_per_detector_per_configuration_repetition",
            "parallel_shared_scorer": (
                "one_main_process_CUDA_scorer_consumes_two_bounded_detector_queues"
            ),
            "queue_depth_batches_per_detector": 2,
            "authoritative_metric": "median_end_to_end_windows_per_second",
            "equivalence": {
                "detector_gps_set": "exact",
                "image_sha256": "exact_by_detector_gps",
                "score_atol": SCORE_ATOL,
                "score_rtol": 0.0,
                "all_repetitions_must_pass": True,
            },
            "promotion": {
                "baseline_id": "serial_2x8",
                "minimum_speedup_over_baseline": 2.0,
                "selection": "fastest_passing_configuration_by_authoritative_metric",
                "tie_break": "fewer_total_workers_then_smaller_batch_then_serial",
                "no_passing_candidate": "STOP_NO_REFREEZE",
            },
        },
        "executor_candidate": {
            "database_commit_rows": 1024,
            "database_evidence_artifact_digest": v1["artifact_digest"],
            "database_journal_mode": "WAL",
            "database_synchronous": "FULL",
            "ephemeral_staging_not_promoted": True,
            "staging_reason": (
                "v1 measured only 1.058x over direct 8x32 and did not justify "
                "production complexity"
            ),
        },
        "outcome_boundary": {
            "candidate_scores_inspected": False,
            "candidate_dispositions_inspected": False,
            "thresholds_loaded_or_compared": False,
            "taxonomy_or_scientific_labels_loaded": False,
            "score_values_used_only_for_cross_configuration_equivalence": True,
            "scientific_protocol_change_allowed": False,
            "score_tolerance_change_allowed": False,
        },
        "references": references,
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_performance_contract_v2(
    value: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    payload = dict(value)
    digest = payload.pop("contract_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("persistent-pool contract self-digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_OUTCOME_BLIND_PERSISTENT_POOL_CONTRACT"
        or value.get("contract_id") != CONTRACT_ID
        or value["benchmark"]["configurations"] != list(CONFIGURATIONS)
        or float(value["benchmark"]["equivalence"]["score_atol"]) != SCORE_ATOL
        or int(value["executor_candidate"]["database_commit_rows"]) != 1024
    ):
        raise ContractError("persistent-pool contract changed")
    protocol = validate_corrected_protocol(_load_json(root / PROTOCOL_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    if (
        value["protocol_digest"] != protocol["protocol_digest"]
        or value["runtime_contract_digest"] != runtime["contract_digest"]
    ):
        raise ContractError("persistent-pool parent contract changed")
    canary = list(value["canary"]["spans"])
    expected = _canary_spans(
        root,
        protocol_digest=protocol["protocol_digest"],
        spans_per_detector=8,
        windows_per_span=96,
    )
    if canary != expected or value["canary"]["canary_digest"] != canonical_json_sha256(canary):
        raise ContractError("persistent-pool canary changed")
    if not all(_reference_is_available(root, row) for row in value["references"].values()):
        raise ContractError("persistent-pool reference is unavailable")
    return dict(value)


def write_performance_contract_v2(root: Path = ROOT) -> dict[str, Any]:
    value = build_performance_contract_v2(root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def load_performance_contract_v2(root: Path = ROOT) -> dict[str, Any]:
    return validate_performance_contract_v2(_load_json(root / CONTRACT_REL), root)


def _write_manifests(
    *, run_dir: Path, contract: Mapping[str, Any]
) -> dict[str, Path]:
    result = {}
    for detector in ("H1", "L1"):
        spans = sorted(
            (row for row in contract["canary"]["spans"] if row["detector"] == detector),
            key=lambda row: float(row["gps_start"]),
        )
        path = run_dir / "manifests" / f"{detector}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for span in spans:
            lines.append(
                json.dumps(
                    {
                        "copy_count": 1,
                        "detector": detector,
                        "duration_s": float(span["gps_end"]) - float(span["gps_start"]),
                        "gps_end": span["gps_end"],
                        "gps_start": span["gps_start"],
                        "physical_copies": [
                            {
                                "relative_path": span["relative_path"],
                                "sha256": span["sha256"],
                                "size_bytes": span["size_bytes"],
                            }
                        ],
                        "sha256": span["sha256"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        result[detector] = path
    return result


def _producer(
    *,
    raw_root: Path,
    manifest: Path,
    detector: str,
    spans: list[Mapping[str, Any]],
    workers: int,
    batch_size: int,
):
    from src.core.patch_producer import PatchProducer, _sha256_path_cached

    expected = {
        float(gps) for span in spans for gps in span["expected_gps_starts"]
    }
    grid = {
        float(gps)
        for span in spans
        for gps in np.arange(float(span["gps_start"]), float(span["gps_end"]), 32.0)
    }
    _sha256_path_cached.cache_clear()
    return PatchProducer(
        raw_root,
        detector,
        workers=workers,
        batch_size=batch_size,
        raw_manifest=manifest,
        raw_root=raw_root,
        manifest_targets=True,
        incomplete_context_policy="record_and_skip",
        excluded_gps_starts=sorted(grid - expected),
        worker_failure_policy="raise",
    )


def _consume_serial(
    *,
    raw_root: Path,
    manifests: Mapping[str, Path],
    contract: Mapping[str, Any],
    configuration: Mapping[str, Any],
    scorer: Any,
) -> tuple[list[tuple[str, float, str, str]], float]:
    import torch

    output = []
    scoring_s = 0.0
    for detector in ("H1", "L1"):
        spans = [row for row in contract["canary"]["spans"] if row["detector"] == detector]
        producer = _producer(
            raw_root=raw_root,
            manifest=manifests[detector],
            detector=detector,
            spans=spans,
            workers=int(configuration["workers_per_detector"]),
            batch_size=int(configuration["batch_size"]),
        )
        for gps_batch, images in producer:
            before = time.perf_counter()
            scores = _score_only(scorer, images)
            torch.cuda.synchronize()
            scoring_s += time.perf_counter() - before
            output.extend(
                (
                    detector,
                    float(gps),
                    hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
                    np.float32(score).tobytes().hex(),
                )
                for gps, image, score in zip(gps_batch, images, scores, strict=True)
            )
    return output, scoring_s


def _consume_parallel(
    *,
    raw_root: Path,
    manifests: Mapping[str, Path],
    contract: Mapping[str, Any],
    configuration: Mapping[str, Any],
    scorer: Any,
) -> tuple[list[tuple[str, float, str, str]], float]:
    import torch

    batch_queue: queue.Queue[tuple[str, Any, Any]] = queue.Queue(
        maxsize=2 * int(contract["benchmark"]["queue_depth_batches_per_detector"])
    )

    def produce(detector: str) -> None:
        try:
            spans = [
                row for row in contract["canary"]["spans"] if row["detector"] == detector
            ]
            producer = _producer(
                raw_root=raw_root,
                manifest=manifests[detector],
                detector=detector,
                spans=spans,
                workers=int(configuration["workers_per_detector"]),
                batch_size=int(configuration["batch_size"]),
            )
            for gps_batch, images in producer:
                batch_queue.put((detector, gps_batch, images))
        except BaseException as exc:
            batch_queue.put((detector, exc, None))
        finally:
            batch_queue.put((detector, None, None))

    threads = [
        threading.Thread(target=produce, args=(detector,), daemon=True)
        for detector in ("H1", "L1")
    ]
    for thread in threads:
        thread.start()
    remaining = 2
    output = []
    scoring_s = 0.0
    while remaining:
        detector, gps_or_error, images = batch_queue.get()
        if gps_or_error is None:
            remaining -= 1
            continue
        if isinstance(gps_or_error, BaseException):
            raise ContractError(f"parallel detector producer failed: {detector}") from gps_or_error
        before = time.perf_counter()
        scores = _score_only(scorer, images)
        torch.cuda.synchronize()
        scoring_s += time.perf_counter() - before
        output.extend(
            (
                detector,
                float(gps),
                hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
                np.float32(score).tobytes().hex(),
            )
            for gps, image, score in zip(gps_or_error, images, scores, strict=True)
        )
    for thread in threads:
        thread.join()
    return output, scoring_s


def _run_configuration(
    *,
    root: Path,
    raw_root: Path,
    run_dir: Path,
    protocol: Mapping[str, Any],
    contract: Mapping[str, Any],
    scorer: Any,
    configuration: Mapping[str, Any],
    repetition: int,
) -> dict[str, Any]:
    manifests = _write_manifests(run_dir=run_dir, contract=contract)
    started = time.perf_counter()
    if configuration["detector_mode"] == "serial":
        output, scoring_s = _consume_serial(
            raw_root=raw_root,
            manifests=manifests,
            contract=contract,
            configuration=configuration,
            scorer=scorer,
        )
    else:
        output, scoring_s = _consume_parallel(
            raw_root=raw_root,
            manifests=manifests,
            contract=contract,
            configuration=configuration,
            scorer=scorer,
        )
    elapsed = time.perf_counter() - started
    output.sort(key=lambda row: (row[0], row[1]))
    expected = sorted(
        (str(span["detector"]), float(gps))
        for span in contract["canary"]["spans"]
        for gps in span["expected_gps_starts"]
    )
    if [(row[0], row[1]) for row in output] != expected:
        raise ContractError("persistent-pool canary identity mismatch")
    body = {
        "configuration": dict(configuration),
        "repetition": repetition,
        "window_count": len(output),
        "identities": [[row[0], row[1]] for row in output],
        "image_sha256": [row[2] for row in output],
        "score_float32_hex": [row[3] for row in output],
        "timing": {
            "scoring_s": scoring_s,
            "end_to_end_s": elapsed,
            "end_to_end_windows_per_s": len(output) / elapsed,
        },
        "runtime_guard": protocol["canonical_runtime"]["environment_digest"],
    }
    return {**body, "record_digest": canonical_json_sha256(body)}


def _decision(
    records: list[Mapping[str, Any]], contract: Mapping[str, Any]
) -> tuple[dict[str, float], dict[str, float], dict[str, Any] | None, str]:
    measured = [row for row in records if row["phase"] == "measured"]
    medians = {
        str(configuration["id"]): statistics.median(
            row["timing"]["end_to_end_windows_per_s"]
            for row in measured
            if row["configuration"]["id"] == configuration["id"]
        )
        for configuration in contract["benchmark"]["configurations"]
    }
    baseline = medians["serial_2x8"]
    speedups = {key: value / baseline for key, value in medians.items()}
    minimum = float(contract["benchmark"]["promotion"]["minimum_speedup_over_baseline"])
    eligible = [
        configuration
        for configuration in contract["benchmark"]["configurations"]
        if configuration["id"] != "serial_2x8"
        and speedups[str(configuration["id"])] >= minimum
    ]
    selected = None
    if eligible:
        selected = min(
            eligible,
            key=lambda configuration: (
                -medians[str(configuration["id"])],
                int(configuration["workers_per_detector"])
                * (2 if configuration["detector_mode"] != "serial" else 1),
                int(configuration["batch_size"]),
                configuration["detector_mode"] != "serial",
            ),
        )
    status = "PASS_EQUIVALENCE_AND_PERSISTENT_SELECTION" if selected else "STOP_NO_REFREEZE"
    return medians, speedups, selected, status


def run_performance_benchmark_v2(
    *,
    root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_performance_contract_v2(root)
    protocol = validate_corrected_protocol(_load_json(root / PROTOCOL_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = canonical_json_sha256(
        {
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
            "stage": "outcome_blind_persistent_pool_benchmark",
        }
    )
    run_dir = external_root.resolve() / f"benchmark_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    scorer = _primary_scorer(root=root, protocol=protocol, device=device)
    configs = list(contract["benchmark"]["configurations"])
    warmups = int(contract["benchmark"]["warmup_repetitions"])
    measured = int(contract["benchmark"]["measured_repetitions"])
    records = []
    for repetition in range(warmups + measured):
        rotation = repetition % len(configs)
        current = {}
        for configuration in configs[rotation:] + configs[:rotation]:
            current[str(configuration["id"])] = _run_configuration(
                root=root,
                raw_root=raw_root.resolve(),
                run_dir=run_dir,
                protocol=protocol,
                contract=contract,
                scorer=scorer,
                configuration=configuration,
                repetition=repetition,
            )
        baseline = current["serial_2x8"]
        baseline_scores = np.asarray(
            [
                np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0]
                for value in baseline["score_float32_hex"]
            ]
        )
        for configuration in configs:
            row = current[str(configuration["id"])]
            if (
                row["identities"] != baseline["identities"]
                or row["image_sha256"] != baseline["image_sha256"]
            ):
                raise ContractError("persistent-pool candidate changed identities or images")
            scores = np.asarray(
                [
                    np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0]
                    for value in row["score_float32_hex"]
                ]
            )
            delta = float(
                np.max(
                    np.abs(
                        scores.astype(np.float64)
                        - baseline_scores.astype(np.float64)
                    )
                )
            )
            if not math.isfinite(delta) or delta > SCORE_ATOL:
                raise ContractError("persistent-pool candidate exceeded score tolerance")
            row["equivalence"] = {
                "identities_exact": True,
                "images_exact": True,
                "max_abs_score_delta": delta,
                "score_atol": SCORE_ATOL,
                "pass": True,
            }
            row["phase"] = "warmup" if repetition < warmups else "measured"
            records.append(row)
    medians, speedups, selected, status = _decision(records, contract)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "records": records,
        "median_end_to_end_windows_per_s": medians,
        "speedup_over_baseline": speedups,
        "selected_configuration": selected,
        "database_commit_rows": contract["executor_candidate"]["database_commit_rows"],
        "outcome_access": contract["outcome_boundary"],
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "performance_benchmark_v2.json", result)
    compact = dict(result)
    compact["records"] = [
        {
            "configuration": row["configuration"],
            "repetition": row["repetition"],
            "phase": row["phase"],
            "window_count": row["window_count"],
            "timing": row["timing"],
            "equivalence": row["equivalence"],
            "record_digest": row["record_digest"],
        }
        for row in records
    ]
    _atomic_json(root / COMPACT_RESULT_REL, compact)
    return result, run_dir


def verify_performance_result_v2(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_performance_contract_v2(root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    run_key = canonical_json_sha256(
        {
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
            "stage": "outcome_blind_persistent_pool_benchmark",
        }
    )
    path = external_root.resolve() / f"benchmark_{run_key}" / "performance_benchmark_v2.json"
    result = _load_json(path)
    payload = dict(result)
    if payload.pop("artifact_digest", None) != canonical_json_sha256(payload):
        raise ContractError("persistent-pool result self-digest mismatch")
    expected_count = len(CONFIGURATIONS) * (
        int(contract["benchmark"]["warmup_repetitions"])
        + int(contract["benchmark"]["measured_repetitions"])
    )
    if len(result["records"]) != expected_count:
        raise ContractError("persistent-pool result cardinality mismatch")
    for repetition in range(3):
        rows = {
            row["configuration"]["id"]: row
            for row in result["records"]
            if int(row["repetition"]) == repetition
        }
        baseline = rows["serial_2x8"]
        baseline_scores = np.asarray(
            [
                np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0]
                for value in baseline["score_float32_hex"]
            ]
        )
        for row in rows.values():
            core = {
                key: value
                for key, value in row.items()
                if key not in {"equivalence", "phase", "record_digest"}
            }
            if row["record_digest"] != canonical_json_sha256(core):
                raise ContractError("persistent-pool record digest mismatch")
            if (
                row["identities"] != baseline["identities"]
                or row["image_sha256"] != baseline["image_sha256"]
            ):
                raise ContractError("persistent-pool image evidence changed")
            scores = np.asarray(
                [
                    np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0]
                    for value in row["score_float32_hex"]
                ]
            )
            delta = float(
                np.max(
                    np.abs(
                        scores.astype(np.float64)
                        - baseline_scores.astype(np.float64)
                    )
                )
            )
            if delta != float(row["equivalence"]["max_abs_score_delta"]) or delta > SCORE_ATOL:
                raise ContractError("persistent-pool score evidence changed")
    medians, speedups, selected, status = _decision(result["records"], contract)
    if (
        medians != result["median_end_to_end_windows_per_s"]
        or speedups != result["speedup_over_baseline"]
        or selected != result["selected_configuration"]
        or status != result["status"]
    ):
        raise ContractError("persistent-pool decision changed")
    compact = _load_json(root / COMPACT_RESULT_REL)
    if compact["artifact_digest"] != result["artifact_digest"]:
        raise ContractError("persistent-pool compact result is not bound")
    return result
