"""Dependency-impact audit for the corrected O4a reconstruction."""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import h5py
import numpy as np

from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import sha256_path


ROOT = Path(__file__).resolve().parents[2]
RAW_MANIFEST = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"
REFERENCE_MANIFEST = ROOT / "config/reference_artifacts.json"
O3B_INDEX = ROOT / "data/reference/patch_compressed_index_o3b.npz"
O3B_BUILD = ROOT / "data/reference/build"
O4A_INDEX = ROOT / "data/reference/patch_compressed_index_o4a_q4-64_ex.npz"
O4A_INDEX_LEDGER = ROOT / "data/reference/patch_compressed_index_o4a_q4-64_ex.t_bg.json"
THRESHOLDS = ROOT / "data/production/aggregated/dsd_thresholds_o4a_idxq4-64_queryq4-64.json"
OUTPUT = ROOT / "artifacts/dante_light/o4a_v1_parity/dependency_impact_audit.json"


def _manifest_spans(path: Path = RAW_MANIFEST) -> dict[str, list[tuple[float, float]]]:
    spans = {"H1": [], "L1": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        spans[row["detector"]].append(
            (float(row["gps_start"]), float(row["gps_end"]))
        )
    for detector in spans:
        spans[detector].sort()
    return spans


def _coverage_kind(
    spans: Iterable[tuple[float, float]], start: float, end: float
) -> str:
    spans = list(spans)
    if any(left <= start and right >= end for left, right in spans):
        return "complete_single_file"
    cursor = start
    for left, right in spans:
        if right <= start or left >= end:
            continue
        if left > cursor:
            break
        cursor = max(cursor, right)
        if cursor >= end:
            return "complete_only_by_stitch"
    return "not_complete_in_frozen_local_manifest"


def _o3b_index_audit() -> dict[str, Any]:
    index = np.load(O3B_INDEX, allow_pickle=False)
    actual_labels = Counter(str(value) for value in index["labels"].tolist())
    corpus_results = {}
    all_sidecars = []
    for corpus in ("o3b_h1", "o3b_l1"):
        root = O3B_BUILD / corpus
        image_counts = {
            child.name: len(list(child.glob("*.png")))
            for child in root.iterdir()
            if child.is_dir()
        }
        expected_labels = {
            label: min(64, max(8, count // 2))
            for label, count in image_counts.items()
            if count
        }
        sidecars = []
        for path in root.rglob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            sidecars.append(value)
            all_sidecars.append(value)
        corpus_results[corpus] = {
            "image_count": int(sum(image_counts.values())),
            "sidecar_count": len(sidecars),
            "all_sidecars_complete_pad": all(
                value.get("preprocessor_version") == "whiten_context_v1"
                and value.get("partial_pad") is False
                and float(value.get("effective_pad")) == 4.0
                for value in sidecars
            ),
            "builder_label_distribution_matches_index": expected_labels
            == dict(actual_labels),
        }
    matching = [
        name
        for name, value in corpus_results.items()
        if value["builder_label_distribution_matches_index"]
    ]
    if matching != ["o3b_l1"] or not all(
        value.get("partial_pad") is False
        and float(value.get("effective_pad")) == 4.0
        for value in all_sidecars
    ):
        raise RuntimeError("O3b reference provenance no longer supports the audit")
    return {
        "disposition": "UNAFFECTED_BY_O4A_PATCHPRODUCER_EDGE_DEFECT",
        "index_sha256": sha256_path(O3B_INDEX),
        "index_centroids": int(index["embeddings"].shape[0]),
        "index_label_count": int(len(index["labels"])),
        "matched_builder_corpus": matching[0],
        "corpora": corpus_results,
        "complete_pad_sidecars": len(all_sidecars),
        "boundary": (
            "This establishes absence of incomplete padding in the preserved "
            "source images; it does not independently reproduce K-means centroids."
        ),
    }


def _o4a_index_audit(spans: Mapping[str, list[tuple[float, float]]]) -> dict[str, Any]:
    times = [
        float(value)
        for value in json.loads(O4A_INDEX_LEDGER.read_text(encoding="utf-8"))
    ]
    by_detector = {}
    cross_sets = {}
    for detector in ("H1", "L1"):
        counts = Counter(
            _coverage_kind(spans[detector], value - 20.0, value + 20.0)
            for value in times
        )
        cross = {
            value
            for value in times
            if _coverage_kind(spans[detector], value - 20.0, value + 20.0)
            == "complete_only_by_stitch"
        }
        cross_sets[detector] = cross
        by_detector[detector] = dict(sorted(counts.items()))
    definite = sorted(cross_sets["H1"] & cross_sets["L1"])
    source = (ROOT / "src/pipeline_v3_multiscale/norm_leakage/common.py").read_text(
        encoding="utf-8"
    )
    if "edge_tolerance=4.0" not in source or "ts_w_padded, _ = whiten_context" not in source:
        raise RuntimeError("historical native-index preprocessing signature changed")
    if not definite:
        raise RuntimeError("native-index audit did not retain a definite edge cohort")
    return {
        "disposition": "REBUILD_REQUIRED",
        "index_sha256": sha256_path(O4A_INDEX),
        "training_ledger_sha256": sha256_path(O4A_INDEX_LEDGER),
        "training_windows": len(times),
        "ledger_missing_detector_identity": True,
        "coverage_if_assigned_to_detector": by_detector,
        "definitely_cross_boundary_regardless_of_detector_count": len(definite),
        "definitely_cross_boundary_gps": definite,
        "causal_code_evidence": {
            "edge_tolerance_s": 4.0,
            "padding_result_was_not_checked": True,
            "source_path": "src/pipeline_v3_multiscale/norm_leakage/common.py",
            "source_sha256": sha256_path(
                ROOT / "src/pipeline_v3_multiscale/norm_leakage/common.py"
            ),
        },
        "reason": (
            "At least four training identities require stitching for both "
            "possible detector assignments, while the frozen builder accepted "
            "a four-second edge tolerance and ignored effective padding."
        ),
    }


def _primary_calibration_audit(
    spans: Mapping[str, list[tuple[float, float]]]
) -> dict[str, Any]:
    required_pairs = set()
    for line in RAW_MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        relative = Path(
            sorted(
                row["physical_copies"], key=lambda item: item["relative_path"]
            )[0]["relative_path"]
        )
        required_pairs.add((relative.parts[0], row["detector"]))
    counts = Counter()
    required_counts = Counter()
    identities = []
    files = sorted((ROOT / "data/production").rglob("novelties_*.h5"))
    for path in files:
        detector = "H1" if path.stem.endswith("_H1") else "L1"
        with h5py.File(path, "r") as handle:
            key = "background_sample/gps_times"
            if key not in handle:
                continue
            for catalog_gps in np.asarray(handle[key], dtype=np.float64):
                # Historical labels were the padded-crop start. The scored
                # analysis window was [gps+4, gps+36], requiring [gps,gps+40].
                kind = _coverage_kind(
                    spans[detector], float(catalog_gps), float(catalog_gps) + 40.0
                )
                counts[(detector, kind)] += 1
                identities.append(
                    (path.relative_to(ROOT).as_posix(), detector, float(catalog_gps), kind)
                )
                if (path.parent.name, detector) in required_pairs:
                    required_counts[(detector, kind)] += 1
    cross = sum(
        counts[(detector, "complete_only_by_stitch")] for detector in ("H1", "L1")
    )
    unresolved = sum(
        counts[(detector, "not_complete_in_frozen_local_manifest")]
        for detector in ("H1", "L1")
    )
    if cross != 246 or unresolved != 15:
        raise RuntimeError("historical primary-calibration edge counts changed")
    return {
        "disposition": "RECOMPUTE_SAME_FROZEN_IDENTITIES",
        "hdf5_session_files": len(files),
        "background_identity_count": len(identities),
        "canonical_session_detector_count": len(required_pairs),
        "canonical_calibration_identity_count": sum(required_counts.values()),
        "canonical_counts": {
            f"{detector}/{kind}": int(value)
            for (detector, kind), value in sorted(required_counts.items())
        },
        "historical_unused_calibration_identity_count": len(identities)
        - sum(required_counts.values()),
        "counts": {
            f"{detector}/{kind}": int(value)
            for (detector, kind), value in sorted(counts.items())
        },
        "cross_boundary_count": cross,
        "not_complete_in_local_manifest_count": unresolved,
        "identity_audit_digest": canonical_json_sha256(identities),
        "reason": (
            "The historical per-session primary thresholds contain 246 "
            "calibration windows scored with incomplete file-edge context."
        ),
    }


def _native_calibration_audit() -> dict[str, Any]:
    thresholds = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    result = {}
    for detector, value in thresholds["thresholds"].items():
        path = ROOT / str(value["background_ledger_path"]).replace("\\", "/")
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        incomplete = [
            row
            for row in rows
            if float(row["gps_start"]) - float(row["source_start"]) < 4.0
            or float(row["source_end"]) - float(row["gps_end"]) < 4.0
        ]
        result[detector] = {
            "ledger_path": path.relative_to(ROOT).as_posix(),
            "ledger_sha256": sha256_path(path),
            "window_count": len(rows),
            "incomplete_padding_count": len(incomplete),
            "window_preprocessing_disposition": "UNAFFECTED",
            "score_disposition": "RECOMPUTE_AFTER_NATIVE_INDEX_REBUILD",
        }
    if any(value["incomplete_padding_count"] for value in result.values()):
        raise RuntimeError("native calibration ledger unexpectedly contains partial padding")
    return {
        "disposition": "RECOMPUTE_AFTER_NATIVE_INDEX_REBUILD",
        "threshold_artifact_sha256": sha256_path(THRESHOLDS),
        "detectors": result,
        "reason": (
            "The 10,000 calibration windows have complete padding, but every "
            "stored score depends on the O4a native index that must be rebuilt."
        ),
    }


def build_dependency_audit() -> dict[str, Any]:
    spans = _manifest_spans()
    body = {
        "schema_version": 1,
        "status": "REBUILD_CHAIN_REQUIRED",
        "raw_manifest": {
            "path": RAW_MANIFEST.relative_to(ROOT).as_posix(),
            "sha256": sha256_path(RAW_MANIFEST),
            "unique_spans": sum(len(value) for value in spans.values()),
        },
        "dependencies": {
            "primary_o3b_index": _o3b_index_audit(),
            "historical_primary_session_calibrations": _primary_calibration_audit(
                spans
            ),
            "native_o4a_index": _o4a_index_audit(spans),
            "native_o4a_detector_thresholds": _native_calibration_audit(),
            "historical_taxonomy_and_downstream": {
                "disposition": "REBUILD_AFTER_CORRECTED_PRIMARY_SCAN",
                "includes": [
                    "candidate catalogue and scores",
                    "detector-aware taxonomy",
                    "coincidence",
                    "PEM association",
                    "figures, tables and reports",
                ],
            },
            "o4b_artifacts_bound_to_old_o4a_teacher": {
                "disposition": "HISTORICAL_ONLY_PENDING_SEPARATE_REVALIDATION",
                "reason": (
                    "Existing O4b DANTE-Light receipts bind the affected O4a "
                    "native index and thresholds; they are not inputs to the "
                    "corrected O4a run and are not silently promoted."
                ),
            },
        },
        "required_order": [
            "recompute frozen primary session calibrations with complete context",
            "run full unique-span O4a primary discovery",
            "rebuild native O4a index excluding corrected primary candidates",
            "recompute native detector thresholds on the frozen calibration ledgers",
            "rescore and classify corrected candidates",
            "rebuild taxonomy, coincidence, PEM and report chain",
        ],
        "scientific_boundary": {
            "no_posthoc_threshold_adjustment": True,
            "published_artifacts_remain_immutable": True,
            "does_not_validate_corrected_catalogue": True,
            "does_not_authorize_o4b_reinterpretation": True,
        },
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def write_dependency_audit(path: Path = OUTPUT) -> dict[str, Any]:
    value = build_dependency_audit()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return value
