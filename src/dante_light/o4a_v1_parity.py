"""Frozen retrospective O4a parity corpus for DANTE-Light.

The corpus is candidate-conditioned: its identities come from the published
detector-aware O4a taxonomy.  It is therefore suitable for exact replay and
non-regression, not for estimating discovery sensitivity on all O4a strain.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

import pandas as pd

from src.dante_light.contracts import (
    ContractError,
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)
from src.dante_light.evidence import SCORE_ATOL
from src.dante_light.prefilter_v5_protocol import repository_reference


ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_REL = "data/production/aggregated/Master_Taxonomy_O4a_idxq4-64_queryq4-64.csv"
THRESHOLDS_REL = "data/production/aggregated/dsd_thresholds_o4a_idxq4-64_queryq4-64.json"
RAW_MANIFEST_REL = "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"
RAW_AUDIT_REL = "artifacts/dante_light/prefilter_l4_v5_design/identity_audit_v5.json"
REFERENCE_REL = "config/reference_artifacts.json"
EPOCHS_REL = "config/dante_light_epochs_v1.json"
SEGMENTS_REL = "config/dante_light_prefilter_v4_segments.json"
SELECTION_CODE_REL = "src/dante_light/o4a_v1_parity.py"
ENTRIES_REL = "config/dante_light_o4a_v1_parity_manifest.jsonl"
MISSING_REL = "config/dante_light_o4a_v1_parity_missing.jsonl"

BASELINE_TAG = "3.7.0"
BASELINE_COMMIT = "67fc8b610277bea79f02757277d19696eee94b62"


def _reference(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.is_file():
        raise ContractError(f"missing parity source artifact: {relative}")
    return repository_reference(root, path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _jsonl_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
        for row in rows
    ).encode("utf-8")


def _offline_class(score: float, limits: Mapping[str, Any]) -> str:
    if score < float(limits["ci_lower"]):
        return "BACKGROUND"
    if score > float(limits["ci_upper"]):
        return "ROBUST"
    return "AMBIGUOUS"


def _git_tag_commit(root: Path, tag: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-list", "-n", "1", tag], cwd=root, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ContractError(f"cannot resolve baseline tag {tag}") from exc


def build_parity_freeze(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the immutable contract, header, full corpus and missing subset."""
    root = root.resolve()
    sources = {
        "taxonomy": _reference(root, TAXONOMY_REL),
        "thresholds": _reference(root, THRESHOLDS_REL),
        "raw_manifest": _reference(root, RAW_MANIFEST_REL),
        "raw_identity_audit": _reference(root, RAW_AUDIT_REL),
        "reference_artifacts": _reference(root, REFERENCE_REL),
        "historical_epochs": _reference(root, EPOCHS_REL),
        "o4a_dq_snapshot": _reference(root, SEGMENTS_REL),
        "selection_code": _reference(root, SELECTION_CODE_REL),
    }
    if _git_tag_commit(root, BASELINE_TAG) != BASELINE_COMMIT:
        raise ContractError("published v1 baseline tag no longer resolves to its frozen commit")

    thresholds = _read_json(root / THRESHOLDS_REL)
    representation = RepresentationContract.from_reference_manifest(root / REFERENCE_REL)
    offset = float(thresholds["representation"]["catalog_gps_to_analysis_window_offset_s"])
    if offset != representation.whitening_pad_s:
        raise ContractError("catalog offset and whitening pad differ")
    if thresholds["representation"]["index_sha256"] != representation.native_index_sha256:
        raise ContractError("threshold and representation native index differ")
    if SCORE_ATOL != 2.0e-7:
        raise ContractError("existing exact-replay score tolerance changed")

    raw_rows = _read_jsonl(root / RAW_MANIFEST_REL)
    dq_flags = _read_json(root / SEGMENTS_REL)["flags"]
    raw_by_detector = {
        detector: sorted(
            (row for row in raw_rows if row["detector"] == detector),
            key=lambda row: (float(row["gps_start"]), float(row["gps_end"])),
        )
        for detector in ("H1", "L1")
    }
    taxonomy = pd.read_csv(root / TAXONOMY_REL).sort_values(["detector", "gps_start"])
    class_column = "robustness_class_idxq4_64_queryq4_64"
    score_column = "native_score_idxq4_64_queryq4_64"
    if len(taxonomy) != 10_429 or taxonomy.duplicated(["detector", "gps_start"]).any():
        raise ContractError("published taxonomy is not the expected 10,429 unique detector+GPS corpus")

    entries: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for raw in taxonomy.to_dict("records"):
        detector = str(raw["detector"])
        catalog_gps = float(raw["gps_start"])
        analysis_gps = catalog_gps + offset
        required_start = analysis_gps - representation.whitening_pad_s
        required_end = analysis_gps + representation.analysis_duration_s + representation.whitening_pad_s
        cat1 = any(
            float(left) <= required_start and required_end <= float(right)
            for left, right in dq_flags[f"{detector}_O4A_CBC_CAT1"]["segments"]
        )
        injection_overlap = any(
            float(left) < required_end and required_start < float(right)
            for suffix in ("HW_INJ", "CBC_INJ", "BURST_INJ")
            for left, right in dq_flags[f"{detector}_O4A_{suffix}"]["segments"]
        )
        if not cat1 or injection_overlap:
            raise ContractError(f"published parity identity violates frozen O4a DQ at {detector} {catalog_gps}")
        hits = [
            row for row in raw_by_detector[detector]
            if float(row["gps_start"]) <= required_start
            and required_end <= float(row["gps_end"])
        ]
        hits.sort(
            key=lambda row: (
                float(row["gps_end"]) - float(row["gps_start"]),
                float(row["gps_start"]),
                str(row["sha256"]),
            )
        )
        source = None
        if hits:
            hit = hits[0]
            source = {
                "logical_root": "user_o4a_raw_mirror",
                "relative_path": hit["physical_copies"][0]["relative_path"],
                "file_sha256": hit["sha256"],
                "file_interval_gps": [float(hit["gps_start"]), float(hit["gps_end"])],
            }
        published_class = str(raw[class_column])
        score = float(raw[score_column])
        limits = thresholds["thresholds"][detector]
        computed_class = _offline_class(score, limits)
        if computed_class != published_class:
            raise ContractError(f"published DSD class mismatch at {detector} {catalog_gps}")
        window = WindowIdentity("O4A", detector, analysis_gps, representation.analysis_duration_s)
        body = {
            "schema_version": 1,
            "window": window.to_dict(),
            "catalog_identity": {"detector": detector, "gps_start": catalog_gps},
            "source": source,
            "required_padded_interval_gps": [required_start, required_end],
            "data_quality": {
                "frozen_cbc_cat1": True,
                "hardware_injection_overlap": False,
                "snapshot_path": SEGMENTS_REL,
            },
            "expected": {
                "published_native_score": score,
                "offline_class": published_class,
                "light_threshold": float(limits["p99"]),
                "light_disposition": "ESCALATE" if score >= float(limits["p99"]) else "ROUTINE",
            },
            "taxonomy": {
                "session_id": int(raw["session_id"]),
                "origin_table": str(raw["origin_table"]),
                "local_cluster_id": str(raw["local_cluster_id"]),
                "global_family_id": str(raw["global_family_id"]),
            },
        }
        entry = {**body, "case_id": f"o4a-v1-{canonical_json_sha256(body)[:24]}"}
        entries.append(entry)
        if source is None:
            missing.append({
                "case_id": entry["case_id"],
                "window": entry["window"],
                "catalog_identity": entry["catalog_identity"],
                "required_padded_interval_gps": entry["required_padded_interval_gps"],
                "data_quality": entry["data_quality"],
                "published_offline_class": published_class,
                "cache_target": {
                    "logical_root": "o4a_v1_comparison_cache",
                    "relative_path": f"raw/{detector}/{entry['case_id']}.hdf5",
                },
            })

    class_counts = Counter((row["catalog_identity"]["detector"], row["expected"]["offline_class"]) for row in entries)
    missing_counts = Counter((row["catalog_identity"]["detector"], row["published_offline_class"]) for row in missing)
    disposition_counts = Counter(row["expected"]["light_disposition"] for row in entries)
    escalation_classes = Counter(row["expected"]["offline_class"] for row in entries if row["expected"]["light_disposition"] == "ESCALATE")
    if disposition_counts != {"ESCALATE": 6984, "ROUTINE": 3445}:
        raise ContractError("historical Light dispositions changed")
    if escalation_classes != {"ROBUST": 6365, "AMBIGUOUS": 619}:
        raise ContractError("historical Light escalation classes changed")

    contract_body = {
        "schema_version": 1,
        "status": "FROZEN_BEFORE_RESCORING",
        "protocol_id": "dante-light-o4a-v1-retrospective-parity",
        "purpose": "candidate-conditioned exact replay against the published O4a v1 evidence",
        "scientific_boundary": {
            "retrospective_non_regression_only": True,
            "candidate_identities_selected_from_published_taxonomy": True,
            "establishes_full_o4a_discovery_sensitivity": False,
            "establishes_independent_prospective_validation": False,
            "may_change_thresholds_after_rescoring": False,
            "may_drop_missing_class_dependent_rows": False,
        },
        "published_baseline": {
            "git_tag": BASELINE_TAG,
            "git_commit": BASELINE_COMMIT,
            "software_doi": "10.5281/zenodo.21912589",
            "evidence_doi": "10.5281/zenodo.21925453",
        },
        "source_references": sources,
        "representation": representation.to_dict(),
        "comparison": {
            "score_absolute_tolerance": SCORE_ATOL,
            "score_tolerance_source": "src/dante_light/evidence.py::SCORE_ATOL",
            "offline_class_rule": "BACKGROUND if score < ci_lower; ROBUST if score > ci_upper; AMBIGUOUS otherwise",
            "light_routing_rule": "ESCALATE if native_score >= detector p99; ROUTINE otherwise",
            "thresholds_loaded_from": THRESHOLDS_REL,
            "mismatch_policy": "repeat_current_then_stage_hashes_then_git_tag_3.7.0; never retune",
        },
        "storage": {
            "raw_mirror": {"logical_id": "user_o4a_raw_mirror", "runtime_alias": "DANTE_O4A_RAW_ROOT", "mutated": False},
            "missing_cache": {"logical_id": "o4a_v1_comparison_cache", "runtime_alias": "DANTE_O4A_V1_PARITY_CACHE_ROOT"},
        },
    }
    contract = {**contract_body, "contract_digest": canonical_json_sha256(contract_body)}
    entries_bytes = _jsonl_bytes(entries)
    missing_bytes = _jsonl_bytes(missing)
    header_body = {
        "schema_version": 1,
        "status": "FROZEN_BEFORE_RESCORING",
        "contract_digest": contract["contract_digest"],
        "entries_path": ENTRIES_REL,
        "entries_file_sha256": hashlib.sha256(entries_bytes).hexdigest(),
        "entries_digest": canonical_json_sha256(entries),
        "missing_path": MISSING_REL,
        "missing_file_sha256": hashlib.sha256(missing_bytes).hexdigest(),
        "counts": {
            "entries": len(entries),
            "covered_by_raw_mirror": len(entries) - len(missing),
            "missing_from_raw_mirror": len(missing),
            "by_detector_and_class": {f"{k[0]}/{k[1]}": v for k, v in sorted(class_counts.items())},
            "missing_by_detector_and_class": {f"{k[0]}/{k[1]}": v for k, v in sorted(missing_counts.items())},
            "light_disposition": dict(sorted(disposition_counts.items())),
            "escalated_by_class": dict(sorted(escalation_classes.items())),
        },
    }
    header = {**header_body, "manifest_digest": canonical_json_sha256(header_body)}
    return contract, header, entries, missing


