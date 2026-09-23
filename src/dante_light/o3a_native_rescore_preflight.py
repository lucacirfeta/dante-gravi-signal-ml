"""Outcome-minimal identity and source-frame preflight for O3a native scoring.

This module never opens strain or reads a primary/native score.  It binds the
frozen calibration ledger and all primary seed identities to their exact
primary-scan images and validated raw-frame dependencies before costly replay.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_cohort import (
    _inventory_frames,
    _raw_frame_rows,
    _source_rows_for_context,
)
from src.dante_light.o3a_raw_acquisition import load_source_inventory


def scan_scoring_identities(database_path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Read only identity, seed flag and image digest from a verified scan."""
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        records = connection.execute(
            "SELECT detector,gps_start,is_candidate,identity_digest,image_sha256 "
            "FROM windows ORDER BY detector,gps_start"
        ).fetchall()
    rows: dict[tuple[str, int], dict[str, Any]] = {}
    for detector, gps, seed, identity, image in records:
        key = (str(detector), int(gps))
        if (
            key in rows
            or key[0] not in {"H1", "L1"}
            or seed not in (0, 1)
            or not isinstance(identity, str)
            or len(identity) != 64
            or not isinstance(image, str)
            or len(image) != 64
        ):
            raise ContractError("O3a native-rescore scan identity ledger is invalid")
        rows[key] = {
            "detector": key[0],
            "gps_start": key[1],
            "is_candidate": bool(seed),
            "identity_digest": identity,
            "expected_image_sha256": image,
        }
    return rows


def assemble_work_rows(
    *,
    scan_rows: Mapping[tuple[str, int], Mapping[str, Any]],
    calibration_rows: Sequence[Mapping[str, Any]],
    frames_by_detector: Mapping[str, Sequence[Mapping[str, Any]]],
    raw_frame_rows: Mapping[tuple[str, str], Mapping[str, Any]],
    expected_calibration_rows_by_detector: Mapping[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build an exact score-only work list without opening outcome columns."""
    calibration_keys: set[tuple[str, int]] = set()
    work: list[dict[str, Any]] = []
    frame_starts = {
        detector: [int(frame["gps_start"]) for frame in frames]
        for detector, frames in frames_by_detector.items()
    }

    def make_row(key: tuple[str, int], population: str, ordinal: int) -> dict[str, Any]:
        scan = scan_rows.get(key)
        if scan is None:
            raise ContractError("O3a native-rescore identity is absent from primary scan")
        sources = _source_rows_for_context(
            detector=key[0],
            gps=key[1],
            frames=frames_by_detector[key[0]],
            frame_starts=frame_starts[key[0]],
            raw_frame_rows=raw_frame_rows,
        )
        return {
            "population": population,
            "ordinal": ordinal,
            "detector": key[0],
            "gps_start": key[1],
            "identity_digest": scan["identity_digest"],
            "expected_image_sha256": scan["expected_image_sha256"],
            "context_sources": sources,
            "context_sources_digest": canonical_json_sha256(sources),
        }

    for ordinal, calibration in enumerate(calibration_rows):
        key = (str(calibration["detector"]), int(calibration["gps_start"]))
        if key in calibration_keys or scan_rows.get(key, {}).get("is_candidate") is not False:
            raise ContractError("O3a native-rescore calibration identity is invalid")
        calibration_keys.add(key)
        row = make_row(key, "native_calibration", ordinal)
        if (
            row["context_sources"] != calibration["context_sources"]
            or row["context_sources_digest"] != calibration["context_sources_digest"]
        ):
            raise ContractError("O3a native-rescore frozen calibration sources changed")
        work.append(row)

    candidate_keys = sorted(key for key, row in scan_rows.items() if row["is_candidate"])
    if calibration_keys.intersection(candidate_keys):
        raise ContractError("O3a native-rescore calibration intersects seed candidates")
    for ordinal, key in enumerate(candidate_keys):
        work.append(make_row(key, "primary_candidate", ordinal))

    counts = Counter((row["population"], row["detector"]) for row in work)
    if any(
        counts[("native_calibration", detector)] != expected_calibration_rows_by_detector[detector]
        for detector in ("H1", "L1")
    ):
        raise ContractError("O3a native-rescore calibration cardinality changed")
    if len(candidate_keys) != sum(row["is_candidate"] for row in scan_rows.values()):
        raise ContractError("O3a native-rescore candidate cardinality changed")

    unique_frames: dict[tuple[str, str], tuple[str, int]] = {}
    for row in work:
        for source in row["context_sources"]:
            key = (str(source["detector"]), str(source["filename"]))
            current = (str(source["sha256"]), int(source["size_bytes"]))
            if key in unique_frames and unique_frames[key] != current:
                raise ContractError("O3a native-rescore source frame has divergent identity")
            unique_frames[key] = current
    audit = {
        "calibration_rows_by_detector": {
            detector: counts[("native_calibration", detector)] for detector in ("H1", "L1")
        },
        "candidate_rows_by_detector": {
            detector: counts[("primary_candidate", detector)] for detector in ("H1", "L1")
        },
        "row_total": len(work),
        "unique_source_frames": len(unique_frames),
        "unique_source_bytes": sum(size for _sha, size in unique_frames.values()),
        "score_or_class_read": False,
        "strain_opened": False,
    }
    return work, audit


def read_calibration_ledger(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def preflight_from_verified_parents(
    *, scan_database: Path, calibration_ledger: Path, root: Path,
    expected_calibration_rows_by_detector: Mapping[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Caller must verify parent artifact digests before invoking this function."""
    scan_rows = scan_scoring_identities(scan_database)
    calibration_rows = read_calibration_ledger(calibration_ledger)
    inventory = load_source_inventory(root=root)
    frames = {detector: _inventory_frames(inventory, detector) for detector in ("H1", "L1")}
    return assemble_work_rows(
        scan_rows=scan_rows,
        calibration_rows=calibration_rows,
        frames_by_detector=frames,
        raw_frame_rows=_raw_frame_rows(scan_database),
        expected_calibration_rows_by_detector=expected_calibration_rows_by_detector,
    )
