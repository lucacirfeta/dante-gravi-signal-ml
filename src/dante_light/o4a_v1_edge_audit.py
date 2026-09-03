"""Forensic audit of the historical O4a file-edge whitening defect.

This module does not repair or reinterpret the frozen v1 catalogue.  It binds
the completed canonical replay to its source hashes, identifies the exact
failure cohort, and records the candidate-conditioned effect of rescoring with
complete symmetric whitening context.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, RepresentationContract, canonical_json_sha256
from src.dante_light.evidence import SCORE_ATOL
from src.dante_light.o4a_v1_parity import ROOT, _offline_class, validate_parity_freeze
from src.dante_light.o4a_v1_parity_replay import EXECUTION_PATH, validate_execution_contract
from src.dante_light.prefilter_v5_protocol import sha256_path


DEFAULT_RUN_DIR = Path(
    "E:/dante_cache/dante_light/o4a_v1_comparison/"
    "score_da26be89a9c9100e4c756b288160b4aa78076fad788a86985499377e8daf648b"
)
DEFAULT_CACHE_ROOT = Path("E:/dante_cache/dante_light/o4a_v1_comparison")
DEFAULT_RAW_ROOT = Path("E:/o4a")
DEFAULT_OUTPUT = ROOT / "artifacts/dante_light/o4a_v1_parity/edge_padding_audit.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _record_id_is_valid(record: Mapping[str, Any]) -> bool:
    body = dict(record)
    record_id = body.pop("record_id", None)
    return record_id == f"dlr1-{canonical_json_sha256(body)[:24]}"


def _route(score: float, threshold: float) -> str:
    return "ESCALATE" if score >= threshold else "ROUTINE"


def _counter_dict(counter: Counter[tuple[str, ...]]) -> dict[str, int]:
    return {"/".join(key): int(value) for key, value in sorted(counter.items())}


def _validate_run_manifest(run_dir: Path, execution: Mapping[str, Any], entries: int) -> dict[str, Any]:
    manifest = _read_json(run_dir / "run_manifest.json")
    body = dict(manifest)
    digest = body.pop("manifest_sha256", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("edge audit: replay run manifest digest mismatch")
    if manifest.get("execution_digest") != execution.get("execution_digest"):
        raise ContractError("edge audit: replay belongs to another execution contract")
    if int(manifest.get("entries", -1)) != entries:
        raise ContractError("edge audit: replay population size mismatch")
    return manifest


def _load_frozen_population(root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    contract = _read_json(root / "config/dante_light_o4a_v1_parity_contract.json")
    header = _read_json(root / "config/dante_light_o4a_v1_parity_manifest.json")
    entries = _read_jsonl(root / str(header["entries_path"]))
    missing = _read_jsonl(root / str(header["missing_path"]))
    validate_parity_freeze(contract, header, entries, missing, root=root)
    return contract, header, entries, missing


def _load_cache_origins(cache_root: Path, missing: list[dict[str, Any]]) -> dict[str, str]:
    origins: dict[str, str] = {}
    for row in missing:
        record = _read_json(cache_root / "records" / f"{row['case_id']}.json")
        source = str(record.get("source"))
        if source not in {"verified_local_raw_stitch", "gwosc_open_data"}:
            raise ContractError(f"edge audit: invalid cache origin for {row['case_id']}")
        origins[str(row["case_id"])] = source
    return origins


def summarize_edge_failure(
    *, root: Path = ROOT, run_dir: Path = DEFAULT_RUN_DIR,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> dict[str, Any]:
    """Recompute the complete failure ledger without changing any gate."""
    execution = validate_execution_contract(_read_json(root / EXECUTION_PATH.relative_to(ROOT)), root=root)
    contract, header, entries, missing = _load_frozen_population(root)
    manifest = _validate_run_manifest(run_dir, execution, len(entries))
    summary = _read_json(run_dir / "summary.json")
    if summary.get("status") != "complete" or int(summary.get("records_total", -1)) != len(entries):
        raise ContractError("edge audit: canonical replay is not complete")
    if summary.get("executor", {}).get("deferred") or summary.get("executor", {}).get("drops") or summary.get("executor", {}).get("failures"):
        raise ContractError("edge audit: canonical replay contains executor failures")

    expected = {str(row["case_id"]): row for row in entries}
    edge = {str(row["case_id"]): row for row in missing}
    origins = _load_cache_origins(cache_root, missing)
    records = _read_jsonl(run_dir / "records.jsonl")
    if len(records) != len(entries):
        raise ContractError("edge audit: record count differs from the frozen population")

    thresholds = _read_json(
        root / "data/production/aggregated/dsd_thresholds_o4a_idxq4-64_queryq4-64.json"
    )["thresholds"]
    seen: set[str] = set()
    source_counts: Counter[tuple[str, ...]] = Counter()
    source_score_mismatches: Counter[tuple[str, ...]] = Counter()
    published_classes: Counter[tuple[str, ...]] = Counter()
    corrected_classes: Counter[tuple[str, ...]] = Counter()
    published_routes: Counter[tuple[str, ...]] = Counter()
    corrected_routes: Counter[tuple[str, ...]] = Counter()
    class_transitions: Counter[tuple[str, ...]] = Counter()
    route_transitions: Counter[tuple[str, ...]] = Counter()
    family_counts: Counter[tuple[str, ...]] = Counter()
    score_deltas: dict[str, list[float]] = {
        "existing_raw_mirror": [],
        "verified_local_raw_stitch": [],
        "gwosc_open_data": [],
    }

    for record in records:
        if not _record_id_is_valid(record):
            raise ContractError("edge audit: replay record digest mismatch")
        evidence = record.get("evidence", {})
        case_id = str(evidence.get("case_id"))
        if case_id in seen or case_id not in expected:
            raise ContractError("edge audit: duplicate or unknown case identity")
        seen.add(case_id)
        if record.get("defer_reason") is not None or record.get("disposition") == "DEFER":
            raise ContractError("edge audit: replay contains a deferred record")

        row = expected[case_id]
        detector = str(row["catalog_identity"]["detector"])
        score = float(record["scores"]["native"])
        if not math.isfinite(score):
            raise ContractError("edge audit: non-finite replay score")
        source = origins.get(case_id, "existing_raw_mirror")
        delta = score - float(row["expected"]["published_native_score"])
        score_deltas[source].append(delta)
        source_counts[(source,)] += 1
        if abs(delta) > SCORE_ATOL:
            source_score_mismatches[(source,)] += 1

        old_class = str(row["expected"]["offline_class"])
        new_class = _offline_class(score, thresholds[detector])
        old_route = str(row["expected"]["light_disposition"])
        new_route = _route(score, float(thresholds[detector]["p99"]))
        published_classes[(detector, old_class)] += 1
        corrected_classes[(detector, new_class)] += 1
        published_routes[(detector, old_route)] += 1
        corrected_routes[(detector, new_route)] += 1
        class_transitions[(detector, old_class, new_class)] += 1
        route_transitions[(detector, old_route, new_route)] += 1
        if case_id in edge:
            family_counts[(str(row["taxonomy"]["global_family_id"]),)] += 1

    if seen != set(expected):
        raise ContractError("edge audit: replay did not cover every frozen case")

    boundary_offsets: Counter[tuple[str, ...]] = Counter()
    for row in missing:
        components = row["local_stitch"]["components"]
        if not components:
            raise ContractError("edge audit: edge row has no historical source component")
        padded_start = float(row["required_padded_interval_gps"][0])
        historical_file_end = float(components[0]["file_interval_gps"][1])
        boundary_offsets[(f"{historical_file_end - padded_start:.1f}",)] += 1

    ordinary = np.abs(np.asarray(score_deltas["existing_raw_mirror"], dtype=np.float64))
    edge_deltas = np.abs(np.asarray(
        score_deltas["verified_local_raw_stitch"] + score_deltas["gwosc_open_data"],
        dtype=np.float64,
    ))
    if (
        ordinary.size != 10_260
        or edge_deltas.size != 169
        or float(ordinary.max(initial=0.0)) > SCORE_ATOL
        or int(np.sum(edge_deltas > SCORE_ATOL)) != 169
        or boundary_offsets != {("36.0",): 169}
    ):
        raise ContractError("edge audit: observed failure is not the frozen 10,260+169 partition")

    changed_classes = sum(
        count for (detector, old, new), count in class_transitions.items() if old != new
    )
    changed_routes = sum(
        count for (detector, old, new), count in route_transitions.items() if old != new
    )
    body = {
        "schema_version": 1,
        "status": "CONFIRMED_HISTORICAL_EDGE_PADDING_DEFECT",
        "not_a_pass": True,
        "run_key": manifest["run_key"],
        "execution_digest": execution["execution_digest"],
        "contract_digest": contract["contract_digest"],
        "manifest_digest": header["manifest_digest"],
        "score_absolute_tolerance": SCORE_ATOL,
        "completed_records": len(records),
        "source_counts": _counter_dict(source_counts),
        "source_score_mismatch_counts": _counter_dict(source_score_mismatches),
        "max_abs_score_delta_by_source": {
            source: float(np.max(np.abs(np.asarray(values, dtype=np.float64)), initial=0.0))
            for source, values in score_deltas.items()
        },
        "edge_geometry": {
            "expected_complete_context_s": 40.0,
            "analysis_window_s": 32.0,
            "required_left_padding_s": 4.0,
            "required_right_padding_s": 4.0,
            "historical_edge_context_s": 36.0,
            "historical_effective_right_padding_s": 0.0,
            "historical_file_boundary_offset_from_padded_start": _counter_dict(boundary_offsets),
        },
        "published_class_counts": _counter_dict(published_classes),
        "candidate_conditioned_corrected_class_counts": _counter_dict(corrected_classes),
        "class_transitions": {
            f"{detector}/{old}->{new}": int(count)
            for (detector, old, new), count in sorted(class_transitions.items())
            if old != new
        },
        "changed_class_count": int(changed_classes),
        "published_route_counts": _counter_dict(published_routes),
        "candidate_conditioned_corrected_route_counts": _counter_dict(corrected_routes),
        "route_transitions": {
            f"{detector}/{old}->{new}": int(count)
            for (detector, old, new), count in sorted(route_transitions.items())
            if old != new
        },
        "changed_route_count": int(changed_routes),
        "edge_family_counts": _counter_dict(family_counts),
        "external_run_artifacts": {
            name: {
                "logical_path": name,
                "sha256": sha256_path(run_dir / name),
            }
            for name in ("run_manifest.json", "records.jsonl", "summary.json")
        },
        "scientific_boundary": {
            "ordinary_window_score_parity_established": True,
            "historical_edge_window_score_parity_established": False,
            "candidate_conditioned_reclassification_only": True,
            "establishes_corrected_discovery_catalogue": False,
            "requires_complete_o4a_rescan": True,
            "historical_artifacts_must_remain_immutable": True,
        },
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def reproduce_clipped_example(
    audit: Mapping[str, Any], *, root: Path = ROOT,
    raw_root: Path = DEFAULT_RAW_ROOT, device: str = "cuda",
) -> dict[str, Any]:
    """Reproduce one v1 score using the historical zero-right-pad context."""
    from gwpy.timeseries import TimeSeries

    from src.core.patch_producer import _worker_preprocess
    from src.core.patch_scorer import PatchScorer

    _, _, entries, missing = _load_frozen_population(root)
    row = missing[0]
    entry = next(item for item in entries if item["case_id"] == row["case_id"])
    component = row["local_stitch"]["components"][0]
    relative = Path(str(component["relative_path"]))
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError("edge audit: invalid clipped-example raw path")
    raw_path = (raw_root / relative).resolve()
    if raw_root.resolve() not in raw_path.parents or not raw_path.is_file():
        raise ContractError("edge audit: clipped-example raw source unavailable")
    if sha256_path(raw_path) != component["file_sha256"]:
        raise ContractError("edge audit: clipped-example raw source hash mismatch")

    series = TimeSeries.read(raw_path)
    start = float(entry["window"]["gps_start"])
    end = start + float(entry["window"]["duration_s"])
    source_end = float(series.t0.value + series.duration.value)
    context = series.crop(max(float(series.t0.value), start - 4.0), min(source_end, end + 4.0))
    _, image = _worker_preprocess(
        context.value,
        float(context.t0.value),
        float(context.dt.value),
        str(context.name),
        start,
        end,
        require_complete_padding=False,
    )
    if image is None:
        raise ContractError("edge audit: clipped historical preprocessing failed")

    representation = RepresentationContract.from_reference_manifest(root / "config/reference_artifacts.json")
    primary = PatchScorer(
        root / "data/reference/patch_compressed_index_o3b.npz",
        device=device,
        k=representation.top_k,
    )
    native = PatchScorer(
        root / "data/reference/patch_compressed_index_o4a_q4-64_ex.npz",
        device=device,
        k=representation.top_k,
    )
    primary_score = float(primary.score_spectrogram([image], threshold=1.0)[0]["novelty_score"])
    native_score = float(native.score_spectrogram([image], threshold=1.0)[0]["novelty_score"])
    expected_native = float(entry["expected"]["published_native_score"])
    native_delta = abs(native_score - expected_native)
    if native_delta > SCORE_ATOL:
        raise ContractError("edge audit: clipped context did not reproduce the historical native score")

    body = dict(audit)
    body.pop("artifact_digest", None)
    body["clipped_context_reproduction"] = {
        "case_id": entry["case_id"],
        "detector": entry["catalog_identity"]["detector"],
        "catalog_gps_start": entry["catalog_identity"]["gps_start"],
        "analysis_gps_start": start,
        "source_relative_path": relative.as_posix(),
        "source_sha256": component["file_sha256"],
        "context_interval_gps": [float(context.t0.value), float(context.t0.value + context.duration.value)],
        "effective_left_padding_s": start - float(context.t0.value),
        "effective_right_padding_s": float(context.t0.value + context.duration.value) - end,
        "published_native_score": expected_native,
        "reproduced_clipped_native_score": native_score,
        "absolute_native_score_delta": native_delta,
        "reproduced_clipped_primary_score": primary_score,
        "image_sha256": hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest(),
        "device": device,
    }
    body["scientific_boundary"] = {
        **body["scientific_boundary"],
        "single_case_clipped_context_causality_established": True,
        "all_edge_windows_historical_score_parity_established": False,
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def write_audit(value: Mapping[str, Any], path: Path = DEFAULT_OUTPUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