def validate_parity_freeze(
    contract: Mapping[str, Any], header: Mapping[str, Any], entries: list[dict[str, Any]],
    missing: list[dict[str, Any]], *, root: Path = ROOT,
) -> None:
    """Fail closed on any drift in the frozen retrospective corpus."""
    rebuilt = build_parity_freeze(root)
    if tuple(rebuilt) != (dict(contract), dict(header), entries, missing):
        raise ContractError("O4a v1 parity freeze differs from its source artifacts")
    contract_body = dict(contract); digest = contract_body.pop("contract_digest", None)
    if digest != canonical_json_sha256(contract_body):
        raise ContractError("parity contract self-digest mismatch")
    header_body = dict(header); digest = header_body.pop("manifest_digest", None)
    if digest != canonical_json_sha256(header_body):
        raise ContractError("parity manifest self-digest mismatch")
    if len(entries) != len({row["case_id"] for row in entries}):
        raise ContractError("duplicate parity case id")
    if len(entries) != len({(row["catalog_identity"]["detector"], row["catalog_identity"]["gps_start"]) for row in entries}):
        raise ContractError("duplicate parity detector+GPS identity")
    encoded = json.dumps({"contract": contract, "header": header, "entries": entries, "missing": missing}, sort_keys=True)
    if "E:\\" in encoded or "/mnt/e/" in encoded:
        raise ContractError("parity freeze contains a machine-specific path")


def write_parity_freeze(
    contract_path: Path, header_path: Path, contract: Mapping[str, Any], header: Mapping[str, Any],
    entries: list[dict[str, Any]], missing: list[dict[str, Any]],
) -> None:
    files = {
        contract_path: (json.dumps(contract, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
        header_path: (json.dumps(header, indent=2, sort_keys=True, allow_nan=False) + "\n").encode(),
        ROOT / ENTRIES_REL: _jsonl_bytes(entries),
        ROOT / MISSING_REL: _jsonl_bytes(missing),
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != content:
            raise ContractError(f"refusing to overwrite divergent frozen parity artifact: {path}")
        path.write_bytes(content)
