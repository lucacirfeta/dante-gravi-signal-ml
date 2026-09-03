"""Outcome-blind sustained audit on representative O4a manifest topology."""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import queue
import threading
import time
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.evidence import SCORE_ATOL
from src.dante_light.o4a_corrected_execution import (
    _ScanIdentityLookup,
    _primary_scorer,
    _score_only,
)
from src.dante_light.o4a_corrected_protocol import ROOT
from src.dante_light.o4a_corrected_runtime import load_canonical_runtime_contract
from src.dante_light.o4a_corrected_cold_path import (
    RAW_MANIFEST_REL,
    _atomic_json,
    _load_json,
    _load_parent_protocol_v3,
    _raw_rows,
)
from src.dante_light.o4a_corrected_cold_path_attribution import (
    CONTRACT_REL as ATTRIBUTION_CONTRACT_REL,
    _excluded_spans,
)
from src.dante_light.prefilter_v5_protocol import repository_reference


SCHEMA_VERSION = 1
CONTRACT_ID = "dante-o4a-corrected-sustained-manifest-v1"
CONTRACT_REL = "config/dante_o4a_corrected_sustained_v1.json"
COMPACT_REL = (
    "artifacts/dante_light/o4a_v1_parity/"
    "corrected_sustained_manifest_audit.json"
)
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_sustained"
)
TARGET_SPANS_PER_DETECTOR = 32
ROLLING_OUTPUT_ROWS = 512


def _coverage_components(rows: list[Mapping[str, Any]]) -> list[list[float]]:
    merged: list[list[float]] = []
    for row in sorted(rows, key=lambda item: float(item["gps_start"])):
        start, end = float(row["gps_start"]), float(row["gps_end"])
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [[start, end] for start, end in merged]


def _window_is_covered(
    components: list[list[float]], gps: float
) -> bool:
    required_start, required_end = gps - 4.0, gps + 36.0
    return any(
        start <= required_start and required_end <= end
        for start, end in components
    )


def _bundle_metrics(
    rows: list[Mapping[str, Any]], invalid_gps: set[float]
) -> dict[str, Any]:
    components = _coverage_components(rows)
    emitted: list[float] = []
    per_span: list[list[float]] = []
    for row in rows:
        values = []
        start, end = float(row["gps_start"]), float(row["gps_end"])
        current = start
        while current + 32.0 <= end:
            if current not in invalid_gps and _window_is_covered(components, current):
                values.append(current)
                emitted.append(current)
            current += 32.0
        per_span.append(values)
    counter = Counter(emitted)
    durations = sorted({float(row["duration_s"]) for row in rows})
    overlap_pairs = sum(
        float(right["gps_start"]) < float(left["gps_end"])
        for left, right in zip(rows, rows[1:], strict=False)
    )
    return {
        "components": components,
        "per_span_expected_gps": per_span,
        "expected_output_count": len(emitted),
        "expected_unique_identity_count": len(counter),
        "expected_duplicate_output_count": len(emitted) - len(counter),
        "expected_duplication_factor": len(emitted) / len(counter),
        "duration_values_s": durations,
        "overlap_adjacent_pair_count": overlap_pairs,
        "expected_identity_multiset_digest": canonical_json_sha256(
            [[gps, count] for gps, count in sorted(counter.items())]
        ),
    }


def _select_bundles(root: Path, *, protocol_digest: str) -> list[dict[str, Any]]:
    excluded = _excluded_spans(root)
    lookup = _ScanIdentityLookup(root=root)
    # Keep the complete frozen manifest topology.  Filtering short files by
    # size would silently remove the mixed-duration and overlap cases this
    # sustained audit is specifically intended to exercise.
    raw = _raw_rows(root)
    selected: list[dict[str, Any]] = []
    for detector in ("H1", "L1"):
        rows = sorted(
            (row for row in raw if row["detector"] == detector),
            key=lambda row: (float(row["gps_start"]), float(row["gps_end"])),
        )
        invalid_gps = lookup.invalid_gps_starts(detector)
        candidates = []
        for index in range(len(rows) - TARGET_SPANS_PER_DETECTOR + 1):
            bundle = rows[index : index + TARGET_SPANS_PER_DETECTOR]
            keys = [
                (
                    detector,
                    float(row["gps_start"]),
                    float(row["gps_end"]),
                    str(row["sha256"]),
                )
                for row in bundle
            ]
            if any(key in excluded for key in keys):
                continue
            metrics = _bundle_metrics(bundle, invalid_gps)
            if (
                len(metrics["duration_values_s"]) < 2
                or metrics["overlap_adjacent_pair_count"] < 1
                or metrics["expected_output_count"] < 2_000
            ):
                continue
            rank = hashlib.sha256(
                (
                    f"{protocol_digest}|sustained-manifest-v1|{detector}|"
                    f"{keys[0][1]:.9f}|{keys[-1][2]:.9f}"
                ).encode("ascii")
            ).hexdigest()
            candidates.append((rank, bundle, metrics))
        candidates.sort(key=lambda item: item[0])
        if not candidates:
            raise ContractError(f"no fresh representative sustained bundle for {detector}")
        _rank, bundle, metrics = candidates[0]
        for position, (row, expected_gps) in enumerate(
            zip(bundle, metrics.pop("per_span_expected_gps"), strict=True)
        ):
            physical = sorted(
                row["physical_copies"], key=lambda item: item["relative_path"]
            )[0]
            selected.append(
                {
                    "detector": detector,
                    "bundle_position": position,
                    "gps_start": float(row["gps_start"]),
                    "gps_end": float(row["gps_end"]),
                    "duration_s": float(row["duration_s"]),
                    "sha256": str(row["sha256"]),
                    "size_bytes": int(physical["size_bytes"]),
                    "relative_path": str(physical["relative_path"]),
                    "expected_gps_starts": expected_gps,
                    "bundle_metrics": metrics,
                }
            )
    return sorted(selected, key=lambda row: (row["detector"], row["bundle_position"]))


