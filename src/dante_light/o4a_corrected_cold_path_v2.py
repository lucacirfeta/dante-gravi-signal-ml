"""Outcome-blind raw-series-cache audit for corrected O4a preprocessing."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import queue
import statistics
import threading
import time
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.evidence import SCORE_ATOL
from src.dante_light.o4a_corrected_execution import _primary_scorer, _score_only
from src.dante_light.o4a_corrected_protocol import ROOT, iter_scan_identities
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.o4a_corrected_cold_path import (
    PRIOR_CANARY_REL,
    RAW_MANIFEST_REL,
    _atomic_json,
    _load_json,
    _load_parent_protocol_v3,
    _raw_rows,
    _write_group_manifests,
)
from src.dante_light.prefilter_v5_protocol import repository_reference


SCHEMA_VERSION = 1
CONTRACT_ID = "dante-o4a-corrected-raw-series-cache-v2"
CONTRACT_REL = "config/dante_o4a_corrected_cold_path_v2.json"
PRIOR_COLD_REL = "config/dante_o4a_corrected_cold_path_v1.json"
COMPACT_REL = "artifacts/dante_light/o4a_v1_parity/corrected_cold_path_benchmark_v2.json"
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_cold_path_v2")


def _excluded_spans(root: Path) -> set[tuple[str, float, float, str]]:
    result = set()
    for relative in (PRIOR_CANARY_REL, PRIOR_COLD_REL):
        value = _load_json(root / relative)
        spans = value["canary"]["spans"] if "canary" in value else value["selection"]["spans"]
        result.update(
            (row["detector"], float(row["gps_start"]), float(row["gps_end"]), row["sha256"])
            for row in spans
        )
    return result


def _select_spans(root: Path, *, protocol_digest: str) -> list[dict[str, Any]]:
    excluded = _excluded_spans(root)
    raw = {
        (row["detector"], float(row["gps_start"]), float(row["gps_end"]), row["sha256"]): row
        for row in _raw_rows(root)
        if float(row["duration_s"]) == 4096.0
        and int(row["physical_copies"][0]["size_bytes"]) >= 100_000_000
    }
    grouped: dict[tuple[str, float, float, str], list[float]] = defaultdict(list)
    for row in iter_scan_identities(root):
        key = (
            row["detector"], float(row["source_span"][0]),
            float(row["source_span"][1]), row["source_sha256"],
        )
        gps = float(row["analysis_gps_start"])
        if (
            key in raw and key not in excluded
            and int(row["overlapping_source_count"]) == 1
            and key[1] + 4.0 <= gps <= key[2] - 36.0
        ):
            grouped[key].append(gps)
    selected = []
    for detector in ("H1", "L1"):
        candidates = sorted(
            (
                hashlib.sha256(f"{protocol_digest}|raw-cache-v2|{key}".encode("ascii")).hexdigest(),
                key, values,
            )
            for key, values in grouped.items()
            if key[0] == detector and len(values) >= 96
        )
        if len(candidates) < 4:
            raise ContractError(f"insufficient fresh raw-cache spans for {detector}")
        for group, (_rank, key, values) in enumerate(candidates[:4]):
            raw_row = raw[key]
            physical = sorted(raw_row["physical_copies"], key=lambda item: item["relative_path"])[0]
            gps = sorted(
                values,
                key=lambda value: hashlib.sha256(
                    f"{protocol_digest}|raw-cache-window-v2|{detector}|{value:.9f}".encode("ascii")
                ).hexdigest(),
            )[:96]
            selected.append(
                {
                    "group": group, "detector": detector,
                    "gps_start": key[1], "gps_end": key[2], "sha256": key[3],
                    "size_bytes": int(physical["size_bytes"]),
                    "relative_path": physical["relative_path"],
                    "expected_gps_starts": sorted(gps),
                    "expected_gps_digest": canonical_json_sha256(sorted(gps)),
                }
            )
    return sorted(selected, key=lambda row: (row["group"], row["detector"]))


def build_contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = _load_parent_protocol_v3(root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    spans = _select_spans(root, protocol_digest=protocol["protocol_digest"])
    references = {
        name: repository_reference(root, root / path)
        for name, path in {
            "protocol": "config/dante_o4a_corrected_protocol_v3.json",
            "runtime": "config/dante_o4a_corrected_runtime_v1.json",
            "raw_manifest": RAW_MANIFEST_REL,
            "prior_warm_canary": PRIOR_CANARY_REL,
            "prior_cold_contract": PRIOR_COLD_REL,
            "patch_producer": "src/core/patch_producer.py",
            "implementation": "src/dante_light/o4a_corrected_cold_path_v2.py",
            "runner": "scripts/benchmark_dante_o4a_corrected_cold_path_v2.py",
        }.items()
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_RAW_SERIES_CACHE_CONTRACT",
        "contract_id": CONTRACT_ID,
        "protocol_digest": protocol["protocol_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "selection": {
            "outcomes_used": [], "all_prior_canaries_excluded": True,
            "groups": 4, "spans_per_detector_per_group": 1,
            "windows_per_span": 96, "spans": spans,
            "span_digest": canonical_json_sha256(spans),
        },
        "benchmark": {
            "arms": {
                "uncached": {"executor_backend": "process", "raw_series_cache_files": 0},
                "cache3": {"executor_backend": "process", "raw_series_cache_files": 3},
            },
            "workers_per_detector": 8, "batch_size": 32,
            "detector_mode": "parallel_shared_scorer",
            "group_orders": {
                "0": ["uncached", "cache3"], "1": ["cache3", "uncached"],
                "2": ["uncached", "cache3"], "3": ["cache3", "uncached"],
            },
            "authoritative_cold_metric": "median_first_position_windows_per_second",
            "promotion": {
                "baseline": "uncached", "candidate": "cache3",
                "minimum_speedup": 2.0, "source": PRIOR_CANARY_REL,
                "no_pass": "STOP_NO_REFREEZE",
            },
            "equivalence": {
                "detector_gps": "exact", "image_sha256": "exact",
                "score_atol": SCORE_ATOL, "score_rtol": 0.0,
            },
        },
        "scientific_boundary": {
            "candidate_scores_or_dispositions_inspected": False,
            "thresholds_or_taxonomy_accessed": False,
            "hash_verification_preserved": True,
            "whitening_context_preserved": True,
            "performance_only": True,
        },
        "references": references,
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_contract(value: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    expected = build_contract(root)
    if dict(value) != expected:
        raise ContractError("raw-series-cache contract is stale")
    return dict(value)


def _consume_group(
    *, raw_root: Path, run_dir: Path, contract: Mapping[str, Any],
    group: int, arm: str, scorer: Any
) -> dict[str, Any]:
    from src.core.patch_producer import PatchProducer, _sha256_path_cached

    spans = [row for row in contract["selection"]["spans"] if row["group"] == group]
    manifests = _write_group_manifests(run_dir, spans)
    config = contract["benchmark"]["arms"][arm]
    output_queue: queue.Queue[tuple[str, Any, Any]] = queue.Queue(maxsize=4)

    def produce(detector: str) -> None:
        row = next(item for item in spans if item["detector"] == detector)
        expected = set(float(value) for value in row["expected_gps_starts"])
        grid = set(np.arange(float(row["gps_start"]), float(row["gps_end"]), 32.0))
        try:
            producer = PatchProducer(
                raw_root, detector, workers=8, batch_size=32,
                raw_manifest=manifests[detector], raw_root=raw_root,
                manifest_targets=True, incomplete_context_policy="record_and_skip",
                excluded_gps_starts=sorted(grid - expected), worker_failure_policy="raise",
                executor_backend=config["executor_backend"],
                raw_series_cache_files=int(config["raw_series_cache_files"]),
            )
            for gps, images in producer:
                output_queue.put((detector, gps, images))
        except BaseException as exc:
            output_queue.put((detector, exc, None))
        finally:
            output_queue.put((detector, None, None))

    _sha256_path_cached.cache_clear()
    started = time.perf_counter()
    threads = [threading.Thread(target=produce, args=(detector,), daemon=True) for detector in ("H1", "L1")]
    for thread in threads:
        thread.start()
    remaining, output = 2, []
    while remaining:
        detector, payload, images = output_queue.get()
        if payload is None:
            remaining -= 1
        elif isinstance(payload, BaseException):
            raise ContractError(f"raw-cache producer failed for {detector}") from payload
        else:
            scores = _score_only(scorer, images)
            output.extend(
                (detector, float(gps), hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(), np.float32(score).tobytes().hex())
                for gps, image, score in zip(payload, images, scores, strict=True)
            )
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started
    output.sort(key=lambda row: (row[0], row[1]))
    return {
        "group": group, "arm": arm, "window_count": len(output),
        "identities": [[row[0], row[1]] for row in output],
        "image_sha256": [row[2] for row in output],
        "score_float32_hex": [row[3] for row in output],
        "elapsed_s": elapsed, "windows_per_s": len(output) / elapsed,
    }


def run_benchmark(
    *, root: Path = ROOT, raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT, device: str = "cuda"
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = validate_contract(_load_json(root / CONTRACT_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = canonical_json_sha256({"contract": contract["contract_digest"], "runtime": runtime["runtime_environment"]["environment_digest"]})
    run_dir = external_root.resolve() / f"benchmark_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    scorer = _primary_scorer(root=root, protocol=_load_parent_protocol_v3(root), device=device)
    records = []
    for group in range(4):
        current = {}
        for position, arm in enumerate(contract["benchmark"]["group_orders"][str(group)]):
            row = _consume_group(raw_root=raw_root.resolve(), run_dir=run_dir, contract=contract, group=group, arm=arm, scorer=scorer)
            row["position"] = position
            current[arm] = row
            records.append(row)
        baseline, candidate = current["uncached"], current["cache3"]
        if baseline["identities"] != candidate["identities"] or baseline["image_sha256"] != candidate["image_sha256"]:
            raise ContractError("raw-series cache changed identities or images")
        left = np.asarray([np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0] for value in baseline["score_float32_hex"]])
        right = np.asarray([np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0] for value in candidate["score_float32_hex"]])
        delta = float(np.max(np.abs(left.astype(np.float64) - right.astype(np.float64))))
        if not math.isfinite(delta) or delta > SCORE_ATOL:
            raise ContractError("raw-series cache changed scores")
        for row in (baseline, candidate):
            row["equivalence"] = {"identities_exact": True, "images_exact": True, "max_abs_score_delta": delta, "pass": True}
    cold = {
        arm: statistics.median(row["windows_per_s"] for row in records if row["arm"] == arm and row["position"] == 0)
        for arm in ("uncached", "cache3")
    }
    speedup = cold["cache3"] / cold["uncached"]
    status = "PASS_RAW_SERIES_CACHE" if speedup >= float(contract["benchmark"]["promotion"]["minimum_speedup"]) else "STOP_NO_REFREEZE"
    body = {
        "schema_version": SCHEMA_VERSION, "status": status, "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "records": records, "median_first_position_windows_per_s": cold,
        "cache3_speedup_over_uncached": speedup,
        "outcome_access": {"scores": False, "dispositions": False, "taxonomy": False},
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "cold_path_summary.json", result)
    compact = dict(result)
    compact["records"] = [
        {key: row[key] for key in ("group", "arm", "position", "window_count", "elapsed_s", "windows_per_s", "equivalence")}
        for row in records
    ]
    compact_body = dict(compact)
    compact_body.pop("artifact_digest")
    compact["artifact_digest"] = canonical_json_sha256(compact_body)
    _atomic_json(root / COMPACT_REL, compact)
    return result, run_dir
