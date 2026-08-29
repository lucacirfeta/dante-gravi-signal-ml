"""Outcome-blind performance contract for the corrected O4a reconstruction."""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import tempfile
import time
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.evidence import SCORE_ATOL
from src.dante_light.o4a_corrected_execution import (
    _open_scan_database,
    _primary_scorer,
    _score_only,
)
from src.dante_light.o4a_corrected_protocol import (
    OUTPUT_REL as PROTOCOL_REL,
    ROOT,
    iter_scan_identities,
    validate_corrected_protocol,
)
from src.dante_light.o4a_corrected_runtime import (
    OUTPUT_REL as RUNTIME_REL,
    load_canonical_runtime_contract,
)
from src.dante_light.prefilter_v5_protocol import repository_reference


SCHEMA_VERSION = 1
CONTRACT_ID = "dante-o4a-corrected-outcome-blind-performance-v1"
CONTRACT_REL = "config/dante_o4a_corrected_performance_v1.json"
COMPACT_RESULT_REL = (
    "artifacts/dante_light/o4a_v1_parity/corrected_performance_benchmark.json"
)
RAW_MANIFEST_REL = (
    "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"
)
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_performance")
CONFIGURATIONS = (
    {"id": "baseline_2x8_direct", "workers": 2, "batch_size": 8, "staging": "direct"},
    {"id": "mid_4x16_direct", "workers": 4, "batch_size": 16, "staging": "direct"},
    {"id": "v1_8x32_direct", "workers": 8, "batch_size": 32, "staging": "direct"},
    {
        "id": "v1_8x32_ephemeral_stage",
        "workers": 8,
        "batch_size": 32,
        "staging": "ephemeral_verified_one_file",
    },
)
DB_COMMIT_ROWS = (32, 256, 1024)


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