def build_contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = _load_parent_protocol_v3(root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    spans = _select_bundles(root, protocol_digest=protocol["protocol_digest"])
    references = {
        name: repository_reference(root, root / path)
        for name, path in {
            "protocol": "config/dante_o4a_corrected_protocol_v3.json",
            "runtime": "config/dante_o4a_corrected_runtime_v1.json",
            "raw_manifest": RAW_MANIFEST_REL,
            "attribution_contract": ATTRIBUTION_CONTRACT_REL,
            "patch_producer": "src/core/patch_producer.py",
            "execution": "src/dante_light/o4a_corrected_execution.py",
            "implementation": "src/dante_light/o4a_corrected_sustained_audit.py",
            "runner": "scripts/benchmark_dante_o4a_corrected_sustained.py",
        }.items()
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_SUSTAINED_MANIFEST_CONTRACT",
        "contract_id": CONTRACT_ID,
        "protocol_digest": protocol["protocol_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "selection": {
            "outcomes_used": [],
            "all_prior_canaries_excluded": True,
            "spans_per_detector": TARGET_SPANS_PER_DETECTOR,
            "requires_mixed_durations": True,
            "requires_overlap": True,
            "spans": spans,
            "span_digest": canonical_json_sha256(spans),
        },
        "benchmark": {
            "mode": "production_patch_producer_plus_score_only",
            "workers_per_detector": 8,
            "batch_size": 32,
            "detector_mode": "parallel_shared_scorer",
            "rolling_output_rows": ROLLING_OUTPUT_ROWS,
            "raw_series_cache_files": 0,
            "executor_backend": "process",
            "promotion_allowed": False,
            "equivalence": {
                "duplicate_detector_gps_image_sha256": "exact",
                "duplicate_score_atol": SCORE_ATOL,
                "duplicate_score_rtol": 0.0,
            },
        },
        "scientific_boundary": {
            "candidate_scores_or_dispositions_inspected": False,
            "thresholds_or_taxonomy_accessed": False,
            "performance_only": True,
            "can_refreeze_protocol": False,
        },
        "references": references,
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_contract(value: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    expected = build_contract(root)
    if dict(value) != expected:
        raise ContractError("sustained manifest contract is stale")
    return dict(value)


def _write_manifests(run_dir: Path, spans: list[Mapping[str, Any]]) -> dict[str, Path]:
    result = {}
    for detector in ("H1", "L1"):
        rows = sorted(
            (row for row in spans if row["detector"] == detector),
            key=lambda row: int(row["bundle_position"]),
        )
        path = run_dir / "manifests" / f"{detector}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = []
        for row in rows:
            value = {
                "detector": detector,
                "gps_start": row["gps_start"],
                "gps_end": row["gps_end"],
                "duration_s": row["duration_s"],
                "sha256": row["sha256"],
                "physical_copies": [{
                    "relative_path": row["relative_path"],
                    "sha256": row["sha256"],
                    "size_bytes": row["size_bytes"],
                }],
            }
            encoded.append(json.dumps(value, sort_keys=True, separators=(",", ":")))
        path.write_text("\n".join(encoded) + "\n", encoding="utf-8", newline="\n")
        result[detector] = path
    return result


def run_benchmark(
    *, root: Path = ROOT, raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT, device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    from src.core.patch_producer import PatchProducer, _sha256_path_cached

    root = root.resolve()
    contract = validate_contract(_load_json(root / CONTRACT_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = canonical_json_sha256({
        "contract": contract["contract_digest"],
        "runtime": runtime["runtime_environment"]["environment_digest"],
    })
    run_dir = external_root.resolve() / f"benchmark_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    spans = list(contract["selection"]["spans"])
    manifests = _write_manifests(run_dir, spans)
    scorer = _primary_scorer(root=root, protocol=_load_parent_protocol_v3(root), device=device)
    lookup = _ScanIdentityLookup(root=root)
    output_queue: queue.Queue[tuple[str, Any, Any]] = queue.Queue(maxsize=4)

    def produce(detector: str) -> None:
        invalid = lookup.invalid_gps_starts(detector)
        try:
            producer = PatchProducer(
                raw_root,
                detector,
                workers=8,
                batch_size=32,
                raw_manifest=manifests[detector],
                raw_root=raw_root,
                manifest_targets=True,
                incomplete_context_policy="record_and_skip",
                excluded_gps_starts=sorted(invalid),
                worker_failure_policy="raise",
                executor_backend="process",
                raw_series_cache_files=0,
            )
            for gps, images in producer:
                output_queue.put((detector, gps, images))
        except BaseException as exc:
            output_queue.put((detector, exc, None))
        finally:
            output_queue.put((detector, None, None))

    _sha256_path_cached.cache_clear()
    started = time.perf_counter()
    threads = [
        threading.Thread(target=produce, args=(detector,), daemon=True)
        for detector in ("H1", "L1")
    ]
    for thread in threads:
        thread.start()
    remaining = 2
    output: list[tuple[str, float, str, float]] = []
    rolling = []
    next_checkpoint = ROLLING_OUTPUT_ROWS
    while remaining:
        detector, payload, images = output_queue.get()
        if payload is None:
            remaining -= 1
            continue
        if isinstance(payload, BaseException):
            raise ContractError(f"sustained producer failed for {detector}") from payload
        scores = _score_only(scorer, images)
        output.extend(
            (
                detector,
                float(gps),
                hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
                float(score),
            )
            for gps, image, score in zip(payload, images, scores, strict=True)
        )
        while len(output) >= next_checkpoint:
            elapsed = time.perf_counter() - started
            rolling.append({
                "output_count": next_checkpoint,
                "elapsed_s": elapsed,
                "cumulative_windows_per_s": next_checkpoint / elapsed,
            })
            next_checkpoint += ROLLING_OUTPUT_ROWS
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started

    actual_counter = Counter((row[0], row[1]) for row in output)
    expected_counter: Counter[tuple[str, float]] = Counter()
    for row in spans:
        expected_counter.update(
            (str(row["detector"]), float(gps))
            for gps in row["expected_gps_starts"]
        )
    if actual_counter != expected_counter:
        raise ContractError("sustained output identity multiset differs from contract")

    duplicate_groups: dict[tuple[str, float], list[tuple[str, float]]] = defaultdict(list)
    for detector, gps, image_hash, score in output:
        duplicate_groups[(detector, gps)].append((image_hash, score))
    max_duplicate_score_delta = 0.0
    duplicate_images_exact = True
    for values in duplicate_groups.values():
        if len(values) < 2:
            continue
        duplicate_images_exact &= len({value[0] for value in values}) == 1
        scores = [value[1] for value in values]
        max_duplicate_score_delta = max(
            max_duplicate_score_delta, max(scores) - min(scores)
        )
    if not duplicate_images_exact or max_duplicate_score_delta > SCORE_ATOL:
        raise ContractError("duplicate manifest identities changed images or scores")

    sorted_output = sorted(output, key=lambda row: (row[0], row[1], row[2], row[3]))
    detector_counts = Counter(row[0] for row in output)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_OUTCOME_BLIND_SUSTAINED_MANIFEST_AUDIT",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "elapsed_s": elapsed,
        "output_count": len(output),
        "unique_identity_count": len(actual_counter),
        "duplicate_output_count": len(output) - len(actual_counter),
        "duplication_factor": len(output) / len(actual_counter),
        "detector_output_counts": dict(sorted(detector_counts.items())),
        "windows_per_s": len(output) / elapsed,
        "unique_identities_per_s": len(actual_counter) / elapsed,
        "rolling": rolling,
        "output_digest": canonical_json_sha256([
            [detector, gps, image_hash, np.float32(score).tobytes().hex()]
            for detector, gps, image_hash, score in sorted_output
        ]),
        "equivalence": {
            "identity_multiset_exact": True,
            "duplicate_images_exact": duplicate_images_exact,
            "max_duplicate_score_delta": max_duplicate_score_delta,
            "pass": True,
        },
        "outcome_access": {"thresholds": False, "dispositions": False, "taxonomy": False},
        "promotion_allowed": False,
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "sustained_summary.json", result)
    _atomic_json(root / COMPACT_REL, result)
    return result, run_dir
