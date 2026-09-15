"""Frozen, outcome-blind cohorts for the multiscale efficiency v2 study.

This module performs identity selection only.  It never opens strain, model
outputs, scores, thresholds, or taxonomy fields.  Source blocks already used
by the canonical O4a native index or native calibration are removed before
four mutually disjoint roles are allocated: short-scale index, short-scale
calibration, primary injections, and secondary DSD controls.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.dante_light.contracts import ContractError, canonical_json_sha256

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_REL = Path("config/dante_multiscale_efficiency_v2.json")
SCHEMA_VERSION = 1
FORBIDDEN_OUTCOME_FIELDS = {
    "primary_score",
    "native_score",
    "score",
    "score_hex",
    "threshold",
    "threshold_lower",
    "threshold_upper",
    "class",
    "robustness_class",
    "taxonomy",
    "taxonomy_family",
    "disposition",
    "detected",
    "recovered",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            )
    temporary.replace(path)


def _assert_sha256(value: Any, label: str) -> str:
    text = str(value)
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ContractError(f"{label} is not a lowercase SHA-256")
    return text


def validate_contract(payload: Mapping[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Validate the approved protocol and all repository-bound inputs."""

    value = json.loads(json.dumps(payload))
    declared = value.pop("contract_digest", None)
    if declared != canonical_json_sha256(value):
        raise ContractError("multiscale-efficiency-v2 contract digest mismatch")
    value["contract_digest"] = declared
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ContractError("unsupported multiscale-efficiency-v2 schema")
    if value.get("contract_id") != "dante-multiscale-efficiency-v2":
        raise ContractError("multiscale-efficiency-v2 contract id changed")
    if value.get("status") != "APPROVED_OUTCOME_BLIND_FREEZE_INPUT":
        raise ContractError("multiscale-efficiency-v2 is not approved and frozen")

    population = value.get("population", {})
    if population.get("detectors") != ["H1", "L1"]:
        raise ContractError("detector order changed")
    roles = population.get("roles", {})
    expected = {
        "short_scale_index": {"identities_per_detector": 500},
        "short_scale_calibration": {"identities_per_detector": 5000},
        "primary_injection": {"source_blocks_per_detector": 100},
        "secondary_dsd_control": {"source_blocks_per_detector": 40},
    }
    for role, fields in expected.items():
        if role not in roles:
            raise ContractError(f"missing frozen role: {role}")
        for field, expected_value in fields.items():
            if int(roles[role].get(field, -1)) != expected_value:
                raise ContractError(f"{role} {field} changed")
    if roles["primary_injection"].get("morphologies") != [
        "Blip",
        "NarrowChirp",
        "Whistle",
        "ScatteredLight",
        "NoiseBlob",
    ]:
        raise ContractError("primary morphology population changed")
    if roles["secondary_dsd_control"].get("morphologies") != [
        "HarmonicComb",
        "WallOfLines",
        "KoiFish",
    ]:
        raise ContractError("secondary DSD population changed")
    if roles["primary_injection"].get("target_snr") != [8, 12, 16, 24, 32, 48]:
        raise ContractError("primary SNR grid changed")
    if roles["secondary_dsd_control"].get("target_snr") != [8, 12, 16, 24, 32, 48]:
        raise ContractError("secondary SNR grid changed")

    selection = population.get("selection", {})
    required_selection = {
        "selection_reads_identity_and_candidate_firewall_only": True,
        "candidate_guard_is_cross_detector": True,
        "single_raw_block_context_required": True,
        "raw_block_roles_mutually_disjoint": True,
        "canonical_index_blocks_excluded": True,
        "canonical_calibration_blocks_excluded": True,
    }
    if any(selection.get(k) is not v for k, v in required_selection.items()):
        raise ContractError("outcome-blind selection boundary changed")
    if float(selection.get("candidate_start_guard_s", -1.0)) != 128.0:
        raise ContractError("candidate guard changed")
    if float(selection.get("within_role_minimum_separation_s", -1.0)) != 96.0:
        raise ContractError("within-role guard changed")
    forbidden = set(value.get("scientific_boundary", {}).get("forbidden_fields", []))
    if not FORBIDDEN_OUTCOME_FIELDS <= forbidden:
        raise ContractError("outcome firewall changed")
    endpoints = value.get("endpoints", {})
    if (
        endpoints.get("primary")
        != "end_to_end_32s_discovery_then_multiscale_characterization"
    ):
        raise ContractError("primary endpoint changed")
    if endpoints.get("diagnostic") != "conditional_multiscale_component_response":
        raise ContractError("diagnostic endpoint changed")
    if endpoints.get("scale_or_fusion_allowed") is not False:
        raise ContractError("scale OR-fusion must remain disabled")
    if endpoints.get("morphology_rate_upper_limit_allowed") is not False:
        raise ContractError("morphology rate upper limits are not authorized")
    uncertainty = value.get("uncertainty", {})
    if uncertainty.get("method") != "detector_raw_source_block_bootstrap":
        raise ContractError("uncertainty must remain raw-block based")
    if float(uncertainty.get("percentile", -1.0)) != 99.0:
        raise ContractError("bootstrap percentile changed")
    if int(uncertainty.get("n_resamples", -1)) != 2000:
        raise ContractError("bootstrap replicate count changed")
    if float(uncertainty.get("confidence", -1.0)) != 0.95:
        raise ContractError("bootstrap confidence changed")
    if uncertainty.get("iid_bootstrap_allowed") is not False:
        raise ContractError("i.i.d. bootstrap is forbidden")

    preprocessing = value.get("preprocessing", {})
    if (
        int(preprocessing.get("sample_rate_hz", -1)) != 4096
        or float(preprocessing.get("analysis_duration_s", -1.0)) != 32.0
        or float(preprocessing.get("whitening_pad_s", -1.0)) != 4.0
        or preprocessing.get("bandpass_hz") != [20.0, 2000.0]
        or preprocessing.get("whitening_before_crop") is not True
    ):
        raise ContractError("preprocessing geometry changed")
    representation = value.get("representation", {})
    expected_representation = {
        "frequency_range_hz": [20, 2048],
        "image_shape": [256, 256, 3],
        "colormap": "cividis",
        "encoder_model": "dinov2_vits14_reg",
        "encoder_input_size": 518,
        "embedding_dimension": 384,
        "patch_tokens_per_image": 1369,
    }
    if any(
        representation.get(key) != expected
        for key, expected in expected_representation.items()
    ):
        raise ContractError("representation geometry changed")
    conditional = representation.get("conditional_multiscale", {})
    if conditional.get("scales_s") != [0.5, 1.0, 2.0, 4.0]:
        raise ContractError("multiscale durations changed")
    if conditional.get("alignment") != "centered_on_32s_window_midpoint":
        raise ContractError("multiscale alignment changed")
    if conditional.get("qrange") != [4, 32] or int(conditional.get("top_k", -1)) != 68:
        raise ContractError("multiscale scoring geometry changed")
    if int(conditional.get("centroids_per_detector_scale", -1)) != 275:
        raise ContractError("multiscale centroid count changed")

    for name, reference in value.get("references", {}).items():
        path = root / str(reference["path"])
        expected_digest = _assert_sha256(reference["sha256"], f"reference {name}")
        if not path.is_file() or sha256_file(path) != expected_digest:
            raise ContractError(f"repository reference mismatch: {path}")
    for name, external in value.get("external_inputs", {}).items():
        _assert_sha256(external["sha256"], f"external input {name}")
    return value


