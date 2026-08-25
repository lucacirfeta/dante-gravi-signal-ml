"""Outcome-blind identity and raw-mirror audit for DANTE-Light v5.

This module inventories file identities and 4096-second grouping blocks only.
It must not read strain arrays, teacher scores, feature values, or protected
outcomes. Full-file SHA256 is used solely for raw-cache integrity and duplicate
resolution.
"""

from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v4_protocol import repository_reference


AUDIT_ID = "dante-light-l4-prefilter-v5-identity-feasibility"
AUDIT_STATUS = "V5_PLAN1_IDENTITY_ONLY"
ARTIFACT_STATUS = "PASS_IDENTITY_CAPACITY_ONLY_NOT_A_SPLIT"
HASH_CACHE_STATUS = "LOCAL_RESUMABLE_RAW_SHA256_CACHE"
RAW_FILE_RE = re.compile(r"^(?P<detector>[A-Z][0-9])_(?P<start>[0-9]+)_(?P<end>[0-9]+)\.hdf5$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_stream(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Hash a potentially large file without loading it into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def quick_content_fingerprint(path: Path, *, edge_size: int = 64 * 1024) -> str:
    """Guard a local cache against same-size, same-mtime rewrites."""

    size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(int(size).to_bytes(16, "big", signed=False))
    with path.open("rb") as stream:
        digest.update(stream.read(edge_size))
        if size > edge_size:
            stream.seek(max(0, size - edge_size))
            digest.update(stream.read(edge_size))
    return digest.hexdigest()


def _config_digest(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("config_digest", None)
    return canonical_json_sha256(body)


def validate_identity_config(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    if payload.get("schema_version") != 1:
        raise ContractError("v5 identity audit requires schema version 1")
    if payload.get("audit_id") != AUDIT_ID or payload.get("status") != AUDIT_STATUS:
        raise ContractError("unexpected v5 identity-audit identity or status")
    if payload.get("config_digest") != _config_digest(payload):
        raise ContractError("v5 identity-audit config digest mismatch")

    boundary = payload.get("scientific_boundary", {})
    required_false = (
        "may_read_strain_arrays",
        "may_read_teacher_scores",
        "may_read_feature_values",
        "may_read_development_outcomes",
        "may_read_confirmation_outcomes",
        "may_read_o4b",
        "may_assign_v5_partitions",
        "may_freeze_v5",
    )
    if any(boundary.get(key) is not False for key in required_false):
        raise ContractError("v5 identity audit permits protected or promotable work")
    if boundary.get("allowed_operations") != [
        "read_prior_versioned_window_identities",
        "read_raw_file_names_sizes_mtimes_and_bytes_for_sha256",
        "read_hdf5_container_and_dataset_metadata_without_strain_values",
        "derive_4096s_coverage_capacity",
    ]:
        raise ContractError("v5 identity audit operations changed")

    raw = payload.get("raw_mirror_contract", {})
    detectors = tuple(raw.get("detectors", ()))
    if detectors != ("H1", "L1"):
        raise ContractError("v5 identity audit is restricted to O4a H1/L1")
    if int(raw.get("group_block_duration_s", 0)) != 4096:
        raise ContractError("v5 identity audit block duration must remain 4096 s")
    if int(raw.get("raw_sample_rate_hz", 0)) != 4096:
        raise ContractError("v5 raw mirror must contain 4096 Hz strain")
    if raw.get("file_name_regex") != RAW_FILE_RE.pattern:
        raise ContractError("v5 raw-file identity regex changed")
    if raw.get("content_hash") != "sha256_all_physical_files_resumable":
        raise ContractError("v5 raw inventory must hash every physical file")

    prior = payload.get("prior_identity_sources", [])
    if [item.get("protocol_version") for item in prior] != ["v1", "v2", "v4"]:
        raise ContractError("v5 prior split sources must be v1, v2, and v4")
    for item in prior:
        reference = item.get("split_header_reference", {})
        if not isinstance(reference.get("path"), str) or not SHA256_RE.fullmatch(
            str(reference.get("sha256", ""))
        ):
            raise ContractError("invalid prior split-header reference")

    alias = payload.get("protocol_aliases", {}).get("v3", {})
    if alias.get("reuses_split_protocol_version") != "v2":
        raise ContractError("v3 must be represented as an audited v2 split alias")
    reference = alias.get("protocol_reference", {})
    if not isinstance(reference.get("path"), str) or not SHA256_RE.fullmatch(
        str(reference.get("sha256", ""))
    ):
        raise ContractError("invalid v3 protocol reference")
    quarantine = payload.get("known_raw_quarantine_reference", {})
    if not isinstance(quarantine.get("path"), str) or not SHA256_RE.fullmatch(
        str(quarantine.get("sha256", ""))
    ):
        raise ContractError("invalid known raw-quarantine reference")
    return payload


def load_identity_config(path: Path) -> dict[str, Any]:
    return validate_identity_config(json.loads(path.read_text(encoding="utf-8")))


def _require_repository_reference(root: Path, reference: Mapping[str, str]) -> Path:
    path = root / str(reference["path"])
    if not path.is_file():
        raise ContractError(f"missing repository identity source: {reference['path']}")
    if repository_reference(root, path) != dict(reference):
        raise ContractError(f"repository identity reference mismatch: {reference['path']}")
    return path


def _entries_reference(
    root: Path, header_path: Path, header: Mapping[str, Any]
) -> dict[str, str]:
    if "entries_reference" in header:
        reference = dict(header["entries_reference"])
    else:
        declared = Path(str(header["entries_path"]))
        candidate = root / declared
        if not candidate.is_file():
            candidate = header_path.parent / declared
        try:
            normalized = candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise ContractError("prior split entries resolve outside the repository") from exc
        reference = {
            "path": normalized,
            "sha256": str(header["entries_file_sha256"]),
        }
    if not SHA256_RE.fullmatch(reference.get("sha256", "")):
        raise ContractError("prior split contains an invalid entries digest")
    return reference


def prior_o4a_blocks(root: Path, config: Mapping[str, Any]) -> tuple[set[str], list[dict[str, Any]]]:
    """Return prior O4a grouping blocks without propagating role/outcome fields."""

    union: set[str] = set()
    sources: list[dict[str, Any]] = []
    block_duration = int(config["raw_mirror_contract"]["group_block_duration_s"])
    for source in config["prior_identity_sources"]:
        header_path = _require_repository_reference(root, source["split_header_reference"])
        header = json.loads(header_path.read_text(encoding="utf-8"))
        entries_ref = _entries_reference(root, header_path, header)
        entries_path = _require_repository_reference(root, entries_ref)
        rows = 0
        o4a_rows = 0
        blocks: set[str] = set()
        for line in entries_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rows += 1
            window = row.get("window", {})
            if str(window.get("run", "")).upper() != "O4A":
                continue
            detector = str(window.get("detector", row.get("detector", ""))).upper()
            if detector not in config["raw_mirror_contract"]["detectors"]:
                raise ContractError(f"unexpected detector in prior O4a split: {detector!r}")
            gps_start = float(window["gps_start"])
            if not math.isfinite(gps_start) or gps_start < 0:
                raise ContractError("invalid GPS identity in prior O4a split")
            block = f"{detector}:{math.floor(gps_start / block_duration)}"
            blocks.add(block)
            union.add(block)
            o4a_rows += 1
        sources.append(
            {
                "protocol_version": source["protocol_version"],
                "split_header_reference": dict(source["split_header_reference"]),
                "split_entries_reference": entries_ref,
                "all_identity_rows": rows,
                "o4a_identity_rows": o4a_rows,
                "o4a_block_count": len(blocks),
                "o4a_block_digest": canonical_json_sha256(sorted(blocks)),
            }
        )

    alias = config["protocol_aliases"]["v3"]
    protocol_path = _require_repository_reference(root, alias["protocol_reference"])
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    v2_source = next(item for item in sources if item["protocol_version"] == "v2")
    parent_split = protocol.get("parent_v2", {}).get("split", {})
    if (
        parent_split.get("path") != v2_source["split_header_reference"]["path"]
        or parent_split.get("sha256") != v2_source["split_header_reference"]["sha256"]
        or parent_split.get("entries_path") != v2_source["split_entries_reference"]["path"]
        or parent_split.get("entries_sha256") != v2_source["split_entries_reference"]["sha256"]
    ):
        raise ContractError("v3 protocol no longer reuses the audited v2 split exactly")
    return union, sources


def load_quarantine_record(root: Path, reference: Mapping[str, str]) -> dict[str, Any]:
    path = _require_repository_reference(root, reference)
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("raw-quarantine artifact digest mismatch")
    if payload.get("status") != "QUARANTINED_RECOVERABLE_RAW_INTEGRITY_FAILURES":
        raise ContractError("unexpected raw-quarantine status")
    if payload.get("recoverable") is not True or payload.get("strain_values_read") is not False:
        raise ContractError("raw-quarantine scientific boundary changed")
    names = [str(item["filename"]) for item in payload.get("files", [])]
    if len(names) != len(set(names)) or not names:
        raise ContractError("raw-quarantine file identities are empty or duplicated")
    for item in payload["files"]:
        if not SHA256_RE.fullmatch(str(item.get("sha256", ""))):
            raise ContractError("raw-quarantine entry lacks SHA256")
    return payload


def parse_raw_file(raw_root: Path, path: Path) -> dict[str, Any]:
    match = RAW_FILE_RE.fullmatch(path.name)
    if match is None:
        raise ContractError(f"unexpected raw HDF5 file name: {path.name}")
    start = int(match.group("start"))
    end = int(match.group("end"))
    stat = path.stat()
    if end <= start:
        raise ContractError(f"non-positive raw-file interval: {path.name}")
    if stat.st_size <= 0:
        raise ContractError(f"empty raw-file identity: {path.name}")
    return {
        "detector": match.group("detector"),
        "gps_start": start,
        "gps_end": end,
        "duration_s": end - start,
        "relative_path": path.relative_to(raw_root).as_posix(),
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def load_hash_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "status": HASH_CACHE_STATUS, "files": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("status") != HASH_CACHE_STATUS:
        raise ContractError("unexpected raw SHA256 cache schema or status")
    if not isinstance(payload.get("files"), dict):
        raise ContractError("raw SHA256 cache has no file mapping")
    return payload


def write_hash_cache_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def hash_raw_files(
    raw_root: Path,
    identities: Sequence[dict[str, Any]],
    *,
    cache_path: Path,
    checkpoint_every: int = 25,
    force_rehash: bool = False,
) -> list[dict[str, Any]]:
    cache = load_hash_cache(cache_path)
    cached_files: dict[str, Any] = cache["files"]
    rows: list[dict[str, Any]] = []
    changed = 0
    for identity in sorted(identities, key=lambda row: row["relative_path"]):
        relative = identity["relative_path"]
        cached = cached_files.get(relative)
        source_path = raw_root / relative
        quick_digest = quick_content_fingerprint(source_path)
        fingerprint = {
            "size_bytes": identity["size_bytes"],
            "mtime_ns": identity["mtime_ns"],
            "quick_content_sha256": quick_digest,
        }
        if (
            not force_rehash
            and isinstance(cached, dict)
            and cached.get("size_bytes") == fingerprint["size_bytes"]
            and cached.get("mtime_ns") == fingerprint["mtime_ns"]
            and cached.get("quick_content_sha256") == quick_digest
            and SHA256_RE.fullmatch(str(cached.get("sha256", "")))
        ):
            digest = str(cached["sha256"])
        else:
            digest = sha256_stream(source_path)
            post = source_path.stat()
            if (
                int(post.st_size) != fingerprint["size_bytes"]
                or int(post.st_mtime_ns) != fingerprint["mtime_ns"]
                or quick_content_fingerprint(source_path) != quick_digest
            ):
                raise ContractError(f"raw file changed during hashing: {relative}")
            cached_files[relative] = {**fingerprint, "sha256": digest}
            changed += 1
            if changed % checkpoint_every == 0:
                cache["files"] = cached_files
                write_hash_cache_atomic(cache_path, cache)
        row = dict(identity)
        row["sha256"] = digest
        rows.append(row)
    live = {row["relative_path"] for row in identities}
    cache["files"] = {key: value for key, value in cached_files.items() if key in live}
    write_hash_cache_atomic(cache_path, cache)
    return rows


def _merged_intervals(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[list[int]]]:
    by_detector: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for row in rows:
        by_detector[str(row["detector"])].add((int(row["gps_start"]), int(row["gps_end"])))
    merged: dict[str, list[list[int]]] = {}
    for detector, intervals in by_detector.items():
        detector_merged: list[list[int]] = []
        for start, end in sorted(intervals):
            if not detector_merged or start > detector_merged[-1][1]:
                detector_merged.append([start, end])
            else:
                detector_merged[-1][1] = max(detector_merged[-1][1], end)
        merged[detector] = detector_merged
    return merged


def coverage_by_block(
    rows: Sequence[Mapping[str, Any]], *, block_duration_s: int
) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for detector, intervals in _merged_intervals(rows).items():
        for start, end in intervals:
            first = start // block_duration_s
            last = (end - 1) // block_duration_s
            for block in range(first, last + 1):
                left = max(start, block * block_duration_s)
                right = min(end, (block + 1) * block_duration_s)
                key = f"{detector}:{block}"
                coverage[key] = coverage.get(key, 0) + max(0, right - left)
    if any(value > block_duration_s for value in coverage.values()):
        raise ContractError("merged raw intervals double-count block coverage")
    return coverage


def validate_raw_rows(rows: Sequence[Mapping[str, Any]], *, detectors: Sequence[str]) -> None:
    if not rows:
        raise ContractError("raw mirror contains no HDF5 identities")
    if any(row["detector"] not in detectors for row in rows):
        raise ContractError("raw mirror contains an out-of-contract detector")
    if any(not SHA256_RE.fullmatch(str(row.get("sha256", ""))) for row in rows):
        raise ContractError("raw mirror row lacks a full-file SHA256")
    grouped: dict[tuple[str, int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["detector"], row["gps_start"], row["gps_end"])].append(row)
    for key, copies in grouped.items():
        if len({copy["sha256"] for copy in copies}) != 1:
            raise ContractError(f"conflicting duplicate raw span: {key}")


def compact_raw_manifest(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep one span identity plus every physical-copy hash and relative path."""

    grouped: dict[tuple[str, int, int], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["detector"], row["gps_start"], row["gps_end"])].append(row)
    compact: list[dict[str, Any]] = []
    for (detector, start, end), copies in sorted(grouped.items()):
        ordered = sorted(copies, key=lambda item: item["relative_path"])
        compact.append(
            {
                "detector": detector,
                "gps_start": start,
                "gps_end": end,
                "duration_s": end - start,
                "sha256": ordered[0]["sha256"],
                "copy_count": len(ordered),
                "physical_copies": [
                    {
                        "relative_path": copy["relative_path"],
                        "size_bytes": copy["size_bytes"],
                        "sha256": copy["sha256"],
                    }
                    for copy in ordered
                ],
            }
        )
    return compact


def validate_hdf5_metadata(
    raw_root: Path,
    compact_rows: Sequence[Mapping[str, Any]],
    *,
    sample_rate_hz: int,
) -> None:
    """Validate HDF5 structure and dataset metadata without reading strain values."""

    try:
        import h5py
    except ImportError as exc:  # pragma: no cover - pinned project dependency
        raise ContractError("h5py is required for raw-container validation") from exc
    failures: list[str] = []
    for row in compact_rows:
        relative = row["physical_copies"][0]["relative_path"]
        path = raw_root / relative
        try:
            with h5py.File(path, "r") as handle:
                if set(handle.keys()) != {"Strain"}:
                    raise ValueError(f"unexpected root objects {sorted(handle.keys())}")
                dataset = handle["Strain"]
                expected_samples = int(row["duration_s"]) * int(sample_rate_hz)
                if dataset.ndim != 1 or dataset.shape != (expected_samples,):
                    raise ValueError(f"unexpected Strain shape {dataset.shape}")
                if dataset.dtype.kind != "f" or dataset.dtype.itemsize != 8:
                    raise ValueError(f"unexpected Strain dtype {dataset.dtype}")
        except (OSError, KeyError, ValueError) as exc:
            failures.append(f"{relative}: {exc}")
    if failures:
        detail = " | ".join(failures)
        raise ContractError(
            f"invalid HDF5 container metadata for {len(failures)} file(s): {detail}"
        )


def build_identity_artifact(
    *,
    root: Path,
    config_path: Path,
    config: Mapping[str, Any],
    source_path: Path,
    script_path: Path,
    physical_rows: Sequence[Mapping[str, Any]],
    compact_rows: Sequence[Mapping[str, Any]],
    manifest_path: Path,
    manifest_sha256: str,
    prior_blocks: set[str],
    prior_sources: Sequence[Mapping[str, Any]],
    all_files_rehashed_in_current_run: bool,
) -> dict[str, Any]:
    block_duration = int(config["raw_mirror_contract"]["group_block_duration_s"])
    coverage = coverage_by_block(compact_rows, block_duration_s=block_duration)
    touched = set(coverage)
    full = {key for key, seconds in coverage.items() if seconds == block_duration}
    fresh_touched = touched - prior_blocks
    fresh_full = full - prior_blocks
    detectors = tuple(config["raw_mirror_contract"]["detectors"])

    def per_detector(keys: set[str]) -> dict[str, int]:
        return {detector: sum(key.startswith(f"{detector}:") for key in keys) for detector in detectors}

    duplicate_spans = sum(int(row["copy_count"]) > 1 for row in compact_rows)
    quarantine = load_quarantine_record(root, config["known_raw_quarantine_reference"])
    body = {
        "schema_version": 1,
        "audit_id": AUDIT_ID,
        "status": ARTIFACT_STATUS,
        "scientific_boundary": {
            "eligible_for_candidate_selection": False,
            "eligible_for_partition_assignment": False,
            "eligible_for_v5_freeze": False,
            "teacher_scores_used": [],
            "feature_values_used": [],
            "development_outcomes_used": [],
            "confirmation_outcomes_used": [],
            "o4b_used": [],
        },
        "source_references": {
            "config": repository_reference(root, config_path),
            "implementation": repository_reference(root, source_path),
            "cli": repository_reference(root, script_path),
            "known_raw_quarantine": dict(config["known_raw_quarantine_reference"]),
            "prior_identity_sources": list(prior_sources),
        },
        "raw_mirror": {
            "logical_id": config["raw_mirror_contract"]["logical_id"],
            "absolute_runtime_path_recorded": False,
            "physical_file_count": len(physical_rows),
            "unique_span_count": len(compact_rows),
            "duplicate_span_count": duplicate_spans,
            "duplicate_extra_copy_count": len(physical_rows) - len(compact_rows),
            "all_physical_files_content_hashed": True,
            "all_files_rehashed_in_artifact_generation_run": bool(
                all_files_rehashed_in_current_run
            ),
            "all_duplicate_spans_byte_identical": True,
            "all_unique_spans_hdf5_metadata_valid": True,
            "hdf5_validation_read_strain_values": False,
            "raw_sample_rate_hz": config["raw_mirror_contract"]["raw_sample_rate_hz"],
            "known_quarantined_corrupt_file_count": len(quarantine["files"]),
            "physical_bytes_including_duplicates": sum(int(row["size_bytes"]) for row in physical_rows),
            "unique_span_bytes": sum(int(row["physical_copies"][0]["size_bytes"]) for row in compact_rows),
            "manifest_reference": {
                "path": manifest_path.relative_to(root).as_posix(),
                "sha256": manifest_sha256,
                "rows": len(compact_rows),
            },
        },
        "prior_usage": {
            "v3_split_alias_verified_as_v2": True,
            "union_o4a_block_count": len(prior_blocks),
            "union_o4a_block_digest": canonical_json_sha256(sorted(prior_blocks)),
            "union_o4a_block_keys": sorted(prior_blocks),
        },
        "capacity": {
            "group_block_duration_s": block_duration,
            "raw_touched_block_count": len(touched),
            "raw_fully_covered_block_count": len(full),
            "fresh_touched_block_count": len(fresh_touched),
            "fresh_fully_covered_block_count": len(fresh_full),
            "fresh_partial_only_block_count": len(fresh_touched - fresh_full),
            "fresh_fully_covered_by_detector": per_detector(fresh_full),
            "fresh_fully_covered_block_digest": canonical_json_sha256(sorted(fresh_full)),
            "fresh_fully_covered_block_keys": sorted(fresh_full),
            "interpretation": "identity-only capacity; no v5 partition assignment or CAT1/window eligibility",
        },
        "scattering_feasibility": {
            "status": "DEPENDENCY_CHECK_PENDING_OR_SEPARATE",
            "candidate_selected": False,
        },
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def validate_identity_artifact(
    artifact: Mapping[str, Any], *, root: Path, manifest_path: Path
) -> dict[str, Any]:
    payload = dict(artifact)
    declared = payload.pop("artifact_digest", None)
    if declared != canonical_json_sha256(payload):
        raise ContractError("v5 identity artifact digest mismatch")
    if payload.get("status") != ARTIFACT_STATUS:
        raise ContractError("v5 identity artifact has an unexpected status")
    boundary = payload.get("scientific_boundary", {})
    if any(
        boundary.get(key) is not False
        for key in (
            "eligible_for_candidate_selection",
            "eligible_for_partition_assignment",
            "eligible_for_v5_freeze",
        )
    ):
        raise ContractError("v5 identity artifact exceeds its scientific boundary")
    for key in (
        "teacher_scores_used",
        "feature_values_used",
        "development_outcomes_used",
        "confirmation_outcomes_used",
        "o4b_used",
    ):
        if boundary.get(key) != []:
            raise ContractError(f"v5 identity artifact accessed {key}")
    raw = payload["raw_mirror"]
    manifest_ref = raw["manifest_reference"]
    if manifest_ref["path"] != manifest_path.relative_to(root).as_posix():
        raise ContractError("v5 raw manifest path changed")
    if sha256_stream(manifest_path) != manifest_ref["sha256"]:
        raise ContractError("v5 raw manifest file hash mismatch")
    rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != manifest_ref["rows"] or len(rows) != raw["unique_span_count"]:
        raise ContractError("v5 raw manifest row count mismatch")
    physical_count = sum(int(row["copy_count"]) for row in rows)
    if physical_count != raw["physical_file_count"]:
        raise ContractError("v5 raw manifest physical-file count mismatch")
    for row in rows:
        if row["copy_count"] != len(row["physical_copies"]):
            raise ContractError("v5 raw manifest copy count mismatch")
        if len({copy["sha256"] for copy in row["physical_copies"]}) != 1:
            raise ContractError("v5 raw manifest contains conflicting duplicate hashes")
        if row["sha256"] != row["physical_copies"][0]["sha256"]:
            raise ContractError("v5 raw manifest canonical hash mismatch")
    prior = payload["prior_usage"]
    if prior["union_o4a_block_digest"] != canonical_json_sha256(prior["union_o4a_block_keys"]):
        raise ContractError("v5 prior-block digest mismatch")
    capacity = payload["capacity"]
    if capacity["fresh_fully_covered_block_digest"] != canonical_json_sha256(
        capacity["fresh_fully_covered_block_keys"]
    ):
        raise ContractError("v5 fresh-capacity digest mismatch")
    if set(capacity["fresh_fully_covered_block_keys"]) & set(prior["union_o4a_block_keys"]):
        raise ContractError("v5 fresh capacity overlaps a prior protocol block")
    return dict(artifact)
