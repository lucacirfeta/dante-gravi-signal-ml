"""Resumable sample-level validity audit for every frozen O4a raw span."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

import h5py
import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_protocol import RAW_MANIFEST_REL, ROOT
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path


SCHEMA_VERSION = 2
IMPLEMENTATION_REL = "src/dante_light/o4a_window_validity_audit.py"
OUTPUT_REL = "artifacts/dante_light/o4a_v1_parity/raw_window_validity_audit.json"
OVERLAP_AUDIT_REL = "artifacts/dante_light/o4a_v1_parity/overlapping_raw_span_audit.json"
DEFAULT_EXTERNAL_ROOT = Path("E:/dante_cache/dante_light/o4a_corrected_v2")


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _manifest_rows(root: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line)
        for line in (root / RAW_MANIFEST_REL).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows.sort(key=lambda row: (row["detector"], float(row["gps_start"]), float(row["gps_end"])))
    if len(rows) != 6_928:
        raise ContractError("raw-window validity manifest count changed")
    return rows


def _available_source(raw_root: Path, row: Mapping[str, Any]) -> Path:
    copies = sorted(row["physical_copies"], key=lambda item: item["relative_path"])
    for copy in copies:
        path = (raw_root / str(copy["relative_path"])).resolve()
        if path.is_file():
            if path.stat().st_size != int(copy["size_bytes"]):
                raise ContractError(f"raw-window validity source size mismatch: {path}")
            return path
    raise ContractError(
        f"raw-window validity source missing: {row['detector']} {row['gps_start']}"
    )


def _open_database(path: Path, *, identity: Mapping[str, Any]) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS spans(
          detector TEXT NOT NULL,
          gps_start REAL NOT NULL,
          gps_end REAL NOT NULL,
          source_sha256 TEXT NOT NULL,
          window_count INTEGER NOT NULL,
          nonfinite_gps_json TEXT NOT NULL,
          allzero_gps_json TEXT NOT NULL,
          first_pad_nonfinite_gps_json TEXT NOT NULL,
          last_pad_nonfinite_gps_json TEXT NOT NULL,
          PRIMARY KEY(detector,gps_start,gps_end)
        ) WITHOUT ROWID
        """
    )
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    saved = connection.execute("SELECT value FROM metadata WHERE key='run_identity'").fetchone()
    if saved is None:
        connection.execute("INSERT INTO metadata(key,value) VALUES('run_identity',?)", (encoded,))
        connection.commit()
    elif saved[0] != encoded:
        connection.close()
        raise ContractError("raw-window validity audit run-key collision")
    return connection


def _derive_invalid_rows(
    *,
    all_windows: set[tuple[str, float]],
    target_nonfinite: set[tuple[str, float]],
    target_allzero: set[tuple[str, float]],
    first_pad_nonfinite: set[tuple[str, float]],
    last_pad_nonfinite: set[tuple[str, float]],
) -> list[dict[str, Any]]:
    """Map target and adjacent-pad defects onto unique detector/GPS windows."""

    invalid: dict[tuple[str, float], set[str]] = defaultdict(set)
    for key in target_nonfinite:
        invalid[key].add("TARGET_NONFINITE")
    for key in target_allzero:
        invalid[key].add("TARGET_ALL_ZERO")
    for detector, gps in last_pad_nonfinite:
        target = (detector, gps + 32.0)
        if target in all_windows:
            invalid[target].add("LEFT_CONTEXT_NONFINITE")
    for detector, gps in first_pad_nonfinite:
        target = (detector, gps - 32.0)
        if target in all_windows:
            invalid[target].add("RIGHT_CONTEXT_NONFINITE")
    return [
        {"detector": detector, "gps_start": gps, "reasons": sorted(reasons)}
        for (detector, gps), reasons in sorted(invalid.items())
    ]