def load_contract(root: Path = ROOT) -> dict[str, Any]:
    return validate_contract(
        json.loads((root / CONTRACT_REL).read_text(encoding="utf-8")), root.resolve()
    )


def _load_raw_manifest(path: Path) -> dict[str, list[dict[str, Any]]]:
    by_detector: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    seen: set[tuple[str, float, float]] = set()
    for row in _read_jsonl(path):
        detector = str(row.get("detector"))
        if detector not in by_detector:
            continue
        start = float(row["gps_start"])
        end = float(row["gps_end"])
        key = (detector, start, end)
        if key in seen:
            raise ContractError("duplicate logical raw block in frozen manifest")
        seen.add(key)
        copies = row.get("physical_copies", [])
        if not copies:
            raise ContractError("raw manifest block has no physical copy")
        copy = min(copies, key=lambda item: str(item["relative_path"]))
        digest = _assert_sha256(row["sha256"], "raw manifest digest")
        if str(copy.get("sha256")) != digest:
            raise ContractError("raw manifest physical/logical digest mismatch")
        by_detector[detector].append(
            {
                "detector": detector,
                "gps_start": start,
                "gps_end": end,
                "source_relative_path": str(copy["relative_path"]).replace("\\", "/"),
                "source_sha256": digest,
            }
        )
    for detector_rows in by_detector.values():
        detector_rows.sort(key=lambda row: (row["gps_start"], row["gps_end"]))
    return by_detector


