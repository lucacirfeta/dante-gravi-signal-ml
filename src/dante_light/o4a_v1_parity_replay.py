"""Canonical, resumable scoring and verification for the frozen O4a parity audit."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

import numpy as np

from src.core.patch_scorer import PatchScorer
from src.dante_light.contracts import (
    ContractError, LightDisposition, LightRecord, RepresentationContract,
    WindowIdentity, canonical_json_sha256,
)
from src.dante_light.executor import WindowTask
from src.dante_light.o4a_v1_parity import ROOT, _offline_class, validate_parity_freeze
from src.dante_light.o4a_v1_parity_cache import COMPACT_ARTIFACT, validate_cache
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path
from src.dante_light.preprocessing import PreparedWindow, prepare_canonical_window
from src.dante_light.review_queue import ReviewQueue
from src.dante_light.runner import DanteLightRunner, load_epochs
from src.dante_light.runner_v8_1 import runtime_provenance


EXECUTION_PATH = ROOT / "config/dante_light_o4a_v1_parity_execution.json"
DEFAULT_CACHE_ROOT = Path("E:/dante_cache/dante_light/o4a_v1_comparison")
DEFAULT_RAW_ROOT = Path("E:/o4a")
PRIMARY_INDEX = ROOT / "data/reference/patch_compressed_index_o3b.npz"
NATIVE_INDEX = ROOT / "data/reference/patch_compressed_index_o4a_q4-64_ex.npz"
COMPACT_RESULT = ROOT / "artifacts/dante_light/o4a_v1_parity/score_parity_summary.json"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError(f"expected JSON object: {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _reference_matches(root: Path, reference: Mapping[str, Any]) -> bool:
    path = root / str(reference["path"])
    if not path.is_file():
        return False
    candidates = {sha256_path(path)}
    try:
        candidates.add(hashlib.sha256(subprocess.check_output(
            ["git", "show", f"HEAD:{reference['path']}"], cwd=root,
            stderr=subprocess.DEVNULL,
        )).hexdigest())
    except (OSError, subprocess.SubprocessError):
        pass
    return str(reference["sha256"]) in candidates


def build_execution_contract(root: Path = ROOT) -> dict[str, Any]:
    references = {
        "parity_contract": repository_reference(root, root / "config/dante_light_o4a_v1_parity_contract.json"),
        "parity_manifest": repository_reference(root, root / "config/dante_light_o4a_v1_parity_manifest.json"),
        "parity_entries": repository_reference(root, root / "config/dante_light_o4a_v1_parity_manifest.jsonl"),
        "raw_cache_summary": repository_reference(root, root / COMPACT_ARTIFACT.relative_to(ROOT)),
        "historical_epochs": repository_reference(root, root / "config/dante_light_epochs_v1.json"),
        "reference_artifacts": repository_reference(root, root / "config/reference_artifacts.json"),
        "replay_code": repository_reference(root, root / "src/dante_light/o4a_v1_parity_replay.py"),
        "preprocessing": repository_reference(root, root / "src/dante_light/preprocessing.py"),
        "patch_scorer": repository_reference(root, root / "src/core/patch_scorer.py"),
    }
    parity = _read_json(root / references["parity_contract"]["path"])
    header = _read_json(root / references["parity_manifest"]["path"])
    body = {
        "schema_version": 1,
        "status": "FROZEN_BEFORE_CANONICAL_RESCORING",
        "execution_id": "dante-light-o4a-v1-canonical-parity",
        "parity_contract_digest": parity["contract_digest"],
        "parity_manifest_digest": header["manifest_digest"],
        "source_references": references,
        "scientific_engine": "canonical_two_encoder",
        "preprocessing": "canonical_whiten_context_then_crop_qtransform_cividis",
        "scorer_construction": {
            "top_k_source": "RepresentationContract.top_k",
            "primary_index_source": "RepresentationContract.primary_index_sha256",
            "native_index_source": "RepresentationContract.native_index_sha256",
            "shared_encoder": False,
        },
        "executor": {
            "workers": 2,
            "batch_size": 8,
            "max_preprocess_in_flight": 16,
            "max_pending_writes": 2,
            "requested_device": "cuda",
        },
        "data": {
            "raw_root_alias": "DANTE_O4A_RAW_ROOT",
            "parity_cache_alias": "DANTE_O4A_V1_PARITY_CACHE_ROOT",
            "local_only": True,
            "cat1": "frozen_manifest_attestation_for_retrospective_replay",
        },
        "failure_policy": "DEFER_FAIL_CLOSED_NO_THRESHOLD_OR_TOLERANCE_CHANGE",
    }
    return {**body, "execution_digest": canonical_json_sha256(body)}


def validate_execution_contract(value: Mapping[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    payload = dict(value); body = dict(payload)
    digest = body.pop("execution_digest", None)
    if digest != canonical_json_sha256(body):
        raise ContractError("parity execution contract digest mismatch")
    if payload.get("status") != "FROZEN_BEFORE_CANONICAL_RESCORING":
        raise ContractError("parity execution contract is not frozen")
    if payload.get("scientific_engine") != "canonical_two_encoder":
        raise ContractError("parity replay must use the canonical two-encoder engine")
    if payload["scorer_construction"].get("shared_encoder") is not False:
        raise ContractError("parity replay silently enabled shared encoding")
    if payload["data"] != {
        "raw_root_alias": "DANTE_O4A_RAW_ROOT",
        "parity_cache_alias": "DANTE_O4A_V1_PARITY_CACHE_ROOT",
        "local_only": True,
        "cat1": "frozen_manifest_attestation_for_retrospective_replay",
    }:
        raise ContractError("parity replay data boundary changed")
    for name, reference in payload["source_references"].items():
        if not _reference_matches(root, reference):
            raise ContractError(f"parity execution source mismatch: {name}")
    parity = _read_json(root / payload["source_references"]["parity_contract"]["path"])
    header = _read_json(root / payload["source_references"]["parity_manifest"]["path"])
    if payload["parity_contract_digest"] != parity["contract_digest"] or payload["parity_manifest_digest"] != header["manifest_digest"]:
        raise ContractError("parity execution points to another frozen population")
    return payload


def write_execution_contract(path: Path = EXECUTION_PATH, *, root: Path = ROOT) -> dict[str, Any]:
    value = build_execution_contract(root)
    encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.exists() and path.read_bytes() != encoded:
        raise ContractError("refusing to overwrite divergent parity execution contract")
    path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(encoded)
    return value


class O4aV1ParityRunner(DanteLightRunner):
    """Canonical runner that persists both index evidence hashes."""

    def _score_batch(self, batch: list[tuple[WindowTask, PreparedWindow]]) -> list[LightRecord]:
        images = [prepared.image for _, prepared in batch]
        primary_results = self.primary.score_spectrogram(images, threshold=1.0)
        native_results = self.native.score_spectrogram(images, threshold=1.0)
        records: list[LightRecord] = []
        for task, prepared, primary, native in zip(
            (item[0] for item in batch), (item[1] for item in batch),
            primary_results, native_results, strict=True,
        ):
            epoch = self._epoch(task.window)
            native_score = float(native["novelty_score"])
            disposition = LightDisposition.ESCALATE if native_score > epoch.threshold else LightDisposition.NOT_ESCALATED
            record = LightRecord(
                window=task.window,
                representation_sha256=self.representation.contract_sha256,
                disposition=disposition,
                epoch_id=epoch.epoch_id,
                scores=(("native", native_score), ("primary", float(primary["novelty_score"]))),
            )
            primary_top_k = np.asarray(primary["top_k_indices"], dtype=np.int32)
            native_top_k = np.asarray(native["top_k_indices"], dtype=np.int32)
            primary_mil = np.asarray(primary["mil_vector"], dtype=np.float32)
            native_mil = np.asarray(native["mil_vector"], dtype=np.float32)
            self.evidence[task.window.window_id] = {
                "case_id": task.payload["case_id"],
                "expected": task.payload["expected"],
                "taxonomy": task.payload["taxonomy"],
                "strain_sha256": prepared.strain_sha256,
                "image_sha256": prepared.image_sha256,
                "primary_top_k_sha256": hashlib.sha256(primary_top_k.tobytes()).hexdigest(),
                "native_top_k_sha256": hashlib.sha256(native_top_k.tobytes()).hexdigest(),
                "primary_mil_vector_sha256": hashlib.sha256(primary_mil.tobytes()).hexdigest(),
                "native_mil_vector_sha256": hashlib.sha256(native_mil.tobytes()).hexdigest(),
                "decision_score": "native",
                "decision_threshold": epoch.threshold,
                "timings": prepared.timings,
            }
            records.append(record)
        return records


def _load_population(root: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    parity = _read_json(root / "config/dante_light_o4a_v1_parity_contract.json")
    header = _read_json(root / "config/dante_light_o4a_v1_parity_manifest.json")
    entries = _read_jsonl(root / header["entries_path"])
    missing = _read_jsonl(root / header["missing_path"])
    validate_parity_freeze(parity, header, entries, missing, root=root)
    return parity, header, entries


def run_canonical_replay(
    *, root: Path = ROOT, raw_root: Path = DEFAULT_RAW_ROOT,
    cache_root: Path = DEFAULT_CACHE_ROOT, output_dir: Path | None = None,
    device: str = "cuda",
) -> tuple[Path, dict[str, Any]]:
    execution = validate_execution_contract(_read_json(root / EXECUTION_PATH.relative_to(ROOT)), root=root)
    validate_cache(root=root, cache_root=cache_root)
    parity, header, entries = _load_population(root)
    config = execution["executor"]
    if device != config["requested_device"]:
        raise ContractError("parity replay device differs from frozen execution contract")
    os.environ["DANTE_DATA_DIRS"] = os.pathsep.join([str((cache_root / "raw").resolve()), str(raw_root.resolve())])
    from src.core import data_loader
    data_loader._DATA_DIRECTORIES = [cache_root / "raw", raw_root]
    data_loader._LOCAL_BLOCK_INDEX.clear()

    representation = RepresentationContract.from_reference_manifest(root / "config/reference_artifacts.json")
    epoch_payload, epochs = load_epochs(root / "config/dante_light_epochs_v1.json", representation=representation, root=root)
    primary = PatchScorer(PRIMARY_INDEX, device=device, k=representation.top_k)
    native = PatchScorer(NATIVE_INDEX, device=device, k=representation.top_k)
    if primary.reference_sha256 != representation.primary_index_sha256 or native.reference_sha256 != representation.native_index_sha256:
        raise ContractError("parity scorer index violates the representation contract")
    tasks = [
        WindowTask(
            WindowIdentity.from_dict(row["window"]),
            {"case_id": row["case_id"], "expected": row["expected"], "taxonomy": row["taxonomy"]},
        )
        for row in entries
    ]
    run_key = canonical_json_sha256({
        "execution_digest": execution["execution_digest"],
        "device": device,
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
    })
    output = output_dir or cache_root / f"score_{run_key}"
    run_manifest = {
        "schema_version": 1,
        "status": "CANONICAL_RETROSPECTIVE_PARITY",
        "run_key": run_key,
        "execution_digest": execution["execution_digest"],
        "parity_contract_digest": parity["contract_digest"],
        "parity_manifest_digest": header["manifest_digest"],
        "scientific_engine": execution["scientific_engine"],
        "representation": representation.to_dict(),
        "epochs": epoch_payload,
        "entries": len(tasks),
        "data": execution["data"],
        "executor": config,
        "runtime_provenance": runtime_provenance(),
    }
    queue = ReviewQueue(output, run_manifest)
    runner = O4aV1ParityRunner(
        representation=representation, epochs=epochs, primary=primary, native=native,
        review_queue=queue, cat1_active=lambda _window: True,
        prepare=lambda task: prepare_canonical_window(task.window, local_only=True),
        prospective=False, engine="canonical", workers=int(config["workers"]),
        batch_size=int(config["batch_size"]),
        max_preprocess_in_flight=int(config["max_preprocess_in_flight"]),
        max_pending_writes=int(config["max_pending_writes"]),
    )
    return output, runner.run(tasks)


def verify_score_run(
    *, root: Path = ROOT, run_dir: Path,
) -> dict[str, Any]:
    execution = validate_execution_contract(_read_json(root / EXECUTION_PATH.relative_to(ROOT)), root=root)
    parity, header, entries = _load_population(root)
    by_window = {row["window"]["window_id"]: row for row in entries}
    run_manifest = _read_json(run_dir / "run_manifest.json")
    manifest_body = dict(run_manifest); manifest_digest = manifest_body.pop("manifest_sha256", None)
    if manifest_digest != canonical_json_sha256(manifest_body):
        raise ContractError("parity score run manifest digest mismatch")
    if run_manifest["execution_digest"] != execution["execution_digest"] or run_manifest["entries"] != len(entries):
        raise ContractError("parity score run belongs to another execution")
    records = _read_jsonl(run_dir / "records.jsonl")
    if len(records) != len(entries):
        raise ContractError(f"parity score run incomplete: {len(records)}/{len(entries)}")
    thresholds = _read_json(root / "data/production/aggregated/dsd_thresholds_o4a_idxq4-64_queryq4-64.json")
    tolerance = float(parity["comparison"]["score_absolute_tolerance"])
    max_delta: dict[str, float] = {"H1": 0.0, "L1": 0.0}
    class_counts: Counter[str] = Counter(); disposition_counts: Counter[str] = Counter()
    mismatch_counts: Counter[str] = Counter(); seen: set[str] = set()
    for record in records:
        record_body = dict(record); record_id = record_body.pop("record_id", None)
        if record_id != f"dlr1-{canonical_json_sha256(record_body)[:24]}":
            raise ContractError("parity score record digest mismatch")
        window_id = record["window"]["window_id"]
        if window_id in seen or window_id not in by_window:
            raise ContractError("parity score record identity mismatch")
        seen.add(window_id); expected = by_window[window_id]
        if record["defer_reason"] is not None or record["disposition"] == "DEFER":
            mismatch_counts["defer"] += 1; continue
        native = float(record["scores"]["native"]); primary = float(record["scores"]["primary"])
        if not math.isfinite(native) or not math.isfinite(primary):
            mismatch_counts["nonfinite_score"] += 1; continue
        detector = record["window"]["detector"]
        delta = abs(native - float(expected["expected"]["published_native_score"]))
        max_delta[detector] = max(max_delta[detector], delta)
        if delta > tolerance:
            mismatch_counts["score_tolerance"] += 1
        computed_class = _offline_class(native, thresholds["thresholds"][detector])
        class_counts[computed_class] += 1
        if computed_class != expected["expected"]["offline_class"]:
            mismatch_counts["offline_class"] += 1
        expected_route = "ESCALATE" if native >= float(thresholds["thresholds"][detector]["p99"]) else "ROUTINE"
        actual_route = "ESCALATE" if record["disposition"] == "ESCALATE" else "ROUTINE"
        disposition_counts[actual_route] += 1
        if actual_route != expected_route or expected_route != expected["expected"]["light_disposition"]:
            mismatch_counts["light_routing"] += 1
        evidence = record.get("evidence", {})
        if evidence.get("case_id") != expected["case_id"]:
            mismatch_counts["case_evidence"] += 1
        for field in (
            "strain_sha256", "image_sha256", "primary_top_k_sha256",
            "native_top_k_sha256", "primary_mil_vector_sha256", "native_mil_vector_sha256",
        ):
            if not isinstance(evidence.get(field), str) or len(evidence[field]) != 64:
                mismatch_counts[f"missing_{field}"] += 1
    robust_escalated = sum(
        1 for record in records
        if by_window[record["window"]["window_id"]]["expected"]["offline_class"] == "ROBUST"
        and record["disposition"] == "ESCALATE"
    )
    background_escalated = sum(
        1 for record in records
        if by_window[record["window"]["window_id"]]["expected"]["offline_class"] == "BACKGROUND"
        and record["disposition"] == "ESCALATE"
    )
    if robust_escalated != 6365:
        mismatch_counts["robust_not_escalated"] += 6365 - robust_escalated
    if background_escalated:
        mismatch_counts["background_escalated"] += background_escalated
    status = "PASS" if not mismatch_counts else "FAIL_CLOSED"
    body = {
        "schema_version": 1,
        "status": status,
        "run_key": run_manifest["run_key"],
        "execution_digest": execution["execution_digest"],
        "parity_contract_digest": parity["contract_digest"],
        "parity_manifest_digest": header["manifest_digest"],
        "records": len(records),
        "score_absolute_tolerance": tolerance,
        "max_abs_native_score_delta_by_detector": max_delta,
        "recomputed_offline_class_counts": dict(sorted(class_counts.items())),
        "recomputed_light_disposition_counts": dict(sorted(disposition_counts.items())),
        "robust_escalated": robust_escalated,
        "background_escalated": background_escalated,
        "mismatch_counts": dict(sorted(mismatch_counts.items())),
        "external_artifacts": {
            name: {"logical_path": name, "sha256": sha256_path(run_dir / name)}
            for name in ("run_manifest.json", "records.jsonl", "summary.json")
        },
        "scientific_boundary": parity["scientific_boundary"],
    }
    result = {**body, "artifact_digest": canonical_json_sha256(body)}
    if status != "PASS":
        raise ContractError(f"O4a v1 score parity failed closed: {dict(mismatch_counts)}")
    return result


def write_compact_result(value: Mapping[str, Any], path: Path = COMPACT_RESULT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