def run_window_validity_audit(
    *,
    root: Path = ROOT,
    raw_root: Path = Path("E:/o4a"),
    external_root: Path = DEFAULT_EXTERNAL_ROOT,
    chunk_windows: int = 8,
) -> tuple[dict[str, Any], Path]:
    if chunk_windows < 1:
        raise ValueError("chunk_windows must be positive")
    root = root.resolve()
    raw_root = raw_root.resolve()
    external_root = external_root.resolve()
    overlap = json.loads((root / OVERLAP_AUDIT_REL).read_text(encoding="utf-8"))
    overlap_payload = dict(overlap)
    overlap_digest = overlap_payload.pop("artifact_digest", None)
    if (
        overlap_digest != canonical_json_sha256(overlap_payload)
        or overlap_payload.get("status")
        != "PASS_SAMPLE_EXACT_OVERLAPS_INVALID_DATA_EXPLICIT"
    ):
        raise ContractError("raw-window validity overlap prerequisite is not valid")
    references = {
        "raw_manifest": repository_reference(root, root / RAW_MANIFEST_REL),
        "overlapping_raw_span_audit": repository_reference(
            root, root / OVERLAP_AUDIT_REL
        ),
        "implementation": repository_reference(root, root / IMPLEMENTATION_REL),
    }
    run_key = canonical_json_sha256(
        {
            "stage": "sample_level_raw_window_validity",
            "references": references,
            "sample_rate_hz": 4096,
            "window_duration_s": 32,
            "invalid_rules": [
                "any_nonfinite_sample_in_target",
                "all_target_samples_exactly_zero",
                "any_nonfinite_sample_in_symmetric_4s_whitening_context",
            ],
        }
    )
    run_dir = external_root / f"raw_validity_{run_key}"
    identity = {
        "schema_version": SCHEMA_VERSION,
        "status": "RUN_IDENTITY",
        "run_key": run_key,
        "references": references,
        "chunk_windows": chunk_windows,
    }
    _atomic_json(run_dir / "run_identity.json", identity)
    database_path = run_dir / "raw_window_validity.sqlite"
    connection = _open_database(database_path, identity=identity)
    existing = {
        (str(detector), float(start), float(end))
        for detector, start, end in connection.execute(
            "SELECT detector,gps_start,gps_end FROM spans"
        )
    }
    samples_per_window = 32 * 4096
    samples_per_pad = 4 * 4096
    for row in _manifest_rows(root):
        key = (str(row["detector"]), float(row["gps_start"]), float(row["gps_end"]))
        if key in existing:
            continue
        path = _available_source(raw_root, row)
        duration = float(row["gps_end"]) - float(row["gps_start"])
        expected_samples = int(round(duration * 4096))
        window_count = expected_samples // samples_per_window
        nonfinite = []
        allzero = []
        first_pad_nonfinite = []
        last_pad_nonfinite = []
        with h5py.File(path, "r") as handle:
            if "Strain" not in handle or handle["Strain"].shape != (expected_samples,):
                raise ContractError(f"raw-window validity HDF5 shape mismatch: {path}")
            dataset = handle["Strain"]
            for first in range(0, window_count, chunk_windows):
                count = min(chunk_windows, window_count - first)
                values = np.asarray(
                    dataset[
                        first * samples_per_window : (first + count) * samples_per_window
                    ]
                ).reshape(count, samples_per_window)
                finite = np.isfinite(values).all(axis=1)
                nonzero = np.any(values != 0.0, axis=1)
                first_pad_finite = np.isfinite(values[:, :samples_per_pad]).all(axis=1)
                last_pad_finite = np.isfinite(values[:, -samples_per_pad:]).all(axis=1)
                for offset in np.flatnonzero(~finite):
                    nonfinite.append(float(row["gps_start"]) + (first + int(offset)) * 32.0)
                for offset in np.flatnonzero(finite & ~nonzero):
                    allzero.append(float(row["gps_start"]) + (first + int(offset)) * 32.0)
                for offset in np.flatnonzero(~first_pad_finite):
                    first_pad_nonfinite.append(
                        float(row["gps_start"]) + (first + int(offset)) * 32.0
                    )
                for offset in np.flatnonzero(~last_pad_finite):
                    last_pad_nonfinite.append(
                        float(row["gps_start"]) + (first + int(offset)) * 32.0
                    )
        with connection:
            connection.execute(
                "INSERT INTO spans VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    key[0],
                    key[1],
                    key[2],
                    str(row["sha256"]),
                    window_count,
                    json.dumps(nonfinite, separators=(",", ":")),
                    json.dumps(allzero, separators=(",", ":")),
                    json.dumps(first_pad_nonfinite, separators=(",", ":")),
                    json.dumps(last_pad_nonfinite, separators=(",", ":")),
                ),
            )
    span_count = int(connection.execute("SELECT COUNT(*) FROM spans").fetchone()[0])
    if span_count != 6_928:
        connection.close()
        raise ContractError(f"raw-window validity audit incomplete: {span_count}/6928")
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    summary = summarize_window_validity(
        root=root, run_key=run_key, run_dir=run_dir, references=references
    )
    _atomic_json(run_dir / "raw_window_validity_summary.json", summary)
    _atomic_json(root / OUTPUT_REL, summary)
    return summary, run_dir


