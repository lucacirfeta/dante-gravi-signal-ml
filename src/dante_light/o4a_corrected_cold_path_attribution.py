"""Outcome-blind stage attribution for the corrected O4a cold path."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import queue
import sqlite3
import statistics
import threading
import time
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.evidence import SCORE_ATOL
from src.dante_light.o4a_corrected_execution import (
    _ScanIdentityLookup,
    _primary_scorer,
)
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
CONTRACT_ID = "dante-o4a-corrected-cold-path-attribution-v1"
CONTRACT_REL = "config/dante_o4a_corrected_cold_path_attribution_v1.json"
PRIOR_COLD_RELS = (
    "config/dante_o4a_corrected_cold_path_v1.json",
    "config/dante_o4a_corrected_cold_path_v2.json",
    "config/dante_o4a_corrected_cold_path_v3.json",
)
COMPACT_REL = (
    "artifacts/dante_light/o4a_v1_parity/"
    "corrected_cold_path_attribution.json"
)
DEFAULT_EXTERNAL_ROOT = Path(
    "E:/dante_cache/dante_light/o4a_corrected_cold_path_attribution"
)
MODES = ("score_only", "full_all", "full_all_identity_db")


def _excluded_spans(root: Path) -> set[tuple[str, float, float, str]]:
    result: set[tuple[str, float, float, str]] = set()
    for relative in (PRIOR_CANARY_REL, *PRIOR_COLD_RELS):
        value = _load_json(root / relative)
        rows = (
            value["canary"]["spans"]
            if "canary" in value
            else value["selection"]["spans"]
        )
        result.update(
            (
                str(row["detector"]),
                float(row["gps_start"]),
                float(row["gps_end"]),
                str(row["sha256"]),
            )
            for row in rows
        )
    return result


def _select_spans(root: Path, *, protocol_digest: str) -> list[dict[str, Any]]:
    excluded = _excluded_spans(root)
    raw = {
        (
            str(row["detector"]),
            float(row["gps_start"]),
            float(row["gps_end"]),
            str(row["sha256"]),
        ): row
        for row in _raw_rows(root)
        if float(row["duration_s"]) == 4096.0
        and int(row["physical_copies"][0]["size_bytes"]) >= 100_000_000
    }
    grouped: dict[tuple[str, float, float, str], list[float]] = defaultdict(list)
    for row in iter_scan_identities(root):
        key = (
            str(row["detector"]),
            float(row["source_span"][0]),
            float(row["source_span"][1]),
            str(row["source_sha256"]),
        )
        gps = float(row["analysis_gps_start"])
        if (
            key in raw
            and key not in excluded
            and int(row["overlapping_source_count"]) == 1
            and key[1] + 4.0 <= gps <= key[2] - 36.0
        ):
            grouped[key].append(gps)
    selected = []
    for detector in ("H1", "L1"):
        candidates = sorted(
            (
                hashlib.sha256(
                    f"{protocol_digest}|stage-attribution-v1|{key}".encode("ascii")
                ).hexdigest(),
                key,
                sorted(values),
            )
            for key, values in grouped.items()
            if key[0] == detector and len(values) >= 96
        )
        if len(candidates) < 3:
            raise ContractError(f"insufficient fresh attribution spans for {detector}")
        for group, (_rank, key, values) in enumerate(candidates[:3]):
            row = raw[key]
            physical = sorted(
                row["physical_copies"], key=lambda item: item["relative_path"]
            )[0]
            gps = sorted(
                values,
                key=lambda value: hashlib.sha256(
                    (
                        f"{protocol_digest}|stage-attribution-window-v1|"
                        f"{detector}|{value:.9f}"
                    ).encode("ascii")
                ).hexdigest(),
            )[:96]
            selected.append(
                {
                    "group": group,
                    "detector": detector,
                    "gps_start": key[1],
                    "gps_end": key[2],
                    "sha256": key[3],
                    "size_bytes": int(physical["size_bytes"]),
                    "relative_path": str(physical["relative_path"]),
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
            "prior_cold_v1": PRIOR_COLD_RELS[0],
            "invalid_cache_v2": PRIOR_COLD_RELS[1],
            "edge_cache_v3": PRIOR_COLD_RELS[2],
            "patch_producer": "src/core/patch_producer.py",
            "scorer": "src/core/patch_scorer.py",
            "execution": "src/dante_light/o4a_corrected_execution.py",
            "implementation": (
                "src/dante_light/o4a_corrected_cold_path_attribution.py"
            ),
            "runner": (
                "scripts/benchmark_dante_o4a_corrected_cold_path_attribution.py"
            ),
        }.items()
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_STAGE_ATTRIBUTION_CONTRACT",
        "contract_id": CONTRACT_ID,
        "protocol_digest": protocol["protocol_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "selection": {
            "outcomes_used": [],
            "all_prior_canaries_excluded": True,
            "groups": 3,
            "spans_per_detector_per_group": 1,
            "windows_per_span": 96,
            "spans": spans,
            "span_digest": canonical_json_sha256(spans),
        },
        "benchmark": {
            "modes": list(MODES),
            "workers_per_detector": 8,
            "batch_size": 32,
            "detector_mode": "parallel_shared_scorer",
            "group_orders": {
                "0": ["score_only", "full_all", "full_all_identity_db"],
                "1": ["full_all", "full_all_identity_db", "score_only"],
                "2": ["full_all_identity_db", "score_only", "full_all"],
            },
            "database": {
                "journal_mode": "WAL",
                "synchronous": "FULL",
                "commit_rows": 1024,
                "diagnostic_schema_has_no_candidate_or_disposition_field": True,
            },
            "interpretation": {
                "score_only": "preprocessing plus exact score-only teacher path",
                "full_all": (
                    "conservative upper bound applying full materialization to every window"
                ),
                "full_all_identity_db": (
                    "full-all plus frozen identity lookup, image hashing, serialization, and disk SQLite"
                ),
                "promotion_allowed": False,
                "purpose": "stage attribution only",
            },
            "equivalence": {
                "detector_gps": "exact",
                "image_sha256": "exact",
                "score_atol": SCORE_ATOL,
                "score_rtol": 0.0,
            },
        },
        "scientific_boundary": {
            "candidate_scores_or_dispositions_inspected": False,
            "thresholds_or_taxonomy_accessed": False,
            "uniform_full_materialization_without_thresholds": True,
            "performance_only": True,
            "can_refreeze_protocol": False,
        },
        "references": references,
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_contract(value: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    expected = build_contract(root)
    if dict(value) != expected:
        raise ContractError("cold-path attribution contract is stale")
    return dict(value)


def _open_diagnostic_database(path: Path) -> sqlite3.Connection:
    path.unlink(missing_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        """
        CREATE TABLE windows (
          detector TEXT NOT NULL,
          gps_start REAL NOT NULL,
          score_float32_hex TEXT NOT NULL,
          identity_digest TEXT NOT NULL,
          image_sha256 TEXT NOT NULL,
          mil_vector BLOB NOT NULL,
          top_k_indices BLOB NOT NULL,
          patch_anomaly_scores BLOB NOT NULL,
          PRIMARY KEY(detector,gps_start)
        ) WITHOUT ROWID
        """
    )
    connection.commit()
    return connection


def _consume_group(
    *, root: Path, raw_root: Path, run_dir: Path, contract: Mapping[str, Any],
    group: int, mode: str, scorer: Any, identity_lookup: _ScanIdentityLookup,
) -> dict[str, Any]:
    from src.core.patch_producer import PatchProducer, _sha256_path_cached
    import torch

    spans = [row for row in contract["selection"]["spans"] if row["group"] == group]
    manifests = _write_group_manifests(run_dir, spans)
    output_queue: queue.Queue[tuple[str, Any, Any]] = queue.Queue(maxsize=4)

    def produce(detector: str) -> None:
        row = next(item for item in spans if item["detector"] == detector)
        expected = {float(value) for value in row["expected_gps_starts"]}
        grid = set(np.arange(float(row["gps_start"]), float(row["gps_end"]), 32.0))
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
                excluded_gps_starts=sorted(grid - expected),
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

    database = None
    if mode == "full_all_identity_db":
        database = _open_diagnostic_database(
            run_dir / f"group_{group}_{mode}.sqlite"
        )
    timers = defaultdict(float)
    rows_pending: list[tuple[Any, ...]] = []
    output = []

    def sync_clock() -> float:
        if torch.cuda.is_available():
            torch.cuda.synchronize(scorer.device)
        return time.perf_counter()

    def flush() -> None:
        nonlocal rows_pending
        if database is None or not rows_pending:
            return
        started = time.perf_counter()
        with database:
            database.executemany(
                "INSERT INTO windows VALUES(?,?,?,?,?,?,?,?)", rows_pending
            )
        timers["sqlite_commit_s"] += time.perf_counter() - started
        rows_pending = []

    _sha256_path_cached.cache_clear()
    total_started = time.perf_counter()
    threads = [
        threading.Thread(target=produce, args=(detector,), daemon=True)
        for detector in ("H1", "L1")
    ]
    for thread in threads:
        thread.start()
    remaining = 2
    while remaining:
        wait_started = time.perf_counter()
        detector, payload, images = output_queue.get()
        timers["queue_wait_s"] += time.perf_counter() - wait_started
        if payload is None:
            remaining -= 1
            continue
        if isinstance(payload, BaseException):
            raise ContractError(f"attribution producer failed for {detector}") from payload

        score_started = sync_clock()
        tokens = scorer.encode_patch_tokens(images)
        score_rows = scorer.score_patch_tokens(
            tokens,
            1.0,
            output_mode=("score_only" if mode == "score_only" else "full"),
        )
        timers["scoring_s"] += sync_clock() - score_started

        hash_started = time.perf_counter()
        image_hashes = [
            hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest()
            for image in images
        ]
        timers["image_hash_s"] += time.perf_counter() - hash_started

        for gps, image_hash, score_row in zip(payload, image_hashes, score_rows, strict=True):
            score = float(score_row["novelty_score"])
            output.append(
                (detector, float(gps), image_hash, np.float32(score).tobytes().hex())
            )
            if mode == "full_all_identity_db":
                lookup_started = time.perf_counter()
                identity = identity_lookup.lookup(detector, float(gps))
                identity_digest = canonical_json_sha256(identity)
                timers["identity_lookup_s"] += time.perf_counter() - lookup_started
                serialization_started = time.perf_counter()
                rows_pending.append(
                    (
                        detector,
                        float(gps),
                        np.float32(score).tobytes().hex(),
                        identity_digest,
                        image_hash,
                        np.ascontiguousarray(
                            score_row["mil_vector"], dtype=np.float32
                        ).tobytes(),
                        np.ascontiguousarray(
                            score_row["top_k_indices"], dtype=np.int32
                        ).tobytes(),
                        np.ascontiguousarray(
                            score_row["patch_anomaly_scores"], dtype=np.float32
                        ).tobytes(),
                    )
                )
                timers["serialization_s"] += (
                    time.perf_counter() - serialization_started
                )
        if len(rows_pending) >= 1024:
            flush()
    for thread in threads:
        thread.join()
    flush()
    if database is not None:
        database.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        database.close()
    elapsed = time.perf_counter() - total_started
    output.sort(key=lambda row: (row[0], row[1]))
    return {
        "group": group,
        "mode": mode,
        "window_count": len(output),
        "identities": [[row[0], row[1]] for row in output],
        "image_sha256": [row[2] for row in output],
        "score_float32_hex": [row[3] for row in output],
        "elapsed_s": elapsed,
        "windows_per_s": len(output) / elapsed,
        "timings_s": dict(sorted(timers.items())),
    }


def run_benchmark(
    *, root: Path = ROOT, raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT, device: str = "cuda",
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = validate_contract(_load_json(root / CONTRACT_REL), root)
    runtime = load_canonical_runtime_contract(root=root, require_current=True, device=device)
    run_key = canonical_json_sha256({
        "contract": contract["contract_digest"],
        "runtime": runtime["runtime_environment"]["environment_digest"],
    })
    run_dir = external_root.resolve() / f"benchmark_{run_key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    scorer = _primary_scorer(root=root, protocol=_load_parent_protocol_v3(root), device=device)
    lookup = _ScanIdentityLookup(root=root)
    records = []
    for group in range(3):
        current = {}
        for position, mode in enumerate(contract["benchmark"]["group_orders"][str(group)]):
            row = _consume_group(
                root=root,
                raw_root=raw_root.resolve(),
                run_dir=run_dir,
                contract=contract,
                group=group,
                mode=mode,
                scorer=scorer,
                identity_lookup=lookup,
            )
            row["position"] = position
            current[mode] = row
            records.append(row)
        baseline = current["score_only"]
        for mode in MODES[1:]:
            candidate = current[mode]
            if (
                baseline["identities"] != candidate["identities"]
                or baseline["image_sha256"] != candidate["image_sha256"]
            ):
                raise ContractError(f"{mode} changed identities or images")
            left = np.asarray([
                np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0]
                for value in baseline["score_float32_hex"]
            ])
            right = np.asarray([
                np.frombuffer(bytes.fromhex(value), dtype=np.float32)[0]
                for value in candidate["score_float32_hex"]
            ])
            delta = float(np.max(np.abs(left.astype(np.float64) - right.astype(np.float64))))
            if not np.isfinite(delta) or delta > SCORE_ATOL:
                raise ContractError(f"{mode} changed teacher scores")
            candidate["equivalence"] = {
                "identities_exact": True,
                "images_exact": True,
                "max_abs_score_delta": delta,
                "pass": True,
            }
        baseline["equivalence"] = {
            "identities_exact": True,
            "images_exact": True,
            "max_abs_score_delta": 0.0,
            "pass": True,
        }
    first_position = {
        mode: statistics.median(
            row["windows_per_s"]
            for row in records
            if row["mode"] == mode and row["position"] == 0
        )
        for mode in MODES
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_OUTCOME_BLIND_STAGE_ATTRIBUTION",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "runtime_environment_digest": runtime["runtime_environment"]["environment_digest"],
        "records": records,
        "first_position_windows_per_s": first_position,
        "outcome_access": {"thresholds": False, "dispositions": False, "taxonomy": False},
        "promotion_allowed": False,
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    _atomic_json(run_dir / "cold_path_attribution_summary.json", result)
    compact = dict(result)
    compact["records"] = [
        {key: row[key] for key in (
            "group", "mode", "position", "window_count", "elapsed_s",
            "windows_per_s", "timings_s", "equivalence",
        )}
        for row in records
    ]
    compact_body = dict(compact)
    compact_body.pop("artifact_digest")
    compact["artifact_digest"] = canonical_json_sha256(compact_body)
    _atomic_json(root / COMPACT_REL, compact)
    return result, run_dir