def _block_for_gps(
    blocks: Sequence[Mapping[str, Any]], gps_start: float
) -> dict[str, Any]:
    pos = (
        bisect.bisect_right(blocks, gps_start, key=lambda row: float(row["gps_start"]))
        - 1
    )
    if pos < 0 or not (
        float(blocks[pos]["gps_start"]) <= gps_start < float(blocks[pos]["gps_end"])
    ):
        raise ContractError(f"GPS {gps_start} is absent from frozen raw manifest")
    return dict(blocks[pos])


def _block_key(row: Mapping[str, Any]) -> tuple[str, float, float, str]:
    return (
        str(row["detector"]),
        float(row["gps_start"]),
        float(row["gps_end"]),
        str(row["source_sha256"]),
    )


def _scan_geometry(
    database_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[float]]:
    """Read only identity geometry and the explicit candidate firewall."""

    uri = f"file:{database_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            "SELECT detector,gps_start,image_sha256,is_candidate,identity_digest "
            "FROM windows ORDER BY detector,gps_start"
        ).fetchall()
    finally:
        connection.close()
    geometry: dict[str, list[dict[str, Any]]] = {"H1": [], "L1": []}
    candidates: list[float] = []
    for detector, gps, image_sha, is_candidate, identity_digest in rows:
        detector = str(detector)
        if detector not in geometry:
            raise ContractError("unexpected detector in primary scan")
        row = {
            "detector": detector,
            "gps_start": float(gps),
            "expected_clean_image_sha256": _assert_sha256(image_sha, "image digest"),
            "source_identity_digest": _assert_sha256(
                identity_digest, "identity digest"
            ),
        }
        geometry[detector].append(row)
        if bool(is_candidate):
            candidates.append(float(gps))
    return geometry, sorted(set(candidates))


def _within_guard(value: float, sorted_values: Sequence[float], guard: float) -> bool:
    pos = bisect.bisect_right(sorted_values, value - guard)
    return pos < len(sorted_values) and sorted_values[pos] < value + guard


def _priority(contract_digest: str, role: str, detector: str, value: str) -> str:
    return hashlib.sha256(
        f"{contract_digest}|{role}|{detector}|{value}".encode("ascii")
    ).hexdigest()


def _guarded_rows(
    rows: Sequence[Mapping[str, Any]], *, minimum_separation_s: float
) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    times: list[float] = []
    for row in rows:
        gps = float(row["gps_start"])
        if not _within_guard(gps, sorted(times), minimum_separation_s):
            bisect.insort(times, gps)
            accepted.append(dict(row))
    return accepted


def _canonical_forbidden_blocks(
    *,
    raw_blocks: Mapping[str, Sequence[Mapping[str, Any]]],
    native_index_manifest: Path,
    native_index_cohort_ledger: Path,
    native_calibration_ledger: Path,
) -> set[tuple[str, float, float, str]]:
    forbidden: set[tuple[str, float, float, str]] = set()
    index_value = json.loads(native_index_manifest.read_text(encoding="utf-8"))
    manifest_rows = index_value.get("rows", [])
    cohort_rows = _read_jsonl(native_index_cohort_ledger)
    if len(manifest_rows) != len(cohort_rows):
        raise ContractError("native index manifest/cohort row count mismatch")

    def add_context_source(detector: str, source: Mapping[str, Any]) -> None:
        start, end = map(float, source["block_interval"])
        matches = [
            block
            for block in raw_blocks[detector]
            if float(block["gps_start"]) == start and float(block["gps_end"]) == end
        ]
        if len(matches) != 1:
            raise ContractError("canonical context block is absent from raw manifest")
        source_digest = str(source.get("source_sha256", source.get("sha256")))
        if source_digest != str(matches[0]["source_sha256"]):
            raise ContractError("canonical context raw digest mismatch")
        forbidden.add(_block_key(matches[0]))

    for manifest_row, cohort_row in zip(manifest_rows, cohort_rows, strict=True):
        manifest_identity = (
            str(manifest_row["detector"]),
            float(manifest_row["gps_start"]),
            str(manifest_row["identity_digest"]),
            str(manifest_row["context_sources_digest"]),
        )
        cohort_identity = (
            str(cohort_row["detector"]),
            float(cohort_row["gps_start"]),
            str(cohort_row["identity_digest"]),
            str(cohort_row["context_sources_digest"]),
        )
        if manifest_identity != cohort_identity:
            raise ContractError("native index manifest/cohort identity mismatch")
        for source in cohort_row.get("context_sources", []):
            add_context_source(str(cohort_row["detector"]), source)

    for row in _read_jsonl(native_calibration_ledger):
        detector = str(row["detector"])
        for source in row.get("context_sources", []):
            add_context_source(detector, source)
    return forbidden


