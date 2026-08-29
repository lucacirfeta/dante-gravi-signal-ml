"""Frozen scientific contract for the corrected O4a production reconstruction.

The contract changes only the defective file-edge context handling.  It keeps
the historical O3b reference, per-session empirical p99 calibration identities,
strict threshold comparison, and candidate deduplication semantics.  Historical
outputs remain immutable and are inputs only to the impact comparison.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import heapq
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import h5py
import numpy as np

from src.dante_light.contracts import ContractError, RepresentationContract, canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path


ROOT = Path(__file__).resolve().parents[2]
RAW_MANIFEST_REL = "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"
RAW_AUDIT_REL = "artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json"
DEPENDENCY_AUDIT_REL = "artifacts/dante_light/o4a_v1_parity/dependency_impact_audit.json"
RAW_VALIDITY_REL = "artifacts/dante_light/o4a_v1_parity/raw_window_validity_audit.json"
OVERLAP_AUDIT_REL = "artifacts/dante_light/o4a_v1_parity/overlapping_raw_span_audit.json"
REFERENCE_REL = "config/reference_artifacts.json"
RUNTIME_CONFIG_REL = "config.yaml"
DQ_SNAPSHOT_REL = "config/dante_light_prefilter_v4_segments.json"
PROTOCOL_CODE_REL = "src/dante_light/o4a_corrected_protocol.py"
PATCH_PRODUCER_REL = "src/core/patch_producer.py"
PREPROCESSOR_REL = "src/core/preprocessor.py"
SCORER_REL = "src/core/patch_scorer.py"
OUTPUT_REL = "config/dante_o4a_corrected_protocol_v2.json"

SCHEMA_VERSION = 2
PROTOCOL_ID = "dante-o4a-corrected-edge-context-v2"
BASELINE_TAG = "3.7.0"
BASELINE_COMMIT = "67fc8b610277bea79f02757277d19696eee94b62"
DEFAULT_EXTERNAL_ROOT = "E:/dante_cache/dante_light/o4a_corrected_v2"


def _json_line(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _digest_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for row in rows:
        digest.update(_json_line(row))
        count += 1
    return digest.hexdigest(), count


def _raw_rows(root: Path) -> list[dict[str, Any]]:
    path = root / RAW_MANIFEST_REL
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows.sort(key=lambda row: (row["detector"], float(row["gps_start"])))
    keys = [(row["detector"], float(row["gps_start"]), float(row["gps_end"])) for row in rows]
    if len(keys) != 6_928 or len(set(keys)) != len(keys):
        raise ContractError("corrected O4a raw manifest is not the frozen unique-span corpus")
    return rows


def _session_ids(row: Mapping[str, Any]) -> list[int]:
    sessions = sorted(
        {
            int(Path(str(copy["relative_path"])).parts[0])
            for copy in row["physical_copies"]
        }
    )
    if not sessions:
        raise ContractError("raw span has no historical session membership")
    return sessions


def _components(rows: list[dict[str, Any]]) -> dict[str, list[tuple[float, float]]]:
    """Return detector-specific unions of overlapping or contiguous spans."""

    result: dict[str, list[tuple[float, float]]] = {}
    for detector in ("H1", "L1"):
        subset = [row for row in rows if row["detector"] == detector]
        merged: list[list[float]] = []
        for row in subset:
            start = float(row["gps_start"])
            end = float(row["gps_end"])
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        result[detector] = [(start, end) for start, end in merged]
    return result


def _raw_invalid_windows(root: Path) -> dict[tuple[str, float], tuple[str, ...]]:
    """Load the frozen sample-level target and whitening-context exclusions."""

    path = root / RAW_VALIDITY_REL
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = dict(value)
    digest = payload.pop("artifact_digest", None)
    if (
        digest != canonical_json_sha256(payload)
        or payload.get("schema_version") != 2
        or payload.get("status") != "PASS_COMPLETE_SAMPLE_LEVEL_VALIDITY_AUDIT"
        or payload.get("invalid_unique_window_count")
        != len(payload.get("invalid_windows", []))
        or payload.get("invalid_window_digest")
        != canonical_json_sha256(payload.get("invalid_windows", []))
        or payload.get("references", {}).get("raw_manifest")
        != repository_reference(root, root / RAW_MANIFEST_REL)
        or payload.get("references", {}).get("overlapping_raw_span_audit")
        != repository_reference(root, root / OVERLAP_AUDIT_REL)
    ):
        raise ContractError("corrected O4a raw-window validity artifact is invalid")
    result: dict[tuple[str, float], tuple[str, ...]] = {}
    for row in payload["invalid_windows"]:
        key = (str(row["detector"]), float(row["gps_start"]))
        reasons = tuple(sorted(str(reason) for reason in row["reasons"]))
        if key in result or not reasons:
            raise ContractError("duplicate or empty raw-window validity identity")
        result[key] = reasons
    return result


def iter_scan_identities(
    root: Path = ROOT, *, include_excluded: bool = False
) -> Iterator[dict[str, Any]]:
    """Yield the unique detector-window population in deterministic order."""

    rows = _raw_rows(root)
    invalid_windows = _raw_invalid_windows(root)
    components = _components(rows)
    for detector in ("H1", "L1"):
        subset = [row for row in rows if row["detector"] == detector]
        heap: list[tuple[float, int]] = []
        for index, row in enumerate(subset):
            start = float(row["gps_start"])
            if start + 32.0 <= float(row["gps_end"]):
                heapq.heappush(heap, (start, index))
        component_index = 0
        while heap:
            current, index = heapq.heappop(heap)
            source_indices = [index]
            while heap and heap[0][0] == current:
                source_indices.append(heapq.heappop(heap)[1])
            source_rows = [subset[source_index] for source_index in source_indices]
            for source_index in source_indices:
                following = current + 32.0
                source_end = float(subset[source_index]["gps_end"])
                if following + 32.0 <= source_end:
                    heapq.heappush(heap, (following, source_index))
            while not (
                components[detector][component_index][0]
                <= current
                < components[detector][component_index][1]
            ):
                component_index += 1
            component_start, component_end = components[detector][component_index]
            sessions = sorted(
                {session for row in source_rows for session in _session_ids(row)}
            )
            source_rows.sort(
                key=lambda row: (
                    float(row["gps_end"]) - float(row["gps_start"]),
                    float(row["gps_start"]),
                    float(row["gps_end"]),
                    str(row["sha256"]),
                )
            )
            chosen = source_rows[0]
            required = (current - 4.0, current + 36.0)
            complete = component_start <= required[0] and required[1] <= component_end
            invalid_reasons = list(invalid_windows.get((detector, current), ()))
            exclusion_reasons = list(invalid_reasons)
            if not complete:
                exclusion_reasons.append("INCOMPLETE_SYMMETRIC_4S_CONTEXT")
            eligible = complete and not invalid_reasons
            if eligible or include_excluded:
                yield {
                    "detector": detector,
                    "analysis_gps_start": current,
                    "duration_s": 32.0,
                    "historical_session_ids": sessions,
                    "source_span": [
                        float(chosen["gps_start"]),
                        float(chosen["gps_end"]),
                    ],
                    "source_sha256": str(chosen["sha256"]),
                    "overlapping_source_count": len(source_rows),
                    "overlapping_source_digest": canonical_json_sha256(
                        [
                            {
                                "interval": [
                                    float(row["gps_start"]),
                                    float(row["gps_end"]),
                                ],
                                "sha256": str(row["sha256"]),
                            }
                            for row in source_rows
                        ]
                    ),
                    "required_padded_interval": list(required),
                    "context_disposition": (
                        "COMPLETE_SYMMETRIC_4S_VALID_RAW"
                        if eligible
                        else (
                            "EXCLUDED_INVALID_RAW_OR_WHITENING_CONTEXT"
                            if invalid_reasons
                            else "EXCLUDED_COMPONENT_EDGE"
                        )
                    ),
                    "exclusion_reasons": exclusion_reasons,
                }


def _calibration_files(root: Path) -> list[Path]:
    files = sorted((root / "data/production").rglob("novelties_*.h5"))
    if len(files) != 84:
        raise ContractError("historical primary calibration file count changed")
    return files


def _historical_calibration_spans(
    root: Path,
) -> dict[tuple[str, int], tuple[tuple[float, float], ...]]:
    """Recover the exact per-session raw-file geometry seen by v1.

    The legacy :class:`PatchProducer` enumerated files inside a session
    directory independently.  The same physical interval can also exist in a
    different session directory, so using the detector-wide union here would
    make some historical edge identities ambiguous.  Physical-copy membership
    in the frozen raw manifest resolves that ambiguity without consulting any
    score or downstream outcome.
    """

    grouped: dict[tuple[str, int], set[tuple[float, float]]] = defaultdict(set)
    for row in _raw_rows(root):
        detector = str(row["detector"])
        interval = (float(row["gps_start"]), float(row["gps_end"]))
        for copy in row["physical_copies"]:
            parts = Path(str(copy["relative_path"])).parts
            if not parts or not parts[0].isdigit():
                raise ContractError("raw physical copy lacks a session directory")
            grouped[(detector, int(parts[0]))].add(interval)
    return {
        key: tuple(sorted(intervals))
        for key, intervals in grouped.items()
    }


def _historical_calibration_geometry(
    *,
    session_id: int,
    detector: str,
    catalog_gps_start: float,
    session_spans: Mapping[
        tuple[str, int], tuple[tuple[float, float], ...]
    ],
) -> dict[str, Any]:
    """Decode the overloaded GPS written by the legacy edge-bugged producer.

    v1 stored ``t0`` of the *cropped context*, not the analysis-window start.
    For an interior or right-edge window this is ``analysis_start - 4 s``;
    for the first window of a file the missing left pad makes it equal to the
    analysis start itself.  The frozen per-session file geometry makes the
    mapping unique and outcome-blind.
    """

    candidates: list[tuple[str, float, float]] = []
    current_start = catalog_gps_start + 4.0
    for span_start, span_end in session_spans.get((detector, session_id), ()):
        if catalog_gps_start == span_start and catalog_gps_start + 32.0 <= span_end:
            candidates.append(("HISTORICAL_LEFT_TRUNCATED_4S", span_start, span_end))
        step = (current_start - span_start) / 32.0
        if (
            step >= 1.0
            and abs(step - round(step)) < 1.0e-9
            and current_start + 32.0 <= span_end
        ):
            disposition = (
                "HISTORICAL_RIGHT_TRUNCATED_4S"
                if current_start + 32.0 == span_end
                else "HISTORICAL_FULL_SYMMETRIC_4S"
            )
            candidates.append((disposition, span_start, span_end))
    candidates = sorted(set(candidates))
    if len(candidates) != 1:
        raise ContractError(
            "historical calibration GPS does not resolve uniquely from its "
            f"session file geometry: {session_id} {detector} "
            f"{catalog_gps_start} -> {candidates}"
        )
    disposition, source_start, source_end = candidates[0]
    analysis_start = (
        catalog_gps_start
        if disposition == "HISTORICAL_LEFT_TRUNCATED_4S"
        else catalog_gps_start + 4.0
    )
    historical_context = (
        [catalog_gps_start, catalog_gps_start + 40.0]
        if disposition == "HISTORICAL_FULL_SYMMETRIC_4S"
        else [catalog_gps_start, catalog_gps_start + 36.0]
    )
    return {
        "analysis_gps_start": analysis_start,
        "required_padded_interval": [analysis_start - 4.0, analysis_start + 36.0],
        "historical_context_disposition": disposition,
        "historical_context_interval": historical_context,
        "historical_source_span": [source_start, source_end],
        "replay_disposition": (
            "REQUIRE_EXACT_REPLAY"
            if disposition == "HISTORICAL_FULL_SYMMETRIC_4S"
            else "CORRECTED_CONTEXT_NO_REPLAY"
        ),
    }


def iter_calibration_identities(root: Path = ROOT) -> Iterator[dict[str, Any]]:
    """Yield every historical per-session p99 identity, without reusing scores."""

    from src.dante_light.o4a_dependency_audit import _coverage_kind, _manifest_spans

    spans = _manifest_spans(root / RAW_MANIFEST_REL)
    session_spans = _historical_calibration_spans(root)
    for path in _calibration_files(root):
        detector = "H1" if path.stem.endswith("_H1") else "L1"
        session_id = int(path.parent.name)
        with h5py.File(path, "r") as handle:
            gps = np.asarray(handle["background_sample/gps_times"], dtype=np.float64)
            scores = np.asarray(handle["background_sample/novelty_scores"], dtype=np.float32)
            if len(gps) != len(scores):
                raise ContractError(f"calibration identity/score length mismatch: {path}")
            for value, historical_score in zip(gps, scores, strict=True):
                start = float(value)
                geometry = _historical_calibration_geometry(
                    session_id=session_id,
                    detector=detector,
                    catalog_gps_start=start,
                    session_spans=session_spans,
                )
                required_start, required_end = geometry["required_padded_interval"]
                yield {
                    "session_id": session_id,
                    "detector": detector,
                    "catalog_gps_start": start,
                    **geometry,
                    "coverage_in_frozen_raw_manifest": _coverage_kind(
                        spans[detector], required_start, required_end
                    ),
                    "historical_score_float32_hex": np.float32(historical_score).tobytes().hex(),
                    "historical_hdf5": path.relative_to(root).as_posix(),
                }


def _scan_population(root: Path) -> dict[str, Any]:
    all_rows = iter_scan_identities(root, include_excluded=True)
    eligible_digest = hashlib.sha256()
    excluded_digest = hashlib.sha256()
    eligible = Counter()
    excluded = Counter()
    memberships = Counter()
    unique = Counter()
    duplicate_memberships = Counter()
    excluded_unique = Counter()
    excluded_reasons = Counter()
    matched_raw_invalid = Counter()
    for row in all_rows:
        detector = row["detector"]
        unique[detector] += 1
        duplicate_memberships[detector] += int(row["overlapping_source_count"]) - 1
        memberships[detector] += len(row["historical_session_ids"])
        if row["context_disposition"] == "COMPLETE_SYMMETRIC_4S_VALID_RAW":
            eligible_digest.update(_json_line(row))
            eligible[detector] += 1
        else:
            excluded_digest.update(_json_line(row))
            excluded[detector] += 1
            excluded_unique[detector] += 1
            for reason in row["exclusion_reasons"]:
                excluded_reasons[(detector, reason)] += 1
            if any(reason != "INCOMPLETE_SYMMETRIC_4S_CONTEXT" for reason in row["exclusion_reasons"]):
                matched_raw_invalid[detector] += 1
    frozen_invalid = Counter(detector for detector, _gps in _raw_invalid_windows(root))
    if (
        unique != {"H1": 441_912, "L1": 441_392}
        or duplicate_memberships != {"H1": 72, "L1": 328}
        or matched_raw_invalid != frozen_invalid
        or eligible + excluded != unique
    ):
        raise ContractError("corrected O4a scan population counts changed")
    return {
        "identity_unit": "unique_detector_32s_window",
        "eligible_counts": dict(eligible),
        "eligible_total": sum(eligible.values()),
        "eligible_identity_jsonl_sha256": eligible_digest.hexdigest(),
        "unique_window_counts_before_context_exclusion": dict(unique),
        "overlapping_span_duplicate_window_memberships": dict(duplicate_memberships),
        "excluded_component_edge_counts": {
            detector: int(excluded_reasons[(detector, "INCOMPLETE_SYMMETRIC_4S_CONTEXT")])
            for detector in ("H1", "L1")
        },
        "excluded_component_edge_total": sum(
            value
            for (detector, reason), value in excluded_reasons.items()
            if reason == "INCOMPLETE_SYMMETRIC_4S_CONTEXT"
        ),
        "excluded_invalid_raw_or_context_counts": dict(frozen_invalid),
        "excluded_invalid_raw_or_context_total": sum(frozen_invalid.values()),
        "excluded_unique_counts": dict(excluded_unique),
        "excluded_unique_total": sum(excluded_unique.values()),
        "excluded_reason_counts": {
            f"{detector}/{reason}": int(value)
            for (detector, reason), value in sorted(excluded_reasons.items())
        },
        "excluded_identity_jsonl_sha256": excluded_digest.hexdigest(),
        "historical_session_membership_counts": dict(memberships),
        "duplicate_span_policy": (
            "score each detector+GPS once; compare against every historical session "
            "membership; if more than one threshold is exceeded, retain the earliest "
            "passing session, matching historical candidate-first deduplication"
        ),
    }


def _calibration_population(root: Path) -> dict[str, Any]:
    rows = list(iter_calibration_identities(root))
    digest, count = _digest_rows(rows)
    coverage = Counter(
        (row["detector"], row["coverage_in_frozen_raw_manifest"]) for row in rows
    )
    historical_context = Counter(
        (row["detector"], row["historical_context_disposition"]) for row in rows
    )
    replay = Counter((row["detector"], row["replay_disposition"]) for row in rows)
    sessions = Counter(row["detector"] for row in {  # type: ignore[arg-type]
        (row["session_id"], row["detector"]): row for row in rows
    }.values())
    if count != 39_971 or sessions != {"H1": 42, "L1": 42}:
        raise ContractError("corrected O4a calibration population changed")
    references = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_path(path),
        }
        for path in _calibration_files(root)
    ]
    return {
        "identity_count": count,
        "identity_jsonl_sha256": digest,
        "session_detector_counts": dict(sessions),
        "coverage_counts": {
            f"{detector}/{kind}": int(value)
            for (detector, kind), value in sorted(coverage.items())
        },
        "historical_context_counts": {
            f"{detector}/{kind}": int(value)
            for (detector, kind), value in sorted(historical_context.items())
        },
        "replay_disposition_counts": {
            f"{detector}/{kind}": int(value)
            for (detector, kind), value in sorted(replay.items())
        },
        "source_hdf5_count": len(references),
        "source_hdf5_reference_digest": canonical_json_sha256(references),
        "source_hdf5_references": references,
        "score_reuse_allowed": False,
        "recalibration": {
            "estimator": "numpy.percentile(scores, 99.0)",
            "identities": "exact historical background_sample/gps_times",
            "identity_interpretation": (
                "decode legacy context-t0 with frozen per-session file geometry; "
                "left-edge analysis=t0, otherwise analysis=t0+4s"
            ),
            "corrected_context": "always [analysis_start-4s, analysis_start+36s]",
            "historical_exact_replay_scope": (
                "only identities whose v1 source already supplied symmetric 4s context"
            ),
            "comparison": "candidate primary score > session p99",
            "post_hoc_retuning_allowed": False,
        },
        "missing_local_policy": (
            "fetch the exact corrected 40s detector interval from GWOSC into a "
            "content-addressed E: cache; bind hashes before scoring"
        ),
    }


def build_corrected_protocol(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    references = {
        label: repository_reference(root, root / relative)
        for label, relative in {
            "raw_manifest": RAW_MANIFEST_REL,
            "raw_identity_audit": RAW_AUDIT_REL,
            "dependency_impact_audit": DEPENDENCY_AUDIT_REL,
            "raw_window_validity_audit": RAW_VALIDITY_REL,
            "overlapping_raw_span_audit": OVERLAP_AUDIT_REL,
            "reference_artifacts": REFERENCE_REL,
            "runtime_config": RUNTIME_CONFIG_REL,
            "dq_snapshot": DQ_SNAPSHOT_REL,
            "protocol_implementation": PROTOCOL_CODE_REL,
            "patch_producer": PATCH_PRODUCER_REL,
            "preprocessor": PREPROCESSOR_REL,
            "patch_scorer": SCORER_REL,
        }.items()
    }
    representation = RepresentationContract.from_reference_manifest(root / REFERENCE_REL)
    if (
        representation.primary_index_sha256
        != "9053477ed2f30ed866fc42ff32265957e6a0eb93238032359f5e45e2f032bb7c"
        or representation.top_k != 68
        or representation.whitening_pad_s != 4.0
    ):
        raise ContractError("frozen production representation changed")
    dependency = json.loads((root / DEPENDENCY_AUDIT_REL).read_text(encoding="utf-8"))
    if dependency["dependencies"]["primary_o3b_index"]["disposition"] != "UNAFFECTED_BY_O4A_PATCHPRODUCER_EDGE_DEFECT":
        raise ContractError("O3b primary-index dependency is not cleared")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_BEFORE_INPUT_ACQUISITION_OR_SCORING",
        "protocol_id": PROTOCOL_ID,
        "historical_baseline": {
            "tag": BASELINE_TAG,
            "commit": BASELINE_COMMIT,
            "outputs_immutable": True,
        },
        "scientific_change": {
            "only_intended_change": "complete symmetric whitening context at raw-file boundaries",
            "legacy_calibration_gps_decoding": (
                "edge-aware from frozen per-session source-file geometry"
            ),
            "whitening_before_crop": True,
            "left_context_s": representation.whitening_pad_s,
            "right_context_s": representation.whitening_pad_s,
            "incomplete_context": "record_and_skip_fail_closed",
            "invalid_raw_or_whitening_context": "record_and_skip_fail_closed",
            "threshold_or_score_tolerance_change": False,
        },
        "representation": representation.to_dict(),
        "calibration_population": _calibration_population(root),
        "scan_population": _scan_population(root),
        "execution_order": [
            "acquire_and_hash_missing_frozen_calibration_intervals",
            "rescore_all_39971_historical_primary_calibration_identities",
            "freeze_all_84_session_detector_empirical_p99_thresholds",
            "score_all_unique_complete_context_and_sample_valid_primary_windows",
            "materialize_primary_candidates_with_any_session_threshold_semantics",
            "rebuild_detector_aware_O4a_native_index_excluding_corrected_primary_candidates",
            "rescore_frozen_native_calibration_ledgers_and_freeze_detector_thresholds",
            "native_rescore_and_detector_aware_classification_of_corrected_candidates",
            "taxonomy_coincidence_PEM_and_report_reconstruction",
            "v1_vs_corrected_claim_audit",
        ],
        "external_output": {
            "default_root": DEFAULT_EXTERNAL_ROOT,
            "historical_data_production_mutation_allowed": False,
            "atomic_shards_and_resume_required": True,
            "large_ledgers_committed_to_git": False,
            "compact_hash_bound_summaries_committed": True,
        },
        "scientific_boundary": {
            "retrospective_corrective_reconstruction": True,
            "independent_prospective_validation": False,
            "complete_O4a_livetime_claim": False,
            "population_is_frozen_local_raw_mirror": True,
            "publication_or_submission_authorized": False,
            "historical_paper_claims_remain_unqualified_until_reconstruction_finishes": True,
        },
        "source_references": references,
    }
    return {**body, "protocol_digest": canonical_json_sha256(body)}


def validate_corrected_protocol(value: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("protocol_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("corrected O4a protocol self-digest mismatch")
    rebuilt = build_corrected_protocol(root)
    if dict(value) != rebuilt:
        raise ContractError("corrected O4a protocol is stale")
    return dict(value)


def write_corrected_protocol(
    path: Path = ROOT / OUTPUT_REL, root: Path = ROOT
) -> dict[str, Any]:
    value = build_corrected_protocol(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return value
