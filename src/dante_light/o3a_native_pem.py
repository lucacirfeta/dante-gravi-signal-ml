"""O3a-only diagnostic PEM preflight and frozen input selection.

This module does not load the historical O4a PEM adapter or its provenance
reconciliation. The O4a contract is a method reference, never a data source.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import ROOT
from src.dante_light.o3a_raw_acquisition import _inventory_frames, load_source_inventory
from src.dante_light.o3a_raw_download import file_sha256

CONTRACT_REL = Path("config/dante_o3a_native_pem_v1.json")
DEFAULT_EXTERNAL_ROOT = Path("/mnt/e/dante_cache/dante_light/o3a_native_v1")
EXPECTED_STATUS = "PREFLIGHT_O3A_NATIVE_PEM_V1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"O3a PEM expected JSON object: {path}")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not all(isinstance(row, dict) for row in rows):
        raise ContractError(f"O3a PEM expected JSONL objects: {path}")
    return rows


def _sealed(value: Mapping[str, Any], key: str) -> None:
    body = dict(value)
    if body.pop(key, None) != canonical_json_sha256(body):
        raise ContractError(f"O3a PEM {key} seal changed")


def _verified_file(root: Path, reference: Mapping[str, Any]) -> Path:
    path = (root / str(reference["path"])).resolve()
    if not path.is_relative_to(root.resolve()) or file_sha256(path) != reference["sha256"]:
        raise ContractError(f"O3a PEM parent file changed: {path}")
    return path


def load_contract(*, root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    value = _read_json(root / CONTRACT_REL)
    _sealed(value, "contract_digest")
    if value.get("schema_version") != 1 or value.get("status") != EXPECTED_STATUS or value.get("run") != "O3A":
        raise ContractError("O3a PEM contract identity changed")
    method = _read_json(_verified_file(root, value["method_reference"]))
    _sealed(method, "contract_digest")
    expected_measurement = {
        key: item for key, item in method["measurement"].items()
        if key != "candidate_exclusion_population"
    }
    if value.get("measurement") != expected_measurement:
        raise ContractError("O3a PEM frozen measurement method changed")
    channels = value["channels"]
    if set(channels) != {"H1", "L1", "channel_count_per_detector", "explicitly_excluded", "public_subset_is_complete_sensor_network"}:
        raise ContractError("O3a PEM channel policy fields changed")
    if (
        any(
            len(channels[detector]) != int(channels["channel_count_per_detector"])
            or len(set(channels[detector])) != len(channels[detector])
            for detector in ("H1", "L1")
        )
        or any(not set(channels[detector]).issubset(method["channels"][detector]) for detector in ("H1", "L1"))
        or set(channels["H1"] + channels["L1"]) & set(method["channels"]["explicitly_excluded"])
        or channels["explicitly_excluded"] != method["channels"]["explicitly_excluded"]
        or channels["public_subset_is_complete_sensor_network"] is not False
    ):
        raise ContractError("O3a PEM public five-channel subset changed")
    boundary = value["scientific_boundary"]
    if boundary != {
        "diagnostic_only": True,
        "o4a_comparison_performed": False,
        "global_significance_claim": False,
        "astrophysical_confirmation_claim": False,
        "uncalibrated_is_negative": False,
        "primary_and_diagnostic_combined": False,
        "a2_promoted": False,
        "unreleased_sensors_cleared": False,
    }:
        raise ContractError("O3a PEM scientific boundary changed")
    for reference in value["parents"].values():
        _verified_file(root, reference)
    coincidence = _read_json(root / value["parents"]["coincidence"]["path"])
    classification = _read_json(root / value["parents"]["classification"]["path"])
    _sealed(coincidence, "artifact_digest")
    _sealed(classification, "artifact_digest")
    if (
        coincidence["artifact_digest"] != value["parents"]["coincidence"]["artifact_digest"]
        or classification["artifact_digest"] != value["parents"]["classification"]["artifact_digest"]
        or coincidence["status"] != "PASS_VERIFIED_O3A_NATIVE_COINCIDENCE"
        or classification["status"] != "PASS_VERIFIED_O3A_NATIVE_CLASSIFICATION"
        or classification["row_total"] != value["population"]["candidate_exclusion_total"]
    ):
        raise ContractError("O3a PEM verified parent identity changed")
    coincidence_contract = _read_json(root / value["parents"]["coincidence_contract"]["path"])
    _sealed(coincidence_contract, "contract_digest")
    if (
        coincidence_contract["contract_digest"] != coincidence["contract_digest"]
        or coincidence_contract["measurement"]["segment_duration_s"] != value["measurement"]["event_window_s"]
        or coincidence_contract["measurement"]["sample_rate_hz"]
        != load_source_inventory(root=root)["source_query"]["sample_rate_hz"]
    ):
        raise ContractError("O3a PEM event geometry changed")
    return value


def _external_rows(
    *, root: Path, contract: Mapping[str, Any], external_root: Path,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    coincidence = _read_json(root / contract["parents"]["coincidence"]["path"])
    classification = _read_json(root / contract["parents"]["classification"]["path"])
    coincidence_dir = external_root / f"native_coincidence_{coincidence['run_key']}"
    classification_dir = external_root / f"native_classification_{classification['run_key']}"
    observed: dict[str, list[dict[str, Any]]] = {}
    for bucket in ("primary", "diagnostic"):
        spec = coincidence["outputs"][bucket]
        path = coincidence_dir / spec["filename"]
        rows = _jsonl(path)
        if (
            file_sha256(path) != spec["sha256"]
            or canonical_json_sha256(rows) != spec["row_digest"]
            or len(rows) != spec["row_total"]
        ):
            raise ContractError(f"O3a PEM coincidence {bucket} ledger changed")
        observed[bucket] = rows
    path = classification_dir / "native_classified_candidates.jsonl"
    classified = _jsonl(path)
    if (
        file_sha256(path) != classification["output_sha256"]
        or canonical_json_sha256(classified) != classification["output_row_digest"]
        or len(classified) != contract["population"]["candidate_exclusion_total"]
    ):
        raise ContractError("O3a PEM full candidate-exclusion ledger changed")
    return observed, classified


def _check_sources(
    sources: Sequence[Mapping[str, Any]], *, detector: str, gps: int,
    pad: int, duration: int, inventory_frames: Mapping[str, Mapping[str, Any]],
) -> None:
    cursor = gps - pad
    end = gps + duration + pad
    if not sources:
        raise ContractError("O3a PEM raw context has no source")
    for source in sources:
        used_start, used_end = (int(x) for x in source["used_interval_gps"])
        frame_start, frame_end = int(source["gps_start"]), int(source["gps_end"])
        digest = str(source["sha256"])
        published = inventory_frames.get(str(source["filename"]))
        if (
            source["detector"] != detector
            or published is None
            or any(source[key] != published[key] for key in ("filename", "gps_start", "gps_end", "url"))
            or used_start != cursor
            or not (frame_start <= used_start < used_end <= frame_end)
            or len(digest) != 64
            or not all(ch in "0123456789abcdef" for ch in digest)
            or int(source["size_bytes"]) <= 0
            or not str(source["url"]).startswith("https://")
        ):
            raise ContractError("O3a PEM raw source coverage or identity changed")
        cursor = used_end
    if cursor != end:
        raise ContractError("O3a PEM raw context is incomplete")


def preflight_inputs(
    *, root: Path = ROOT, external_root: Path = DEFAULT_EXTERNAL_ROOT,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[float]]:
    root, external_root = root.resolve(), external_root.resolve()
    contract = load_contract(root=root)
    coincidence_rows, classified = _external_rows(root=root, contract=contract, external_root=external_root)
    coincidence_contract = _read_json(root / contract["parents"]["coincidence_contract"]["path"])
    measurement = coincidence_contract["measurement"]
    pad = int(measurement["whitening_pad_s"])
    duration = int(measurement["segment_duration_s"])
    inventory = load_source_inventory(root=root)
    inventory_frames = {
        detector: {frame["filename"]: frame for frame in _inventory_frames(inventory, detector)}
        for detector in ("H1", "L1")
    }
    by_key = {(str(row["detector"]), int(row["gps_start"])): row for row in classified}
    if len(by_key) != len(classified):
        raise ContractError("O3a PEM classification identities are not unique")
    targets: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for bucket, label in (("primary", "ROBUST"), ("diagnostic", "AMBIGUOUS")):
        for row in coincidence_rows[bucket]:
            if row["exceeds_primary_threshold"] is not True:
                continue
            detector, gps = str(row["detector"]), int(row["gps_start"])
            key = detector, gps
            classified_row = by_key.get(key)
            if (
                key in seen or detector not in ("H1", "L1")
                or classified_row is None
                or row["population"] != bucket
                or row["measurement_status"] != "MEASURED"
                or row["seed_native_class"] != label
                or classified_row["native_class"] != label
                or classified_row["identity_digest"] != row["seed_identity_digest"]
                or classified_row["raw_context_sha256"] != row["seed_raw_context_sha256"]
                or classified_row["image_sha256"] != row["seed_image_sha256"]
                or not np.isfinite(float(row["seed_native_score"]))
                or float(classified_row["native_score"]) != float(row["seed_native_score"])
            ):
                raise ContractError("O3a PEM selected target identity changed")
            _check_sources(
                classified_row["context_sources"], detector=detector, gps=gps,
                pad=pad, duration=duration, inventory_frames=inventory_frames[detector],
            )
            seen.add(key)
            targets.append({
                "population": bucket,
                "detector": detector,
                "gps_start": gps,
                "native_class": label,
                "native_score": float(row["seed_native_score"]),
                "identity_digest": row["seed_identity_digest"],
                "image_sha256": row["seed_image_sha256"],
                "raw_context_sha256": row["seed_raw_context_sha256"],
                "context_sources": classified_row["context_sources"],
                "cc_onsource": float(row["cc_onsource"]),
            })
    targets.sort(key=lambda row: (row["gps_start"], row["detector"]))
    counts = {bucket: Counter(row["detector"] for row in targets if row["population"] == bucket) for bucket in ("primary", "diagnostic")}
    for bucket in counts:
        expected = contract["population"][bucket]
        if any(counts[bucket][detector] != expected[detector] for detector in ("H1", "L1")) or sum(counts[bucket].values()) != expected["total"]:
            raise ContractError(f"O3a PEM selected {bucket} count changed")
    if len(targets) != contract["population"]["exact_total"]:
        raise ContractError("O3a PEM total selected target count changed")
    exclusion = [float(row["gps_start"]) for row in classified]
    if not np.isfinite(exclusion).all():
        raise ContractError("O3a PEM candidate-exclusion GPS is invalid")
    body = {
        "status": "PASS_O3A_NATIVE_PEM_INPUT_PREFLIGHT",
        "contract_digest": contract["contract_digest"],
        "target_total": len(targets),
        "target_digest": canonical_json_sha256(targets),
        "candidate_exclusion_total": len(exclusion),
        "candidate_exclusion_digest": canonical_json_sha256(exclusion),
        "strain_opened": False,
        "pem_outcomes_opened": False,
    }
    return {**body, "preflight_digest": canonical_json_sha256(body)}, targets, exclusion


__all__ = ["CONTRACT_REL", "DEFAULT_EXTERNAL_ROOT", "load_contract", "preflight_inputs"]