@contextmanager
def stage_verified_raw_file(
    source: Path,
    *,
    staging_dir: Path,
    expected_sha256: str,
):
    """Stage one raw file with a single verified source read and bounded space."""

    source = source.resolve()
    staging_dir = staging_dir.resolve()
    staging_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    descriptor, name = tempfile.mkstemp(
        prefix=f"{source.stem}.", suffix=source.suffix, dir=staging_dir
    )
    staged = Path(name)
    try:
        with source.open("rb") as input_stream, os.fdopen(descriptor, "wb") as output_stream:
            for chunk in iter(lambda: input_stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if digest.hexdigest() != expected_sha256:
            raise ContractError(f"raw source SHA-256 mismatch: {source}")
        if staged.stat().st_size != source.stat().st_size:
            raise ContractError(f"staged raw source size mismatch: {source}")
        yield staged
    finally:
        staged.unlink(missing_ok=True)


def _raw_manifest_rows(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (root / RAW_MANIFEST_REL).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _canary_spans(
    root: Path,
    *,
    protocol_digest: str,
    spans_per_detector: int = 2,
    windows_per_span: int = 96,
) -> list[dict[str, Any]]:
    raw_rows = {
        (
            str(row["detector"]),
            float(row["gps_start"]),
            float(row["gps_end"]),
            str(row["sha256"]),
        ): row
        for row in _raw_manifest_rows(root)
        if float(row["duration_s"]) == 4096.0
        and int(row["physical_copies"][0]["size_bytes"]) >= 100_000_000
    }
    grouped: dict[tuple[str, float, float, str], list[float]] = defaultdict(list)
    for row in iter_scan_identities(root):
        if int(row["overlapping_source_count"]) != 1:
            continue
        start, end = (float(value) for value in row["source_span"])
        gps = float(row["analysis_gps_start"])
        key = (str(row["detector"]), start, end, str(row["source_sha256"]))
        if key in raw_rows and start + 4.0 <= gps <= end - 36.0:
            grouped[key].append(gps)
    selected: list[dict[str, Any]] = []
    for detector in ("H1", "L1"):
        candidates = []
        for key, gps_values in grouped.items():
            if key[0] != detector or len(gps_values) < windows_per_span:
                continue
            rank = hashlib.sha256(
                f"{protocol_digest}|performance-canary|{key}".encode("ascii")
            ).hexdigest()
            candidates.append((rank, key, gps_values))
        candidates.sort(key=lambda item: item[0])
        if len(candidates) < spans_per_detector:
            raise ContractError(f"insufficient outcome-blind performance spans for {detector}")
        for _rank, key, gps_values in candidates[:spans_per_detector]:
            gps_ranked = sorted(
                gps_values,
                key=lambda gps: hashlib.sha256(
                    f"{protocol_digest}|performance-window|{detector}|{gps:.9f}".encode(
                        "ascii"
                    )
                ).hexdigest(),
            )[:windows_per_span]
            raw = raw_rows[key]
            physical = sorted(
                raw["physical_copies"], key=lambda row: str(row["relative_path"])
            )[0]
            selected.append(
                {
                    "detector": detector,
                    "gps_start": key[1],
                    "gps_end": key[2],
                    "sha256": key[3],
                    "size_bytes": int(physical["size_bytes"]),
                    "relative_path": str(physical["relative_path"]),
                    "expected_gps_starts": sorted(float(value) for value in gps_ranked),
                    "expected_gps_digest": canonical_json_sha256(
                        sorted(float(value) for value in gps_ranked)
                    ),
                }
            )
    return selected


def build_performance_contract(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    protocol = validate_corrected_protocol(_load_json(root / PROTOCOL_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    canary = _canary_spans(root, protocol_digest=protocol["protocol_digest"])
    references = {
        name: repository_reference(root, root / relative)
        for name, relative in {
            "protocol": PROTOCOL_REL,
            "runtime": RUNTIME_REL,
            "raw_manifest": RAW_MANIFEST_REL,
            "raw_validity": (
                "artifacts/dante_light/o4a_v1_parity/raw_window_validity_audit.json"
            ),
            "patch_producer": "src/core/patch_producer.py",
            "performance_implementation": (
                "src/dante_light/o4a_corrected_performance.py"
            ),
            "benchmark_runner": "scripts/benchmark_dante_o4a_corrected_performance.py",
        }.items()
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_PERFORMANCE_CONTRACT",
        "contract_id": CONTRACT_ID,
        "protocol_digest": protocol["protocol_digest"],
        "runtime_contract_digest": runtime["contract_digest"],
        "canary": {
            "selector": "sha256_ordered_eligible_unique_source_windows",
            "spans_per_detector": 2,
            "windows_per_span": 96,
            "spans": canary,
            "canary_digest": canonical_json_sha256(canary),
        },
        "benchmark": {
            "configurations": list(CONFIGURATIONS),
            "warmup_repetitions": 1,
            "measured_repetitions": 2,
            "configuration_order": "cyclic_rotation_by_repetition",
            "authoritative_metric": "median_end_to_end_windows_per_second",
            "equivalence": {
                "gps_sequence": "exact",
                "image_sha256": "exact",
                "score_atol": SCORE_ATOL,
                "score_rtol": 0.0,
                "all_repetitions_must_pass": True,
            },
            "promotion": {
                "baseline_id": "baseline_2x8_direct",
                "minimum_speedup_over_baseline": 2.0,
                "selection": "fastest_passing_configuration_by_authoritative_metric",
                "tie_break": "lower_workers_then_lower_batch_then_direct",
                "no_passing_candidate": "STOP_NO_REFREEZE",
            },
            "staging": {
                "working_set": "one_source_file",
                "source_read_count": 1,
                "copy_is_hash_verification": True,
                "delete_after_eager_read": True,
                "persistent_second_raw_mirror": False,
                "default_wsl_dir": "/tmp/dante_o4a_corrected_stage",
            },
        },
        "database_probe": {
            "commit_row_candidates": list(DB_COMMIT_ROWS),
            "rows_per_repetition": 8192,
            "warmup_repetitions": 1,
            "measured_repetitions": 3,
            "journal_mode": "WAL",
            "synchronous": "FULL",
            "selection": "fastest_median_rows_per_second",
            "contents_equivalence": "exact_row_count_and_integrity_check",
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


def validate_performance_contract(
    value: Mapping[str, Any], root: Path = ROOT
) -> dict[str, Any]:
    root = root.resolve()
    payload = dict(value)
    digest = payload.pop("contract_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("corrected O4a performance contract self-digest mismatch")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_OUTCOME_BLIND_PERFORMANCE_CONTRACT"
        or value.get("contract_id") != CONTRACT_ID
        or value["benchmark"]["configurations"] != list(CONFIGURATIONS)
        or float(value["benchmark"]["equivalence"]["score_atol"]) != SCORE_ATOL
        or value["database_probe"]["commit_row_candidates"] != list(DB_COMMIT_ROWS)
    ):
        raise ContractError("corrected O4a performance contract changed")
    protocol = validate_corrected_protocol(_load_json(root / PROTOCOL_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    if (
        value["protocol_digest"] != protocol["protocol_digest"]
        or value["runtime_contract_digest"] != runtime["contract_digest"]
    ):
        raise ContractError("corrected O4a performance parent contract changed")
    canary = list(value["canary"]["spans"])
    if (
        value["canary"]["canary_digest"] != canonical_json_sha256(canary)
        or canary != _canary_spans(root, protocol_digest=protocol["protocol_digest"])
    ):
        raise ContractError("corrected O4a performance canary changed")
    for name, reference in value["references"].items():
        current = repository_reference(root, root / str(reference["path"]))
        if current != reference:
            raise ContractError(f"corrected O4a performance reference changed: {name}")
    return dict(value)


def write_performance_contract(root: Path = ROOT) -> dict[str, Any]:
    value = build_performance_contract(root)
    _atomic_json(root / CONTRACT_REL, value)
    return value


def load_performance_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_performance_contract(_load_json(root / CONTRACT_REL), root)


def _single_span_manifest(
    path: Path, span: Mapping[str, Any], *, relative_path: str | None = None
) -> None:
    row = {
        "copy_count": 1,
        "detector": span["detector"],
        "duration_s": float(span["gps_end"]) - float(span["gps_start"]),
        "gps_end": span["gps_end"],
        "gps_start": span["gps_start"],
        "physical_copies": [
            {
                "relative_path": relative_path or span["relative_path"],
                "sha256": span["sha256"],
                "size_bytes": span["size_bytes"],
            }
        ],
        "sha256": span["sha256"],
    }
    path.write_text(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


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
    import torch
    from src.core.patch_producer import PatchProducer, _sha256_path_cached

    staging = str(configuration["staging"])
    staging_dir = (
        Path(contract["benchmark"]["staging"]["default_wsl_dir"])
        if staging == "ephemeral_verified_one_file"
        else None
    )
    gps_all: list[float] = []
    image_hashes: list[str] = []
    score_hex: list[str] = []
    preprocess_s = 0.0
    scoring_s = 0.0
    started = time.perf_counter()
    for span_index, span in enumerate(contract["canary"]["spans"]):
        manifest = run_dir / "manifests" / f"span_{span_index}.jsonl"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        expected = [float(value) for value in span["expected_gps_starts"]]
        grid = np.arange(float(span["gps_start"]), float(span["gps_end"]), 32.0)
        excluded = sorted(set(float(value) for value in grid) - set(expected))
        source = raw_root / str(span["relative_path"])
        if staging_dir is None:
            staged_context = None
            span_raw_root = raw_root
            relative_path = str(span["relative_path"])
        else:
            staged_context = stage_verified_raw_file(
                source,
                staging_dir=staging_dir,
                expected_sha256=str(span["sha256"]),
            )
            span_raw_root = staging_dir
            relative_path = ""

        def consume(read_root: Path, manifest_relative: str) -> list[float]:
            nonlocal preprocess_s, scoring_s
            _single_span_manifest(
                manifest, span, relative_path=manifest_relative
            )
            _sha256_path_cached.cache_clear()
            producer = PatchProducer(
                read_root,
                str(span["detector"]),
                workers=int(configuration["workers"]),
                batch_size=int(configuration["batch_size"]),
                raw_manifest=manifest,
                raw_root=read_root,
                manifest_targets=True,
                incomplete_context_policy="record_and_skip",
                excluded_gps_starts=excluded,
                worker_failure_policy="raise",
            )
            iterator = iter(producer)
            observed: list[float] = []
            while True:
                before = time.perf_counter()
                try:
                    gps_batch, images = next(iterator)
                except StopIteration:
                    preprocess_s += time.perf_counter() - before
                    break
                preprocess_s += time.perf_counter() - before
                before = time.perf_counter()
                scores = _score_only(scorer, images)
                torch.cuda.synchronize()
                scoring_s += time.perf_counter() - before
                observed.extend(float(value) for value in gps_batch)
                gps_all.extend(float(value) for value in gps_batch)
                image_hashes.extend(
                    hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest()
                    for image in images
                )
                score_hex.extend(np.float32(score).tobytes().hex() for score in scores)
            return observed

        if staged_context is None:
            observed_gps = consume(span_raw_root, relative_path)
        else:
            with staged_context as staged:
                observed_gps = consume(span_raw_root, staged.name)
        if observed_gps != expected:
            raise ContractError(
                f"performance canary GPS mismatch for {span['detector']} {span['gps_start']}"
            )
    elapsed = time.perf_counter() - started
    if not gps_all or elapsed <= 0.0:
        raise ContractError("performance configuration produced no timed windows")
    body = {
        "configuration": dict(configuration),
        "repetition": repetition,
        "window_count": len(gps_all),
        "gps_digest": canonical_json_sha256(gps_all),
        "image_digest": canonical_json_sha256(image_hashes),
        "score_float32_hex_digest": canonical_json_sha256(score_hex),
        "gps": gps_all,
        "image_sha256": image_hashes,
        "score_float32_hex": score_hex,
        "timing": {
            "preprocess_and_io_s": preprocess_s,
            "scoring_s": scoring_s,
            "end_to_end_s": elapsed,
            "end_to_end_windows_per_s": len(gps_all) / elapsed,
        },
    }
    return {**body, "record_digest": canonical_json_sha256(body)}


def _database_probe(
    *, run_dir: Path, contract: Mapping[str, Any]
) -> dict[str, Any]:
    rows_per_repetition = int(contract["database_probe"]["rows_per_repetition"])
    warmups = int(contract["database_probe"]["warmup_repetitions"])
    measured = int(contract["database_probe"]["measured_repetitions"])
    results = []
    identity = {"stage": "outcome_blind_database_probe", "contract": contract["contract_digest"]}
    for repetition in range(warmups + measured):
        for commit_rows in contract["database_probe"]["commit_row_candidates"]:
            path = run_dir / "database_probe" / f"r{repetition}_c{commit_rows}.sqlite"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            connection = _open_scan_database(path, identity=identity)
            started = time.perf_counter()
            buffer = []
            for index in range(rows_per_repetition):
                detector = "H1" if index % 2 == 0 else "L1"
                buffer.append(
                    (
                        detector,
                        float(1_000_000_000 + index * 32),
                        float(index % 1000) / 1000.0,
                        np.float32(index % 1000 / 1000.0).tobytes().hex(),
                        "[0]",
                        None,
                        0,
                        hashlib.sha256(f"identity-{index}".encode()).hexdigest(),
                        hashlib.sha256(f"image-{index}".encode()).hexdigest(),
                        None,
                        None,
                        None,
                    )
                )
                if len(buffer) == int(commit_rows):
                    with connection:
                        connection.executemany(
                            "INSERT INTO windows VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            buffer,
                        )
                    buffer = []
            if buffer:
                with connection:
                    connection.executemany(
                        "INSERT INTO windows VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        buffer,
                    )
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            elapsed = time.perf_counter() - started
            count = int(connection.execute("SELECT COUNT(*) FROM windows").fetchone()[0])
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            connection.close()
            if count != rows_per_repetition or integrity != "ok":
                raise ContractError("database performance probe failed integrity")
            results.append(
                {
                    "repetition": repetition,
                    "phase": "warmup" if repetition < warmups else "measured",
                    "commit_rows": int(commit_rows),
                    "row_count": count,
                    "elapsed_s": elapsed,
                    "rows_per_s": count / elapsed,
                    "integrity_check": integrity,
                }
            )
            path.unlink(missing_ok=True)
    medians = {
        str(commit_rows): statistics.median(
            row["rows_per_s"]
            for row in results
            if row["phase"] == "measured" and row["commit_rows"] == commit_rows
        )
        for commit_rows in contract["database_probe"]["commit_row_candidates"]
    }
    selected = min(
        (int(value) for value in medians),
        key=lambda value: (-medians[str(value)], value),
    )
    return {"records": results, "median_rows_per_s": medians, "selected_commit_rows": selected}


def run_performance_benchmark(
    *,
    root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    raw_root = raw_root.resolve()
    contract = load_performance_contract(root)
    protocol = validate_corrected_protocol(_load_json(root / PROTOCOL_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    if runtime["contract_digest"] != contract["runtime_contract_digest"]:
        raise ContractError("performance benchmark runtime changed")
    run_key = canonical_json_sha256(
        {
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
            "stage": "outcome_blind_performance_benchmark",
        }
    )
    run_dir = external_root / f"benchmark_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    scorer = _primary_scorer(root=root, protocol=protocol, device=device)
    warmups = int(contract["benchmark"]["warmup_repetitions"])
    measured = int(contract["benchmark"]["measured_repetitions"])
    configs = list(contract["benchmark"]["configurations"])
    records = []
    for repetition in range(warmups + measured):
        rotation = repetition % len(configs)
        ordered = configs[rotation:] + configs[:rotation]
        current: dict[str, dict[str, Any]] = {}
        for configuration in ordered:
            record = _run_configuration(
                root=root,
                raw_root=raw_root,
                run_dir=run_dir,
                protocol=protocol,
                contract=contract,
                scorer=scorer,
                configuration=configuration,
                repetition=repetition,
            )
            current[str(configuration["id"])] = record
        baseline = current["baseline_2x8_direct"]
        for configuration in configs:
            record = current[str(configuration["id"])]
            if (
                record["gps"] != baseline["gps"]
                or record["image_sha256"] != baseline["image_sha256"]
            ):
                raise ContractError("performance candidate changed GPS or rendered images")
            baseline_scores = np.frombuffer(
                b"".join(bytes.fromhex(value) for value in baseline["score_float32_hex"]),
                dtype=np.float32,
            )
            scores = np.frombuffer(
                b"".join(bytes.fromhex(value) for value in record["score_float32_hex"]),
                dtype=np.float32,
            )
            max_delta = float(
                np.max(
                    np.abs(
                        scores.astype(np.float64)
                        - baseline_scores.astype(np.float64)
                    )
                )
            )
            passed = math.isfinite(max_delta) and max_delta <= SCORE_ATOL
            record["equivalence"] = {
                "gps_exact": True,
                "images_exact": True,
                "max_abs_score_delta": max_delta,
                "score_atol": SCORE_ATOL,
                "pass": passed,
            }
            record["phase"] = "warmup" if repetition < warmups else "measured"
            records.append(record)
            if not passed:
                raise ContractError("performance candidate exceeded frozen score tolerance")
    medians = {
        str(configuration["id"]): statistics.median(
            row["timing"]["end_to_end_windows_per_s"]
            for row in records
            if row["phase"] == "measured"
            and row["configuration"]["id"] == configuration["id"]
        )
        for configuration in configs
    }
    baseline_rate = medians["baseline_2x8_direct"]
    passing_candidates = [
        configuration
        for configuration in configs
        if configuration["id"] != "baseline_2x8_direct"
        and medians[str(configuration["id"])] / baseline_rate
        >= float(contract["benchmark"]["promotion"]["minimum_speedup_over_baseline"])
    ]
    selected = None
    if passing_candidates:
        selected = min(
            passing_candidates,
            key=lambda configuration: (
                -medians[str(configuration["id"])],
                int(configuration["workers"]),
                int(configuration["batch_size"]),
                str(configuration["staging"]) != "direct",
            ),
        )
    database = _database_probe(run_dir=run_dir, contract=contract)
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_EQUIVALENCE_AND_PERFORMANCE_SELECTION" if selected else "STOP_NO_REFREEZE",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "records": records,
        "median_end_to_end_windows_per_s": medians,
        "speedup_over_baseline": {
            key: value / baseline_rate for key, value in medians.items()
        },
        "selected_configuration": selected,
        "database_probe": database,
        "outcome_access": contract["outcome_boundary"],
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "performance_benchmark.json", result)
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


def verify_performance_result(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_performance_contract(root)
    runtime = load_canonical_runtime_contract(root=root, require_current=False)
    run_key = canonical_json_sha256(
        {
            "contract_digest": contract["contract_digest"],
            "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
            "stage": "outcome_blind_performance_benchmark",
        }
    )
    path = external_root.resolve() / f"benchmark_{run_key}" / "performance_benchmark.json"
    result = _load_json(path)
    payload = dict(result)
    digest = payload.pop("artifact_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("performance benchmark result self-digest mismatch")
    expected_records = (
        len(contract["benchmark"]["configurations"])
        * (
            int(contract["benchmark"]["warmup_repetitions"])
            + int(contract["benchmark"]["measured_repetitions"])
        )
    )
    if len(result["records"]) != expected_records:
        raise ContractError("performance benchmark result cardinality mismatch")
    configs = [str(row["id"]) for row in contract["benchmark"]["configurations"]]
    for repetition in range(
        int(contract["benchmark"]["warmup_repetitions"])
        + int(contract["benchmark"]["measured_repetitions"])
    ):
        rows = {
            str(row["configuration"]["id"]): row
            for row in result["records"]
            if int(row["repetition"]) == repetition
        }
        if sorted(rows) != sorted(configs):
            raise ContractError("performance benchmark repetition is incomplete")
        baseline = rows["baseline_2x8_direct"]
        baseline_scores = np.frombuffer(
            b"".join(bytes.fromhex(value) for value in baseline["score_float32_hex"]),
            dtype=np.float32,
        )
        for row in rows.values():
            core = {
                key: value
                for key, value in row.items()
                if key not in {"record_digest", "equivalence", "phase"}
            }
            if row["record_digest"] != canonical_json_sha256(core):
                raise ContractError("performance benchmark record digest mismatch")
            if row["gps"] != baseline["gps"] or row["image_sha256"] != baseline["image_sha256"]:
                raise ContractError("performance benchmark image equivalence changed")
            scores = np.frombuffer(
                b"".join(bytes.fromhex(value) for value in row["score_float32_hex"]),
                dtype=np.float32,
            )
            delta = float(
                np.max(
                    np.abs(
                        scores.astype(np.float64)
                        - baseline_scores.astype(np.float64)
                    )
                )
            )
            if (
                not row["equivalence"]["pass"]
                or delta != float(row["equivalence"]["max_abs_score_delta"])
                or delta > SCORE_ATOL
            ):
                raise ContractError("performance benchmark contains failed equivalence")
    if result["selected_configuration"] is None:
        raise ContractError("performance benchmark did not promote a configuration")
    if result["outcome_access"] != contract["outcome_boundary"]:
        raise ContractError("performance benchmark outcome boundary changed")
    compact = _load_json(root / COMPACT_RESULT_REL)
    if compact["artifact_digest"] != result["artifact_digest"]:
        raise ContractError("compact performance result is not bound to external result")
    return result