def summarize_window_validity(
    *, root: Path, run_key: str, run_dir: Path, references: Mapping[str, Any]
) -> dict[str, Any]:
    database_path = run_dir / "raw_window_validity.sqlite"
    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT detector,gps_start,gps_end,source_sha256,window_count,"
        "nonfinite_gps_json,allzero_gps_json,first_pad_nonfinite_gps_json,"
        "last_pad_nonfinite_gps_json FROM spans ORDER BY detector,gps_start,gps_end"
    )
    membership_counts = Counter()
    target_nonfinite: set[tuple[str, float]] = set()
    target_allzero: set[tuple[str, float]] = set()
    first_pad_nonfinite: set[tuple[str, float]] = set()
    last_pad_nonfinite: set[tuple[str, float]] = set()
    all_windows: set[tuple[str, float]] = set()
    span_count = 0
    for (
        detector,
        start,
        _end,
        _sha,
        window_count,
        nonfinite_json,
        allzero_json,
        first_pad_json,
        last_pad_json,
    ) in rows:
        span_count += 1
        membership_counts[str(detector)] += int(window_count)
        all_windows.update(
            (str(detector), float(start) + offset * 32.0)
            for offset in range(int(window_count))
        )
        for gps in json.loads(nonfinite_json):
            target_nonfinite.add((str(detector), float(gps)))
        for gps in json.loads(allzero_json):
            target_allzero.add((str(detector), float(gps)))
        for gps in json.loads(first_pad_json):
            first_pad_nonfinite.add((str(detector), float(gps)))
        for gps in json.loads(last_pad_json):
            last_pad_nonfinite.add((str(detector), float(gps)))
    connection.close()
    invalid_rows = _derive_invalid_rows(
        all_windows=all_windows,
        target_nonfinite=target_nonfinite,
        target_allzero=target_allzero,
        first_pad_nonfinite=first_pad_nonfinite,
        last_pad_nonfinite=last_pad_nonfinite,
    )
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_COMPLETE_SAMPLE_LEVEL_VALIDITY_AUDIT",
        "run_key": run_key,
        "span_count": span_count,
        "window_membership_counts": dict(membership_counts),
        "invalid_unique_window_count": len(invalid_rows),
        "invalid_detector_counts": {
            detector: sum(row["detector"] == detector for row in invalid_rows)
            for detector in ("H1", "L1")
        },
        "invalid_reason_counts": dict(
            Counter(reason for row in invalid_rows for reason in row["reasons"])
        ),
        "invalid_target_unique_window_count": sum(
            bool({"TARGET_NONFINITE", "TARGET_ALL_ZERO"}.intersection(row["reasons"]))
            for row in invalid_rows
        ),
        "invalid_context_only_unique_window_count": sum(
            not {"TARGET_NONFINITE", "TARGET_ALL_ZERO"}.intersection(row["reasons"])
            for row in invalid_rows
        ),
        "invalid_windows": invalid_rows,
        "invalid_window_digest": canonical_json_sha256(invalid_rows),
        "database": {
            "filename": database_path.name,
            "sha256": sha256_path(database_path),
            "size_bytes": database_path.stat().st_size,
        },
        "references": dict(references),
        "provenance_boundary": {
            "current_file_size_checked_against_manifest": True,
            "current_file_sha256_rechecked_in_this_audit": False,
            "manifest_generation_had_rehashed_all_files": True,
            "full_scoring_rechecks_each_selected_file_sha256": True,
        },
        "scientific_rule": (
            "A detector+GPS window is excluded before preprocessing if any target "
            "sample is non-finite, every target sample is exactly zero, or any sample "
            "in the required symmetric 4s whitening context is non-finite."
        ),
    }
    if span_count != 6_928 or membership_counts != {"H1": 441_984, "L1": 441_720}:
        raise ContractError("raw-window validity summary cardinality mismatch")
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def validate_window_validity_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("artifact_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("raw-window validity summary self-digest mismatch")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or
        payload.get("status") != "PASS_COMPLETE_SAMPLE_LEVEL_VALIDITY_AUDIT"
        or payload.get("span_count") != 6_928
        or payload.get("invalid_unique_window_count") != len(payload.get("invalid_windows", []))
        or payload.get("invalid_window_digest")
        != canonical_json_sha256(payload.get("invalid_windows", []))
    ):
        raise ContractError("raw-window validity summary contract mismatch")
    return dict(value)