def select_cohort_rows(
    *,
    contract: Mapping[str, Any],
    raw_blocks: Mapping[str, Sequence[Mapping[str, Any]]],
    scan_geometry: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate_times: Sequence[float],
    canonical_forbidden_blocks: set[tuple[str, float, float, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Allocate mutually disjoint roles from geometry-only inputs."""

    digest = str(contract["contract_digest"])
    selection = contract["population"]["selection"]
    guard = float(selection["candidate_start_guard_s"])
    separation = float(selection["within_role_minimum_separation_s"])
    pad = float(contract["preprocessing"]["whitening_pad_s"])
    window = float(contract["preprocessing"]["analysis_duration_s"])
    roles = contract["population"]["roles"]
    role_order = [
        "short_scale_index",
        "short_scale_calibration",
        "primary_injection",
        "secondary_dsd_control",
    ]
    selected: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    used_blocks = set(canonical_forbidden_blocks)

    for detector in contract["population"]["detectors"]:
        blocks = raw_blocks[detector]
        candidates_by_block: dict[
            tuple[str, float, float, str], list[dict[str, Any]]
        ] = {}
        rejected_candidate_guard = 0
        rejected_context = 0
        rejected_canonical_block = 0
        for geometry_row in scan_geometry[detector]:
            gps = float(geometry_row["gps_start"])
            if _within_guard(gps, candidate_times, guard):
                rejected_candidate_guard += 1
                continue
            block = _block_for_gps(blocks, gps)
            key = _block_key(block)
            if key in canonical_forbidden_blocks:
                rejected_canonical_block += 1
                continue
            if gps - pad < float(block["gps_start"]) or gps + window + pad > float(
                block["gps_end"]
            ):
                rejected_context += 1
                continue
            candidates_by_block.setdefault(key, []).append(
                {
                    **dict(geometry_row),
                    "gps_end": gps + window,
                    "context_interval": [gps - pad, gps + window + pad],
                    "raw_block": dict(block),
                }
            )

        detector_audit: dict[str, Any] = {
            "candidate_guard_rejections": rejected_candidate_guard,
            "canonical_block_rejections": rejected_canonical_block,
            "single_block_context_rejections": rejected_context,
            "candidate_blocks_available": len(candidates_by_block),
            "roles": {},
        }
        for role in role_order:
            spec = roles[role]
            available_keys = [
                key for key in candidates_by_block if key not in used_blocks
            ]
            available_keys.sort(
                key=lambda key: _priority(
                    digest, role, detector, f"{key[1]:.9f}|{key[2]:.9f}|{key[3]}"
                )
            )
            role_rows: list[dict[str, Any]] = []
            role_blocks: list[tuple[str, float, float, str]] = []
            target_identities = int(spec.get("identities_per_detector", 0))
            target_blocks = int(spec.get("source_blocks_per_detector", 0))
            for key in available_keys:
                ordered = sorted(
                    candidates_by_block[key],
                    key=lambda row: _priority(
                        digest, role, detector, f"{float(row['gps_start']):.9f}"
                    ),
                )
                guarded = _guarded_rows(ordered, minimum_separation_s=separation)
                if not guarded:
                    continue
                if role in {
                    "short_scale_index",
                    "primary_injection",
                    "secondary_dsd_control",
                }:
                    guarded = guarded[:1]
                role_blocks.append(key)
                block_index = len(role_blocks) - 1
                for row in guarded:
                    role_rows.append(
                        {
                            **row,
                            "role": role,
                            "role_block_index": block_index,
                            "selection_priority": _priority(
                                digest, role, detector, f"{float(row['gps_start']):.9f}"
                            ),
                        }
                    )
                if target_blocks and len(role_blocks) >= target_blocks:
                    break
                if target_identities and len(role_rows) >= target_identities:
                    break
            if target_blocks and len(role_blocks) != target_blocks:
                raise ContractError(f"{detector} {role} block pool is incomplete")
            if target_identities:
                if len(role_rows) < target_identities:
                    raise ContractError(
                        f"{detector} {role} identity pool is incomplete"
                    )
                role_rows = role_rows[:target_identities]
                used_role_blocks = {_block_key(row["raw_block"]) for row in role_rows}
                role_blocks = [key for key in role_blocks if key in used_role_blocks]
            used_blocks.update(role_blocks)
            for role_index, row in enumerate(role_rows):
                identity_body = {
                    "contract_digest": digest,
                    "role": role,
                    "detector": detector,
                    "gps_start": float(row["gps_start"]),
                    "raw_source_sha256": str(row["raw_block"]["source_sha256"]),
                }
                row["role_index"] = role_index
                row["identity_digest"] = canonical_json_sha256(identity_body)
            selected.extend(role_rows)
            detector_audit["roles"][role] = {
                "selected_rows": len(role_rows),
                "selected_blocks": len(set(role_blocks)),
            }
        audit[detector] = detector_audit

    selected.sort(
        key=lambda row: (str(row["detector"]), str(row["role"]), int(row["role_index"]))
    )
    for row_number, row in enumerate(selected):
        row["row_number"] = row_number
        if FORBIDDEN_OUTCOME_FIELDS & set(row):
            raise ContractError("frozen cohort contains a forbidden outcome field")
    return selected, audit


def _row_digest(rows: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        digest.update(
            json.dumps(
                row, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _verify_external(path: Path, expected_sha256: str, label: str) -> None:
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise ContractError(f"external input mismatch: {label}: {path}")


def _expected_run_key(contract: Mapping[str, Any]) -> str:
    external = contract["external_inputs"]
    return canonical_json_sha256(
        {
            "stage": "freeze_multiscale_efficiency_v2",
            "contract_digest": contract["contract_digest"],
            "primary_scan_database_sha256": external["primary_scan_database"]["sha256"],
            "native_index_manifest_sha256": external["native_index_manifest"]["sha256"],
            "native_index_cohort_ledger_sha256": external["native_index_cohort_ledger"][
                "sha256"
            ],
            "native_calibration_ledger_sha256": external["native_calibration_ledger"][
                "sha256"
            ],
        }
    )


def _verify_rows(
    rows: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]
) -> tuple[dict[tuple[str, str], int], dict[tuple[str, str], int]]:
    seen_blocks: dict[tuple[str, float, float, str], str] = {}
    role_counts: dict[tuple[str, str], int] = {}
    role_blocks: dict[tuple[str, str], set[tuple[str, float, float, str]]] = {}
    role_times: dict[tuple[str, str], list[float]] = {}
    role_indices: dict[tuple[str, str], list[int]] = {}
    detectors = set(contract["population"]["detectors"])
    roles = contract["population"]["roles"]
    separation = float(
        contract["population"]["selection"]["within_role_minimum_separation_s"]
    )
    pad = float(contract["preprocessing"]["whitening_pad_s"])
    window = float(contract["preprocessing"]["analysis_duration_s"])
    digest = str(contract["contract_digest"])
    for expected_row_number, row in enumerate(rows):
        if int(row.get("row_number", -1)) != expected_row_number:
            raise ContractError("cohort row order is not canonical")
        if FORBIDDEN_OUTCOME_FIELDS & set(row):
            raise ContractError("cohort ledger contains outcome fields")
        detector = str(row.get("detector"))
        role = str(row.get("role"))
        if detector not in detectors or role not in roles:
            raise ContractError("cohort ledger contains an unknown detector or role")
        if "raw_block" not in row:
            raise ContractError("cohort row has no raw-block provenance")
        raw_block = row["raw_block"]
        key = (
            detector,
            float(raw_block["gps_start"]),
            float(raw_block["gps_end"]),
            _assert_sha256(raw_block["source_sha256"], "cohort raw source digest"),
        )
        previous_role = seen_blocks.setdefault(key, role)
        if previous_role != role:
            raise ContractError("raw block is shared by multiple v2 roles")
        gps = float(row["gps_start"])
        if float(row["gps_end"]) != gps + window:
            raise ContractError("cohort analysis interval changed")
        expected_context = [gps - pad, gps + window + pad]
        if [float(value) for value in row["context_interval"]] != expected_context:
            raise ContractError("cohort context interval changed")
        if expected_context[0] < key[1] or expected_context[1] > key[2]:
            raise ContractError("cohort context crosses a raw-block boundary")
        expected_priority = _priority(digest, role, detector, f"{gps:.9f}")
        if row.get("selection_priority") != expected_priority:
            raise ContractError("cohort selection priority mismatch")
        identity_body = {
            "contract_digest": digest,
            "role": role,
            "detector": detector,
            "gps_start": gps,
            "raw_source_sha256": key[3],
        }
        if row.get("identity_digest") != canonical_json_sha256(identity_body):
            raise ContractError("cohort identity digest mismatch")
        detector_role = (detector, role)
        role_indices.setdefault(detector_role, []).append(
            int(row.get("role_index", -1))
        )
        times = role_times.setdefault(detector_role, [])
        if _within_guard(gps, times, separation):
            raise ContractError("cohort within-role separation changed")
        bisect.insort(times, gps)
        role_counts[detector_role] = role_counts.get(detector_role, 0) + 1
        role_blocks.setdefault(detector_role, set()).add(key)

    expected: dict[str, int] = {
        "short_scale_index": int(roles["short_scale_index"]["identities_per_detector"]),
        "short_scale_calibration": int(
            roles["short_scale_calibration"]["identities_per_detector"]
        ),
        "primary_injection": int(
            roles["primary_injection"]["source_blocks_per_detector"]
        ),
        "secondary_dsd_control": int(
            roles["secondary_dsd_control"]["source_blocks_per_detector"]
        ),
    }
    for detector in contract["population"]["detectors"]:
        for role, count in expected.items():
            if role_counts.get((detector, role), 0) != count:
                raise ContractError(f"cohort cardinality mismatch: {detector}/{role}")
            if sorted(role_indices.get((detector, role), [])) != list(range(count)):
                raise ContractError(f"cohort role index mismatch: {detector}/{role}")
            if (
                role
                in {
                    "short_scale_index",
                    "primary_injection",
                    "secondary_dsd_control",
                }
                and len(role_blocks.get((detector, role), set())) != count
            ):
                raise ContractError(
                    f"cohort one-block-per-identity mismatch: {detector}/{role}"
                )
    return role_counts, {key: len(value) for key, value in role_blocks.items()}


def freeze_cohort(
    *,
    root: Path = ROOT,
    primary_scan_db: Path,
    native_index_manifest: Path,
    native_index_cohort_ledger: Path,
    native_calibration_ledger: Path,
    external_root: Path,
) -> tuple[dict[str, Any], Path]:
    root = root.resolve()
    contract = load_contract(root)
    external = contract["external_inputs"]
    _verify_external(
        primary_scan_db, external["primary_scan_database"]["sha256"], "primary scan"
    )
    _verify_external(
        native_index_manifest,
        external["native_index_manifest"]["sha256"],
        "native index manifest",
    )
    _verify_external(
        native_index_cohort_ledger,
        external["native_index_cohort_ledger"]["sha256"],
        "native index cohort ledger",
    )
    _verify_external(
        native_calibration_ledger,
        external["native_calibration_ledger"]["sha256"],
        "native calibration ledger",
    )

    raw_manifest_path = root / contract["references"]["raw_manifest"]["path"]
    raw_blocks = _load_raw_manifest(raw_manifest_path)
    geometry, candidate_times = _scan_geometry(primary_scan_db)
    forbidden = _canonical_forbidden_blocks(
        raw_blocks=raw_blocks,
        native_index_manifest=native_index_manifest,
        native_index_cohort_ledger=native_index_cohort_ledger,
        native_calibration_ledger=native_calibration_ledger,
    )
    rows, audit = select_cohort_rows(
        contract=contract,
        raw_blocks=raw_blocks,
        scan_geometry=geometry,
        candidate_times=candidate_times,
        canonical_forbidden_blocks=forbidden,
    )
    run_key = _expected_run_key(contract)
    run_dir = external_root.resolve() / f"cohort_{run_key}"
    ledger_path = run_dir / "multiscale_efficiency_v2_cohort.jsonl"
    summary_path = run_dir / "multiscale_efficiency_v2_cohort_summary.json"
    if run_dir.exists():
        verified = verify_cohort(run_dir=run_dir, root=root)
        if verified["ledger"]["row_digest"] != _row_digest(rows):
            raise ContractError("existing cohort diverges from deterministic selection")
        if verified.get("audit") != audit:
            raise ContractError(
                "existing cohort audit diverges from deterministic selection"
            )
        if int(verified.get("canonical_forbidden_raw_blocks", -1)) != len(forbidden):
            raise ContractError("existing cohort canonical exclusion count changed")
        return verified, run_dir
    run_dir.mkdir(parents=True, exist_ok=False)
    _atomic_jsonl(ledger_path, rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS_FROZEN_MULTISCALE_EFFICIENCY_V2_COHORT",
        "run_key": run_key,
        "contract_digest": contract["contract_digest"],
        "ledger": {
            "filename": ledger_path.name,
            "row_total": len(rows),
            "row_digest": _row_digest(rows),
            "sha256": sha256_file(ledger_path),
        },
        "canonical_forbidden_raw_blocks": len(forbidden),
        "audit": audit,
        "scientific_boundary": contract["scientific_boundary"],
    }
    summary["artifact_digest"] = canonical_json_sha256(summary)
    _atomic_json(summary_path, summary)
    return verify_cohort(run_dir=run_dir, root=root), run_dir


def verify_cohort(*, run_dir: Path, root: Path = ROOT) -> dict[str, Any]:
    contract = load_contract(root.resolve())
    summary_path = run_dir / "multiscale_efficiency_v2_cohort_summary.json"
    ledger_path = run_dir / "multiscale_efficiency_v2_cohort.jsonl"
    if not summary_path.is_file() or not ledger_path.is_file():
        raise ContractError("multiscale-efficiency-v2 cohort output is incomplete")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("contract_digest") != contract["contract_digest"]:
        raise ContractError("cohort contract digest mismatch")
    artifact = summary.pop("artifact_digest", None)
    if artifact != canonical_json_sha256(summary):
        raise ContractError("cohort artifact digest mismatch")
    summary["artifact_digest"] = artifact
    expected_run_key = _expected_run_key(contract)
    if (
        summary.get("run_key") != expected_run_key
        or run_dir.name != f"cohort_{expected_run_key}"
    ):
        raise ContractError("cohort run key mismatch")
    rows = _read_jsonl(ledger_path)
    if len(rows) != int(summary["ledger"]["row_total"]):
        raise ContractError("cohort row count mismatch")
    if sha256_file(ledger_path) != summary["ledger"]["sha256"]:
        raise ContractError("cohort ledger SHA-256 mismatch")
    if _row_digest(rows) != summary["ledger"]["row_digest"]:
        raise ContractError("cohort row digest mismatch")
    role_counts, role_blocks = _verify_rows(rows, contract)
    for detector in contract["population"]["detectors"]:
        for role in contract["population"]["roles"]:
            audit_role = (
                summary.get("audit", {})
                .get(detector, {})
                .get("roles", {})
                .get(role, {})
            )
            if int(audit_role.get("selected_rows", -1)) != role_counts.get(
                (detector, role), 0
            ):
                raise ContractError(
                    f"cohort audit row count mismatch: {detector}/{role}"
                )
            if int(audit_role.get("selected_blocks", -1)) != role_blocks.get(
                (detector, role), 0
            ):
                raise ContractError(
                    f"cohort audit block count mismatch: {detector}/{role}"
                )
    return summary


__all__ = [
    "CONTRACT_REL",
    "FORBIDDEN_OUTCOME_FIELDS",
    "ROOT",
    "freeze_cohort",
    "load_contract",
    "select_cohort_rows",
    "sha256_file",
    "validate_contract",
    "verify_cohort",
]
