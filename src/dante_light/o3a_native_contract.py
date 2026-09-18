"""Frozen scope, runtime, and preparation contract for O3a-native DANTE.

This layer records the four author-approved scientific choices without
inventing stage parameters that have not yet been frozen.  It deliberately
keeps data execution fail-closed until the DQ snapshot and stage-specific
population/statistical contracts exist.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from src.core.artifact_manager import model_contract_summary
from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_transfer_readiness import (
    DETECTORS,
    O3A_BOUNDS,
    RECOMMENDATIONS,
)
from src.dante_light.o4a_corrected_runtime import capture_runtime_environment


ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION_REL = "config/dante_o3a_native_v1_authorization.json"
RUNTIME_REL = "config/dante_o3a_native_v1_runtime.json"
CONTRACT_REL = "config/dante_o3a_native_v1_contract.json"
DQ_SNAPSHOT_REL = "config/dante_o3a_cbc_cat1_segments_v1.json"
STAGE_GATE_REL = "config/dante_o3a_native_v1_stage_decision_gate.json"
REFERENCE_REL = "config/reference_artifacts.json"
SCHEMA_VERSION = 1
RUNTIME_ID = "dante-o3a-native-wsl-cuda-runtime-v1"

_UNRESOLVED_STAGE_PARAMETERS = (
    "initial_calibration_population_and_size",
    "cross_population_guard_seconds",
    "native_cohort_population_and_size",
    "native_index_clustering_parameters",
    "native_calibration_population_and_size",
    "block_bootstrap_block_length_and_replicates",
    "detector_threshold_quantile_and_confidence_interval",
    "coincidence_null_and_multiple_testing_policy",
)

_SOURCE_FILES = (
    "config/reference_artifacts.json",
    "src/core/artifact_manager.py",
    "src/dante_light/o3a_native_contract.py",
    "src/dante_light/o4a_corrected_runtime.py",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_self_digest(
    value: Mapping[str, Any], field: str, label: str
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop(field, None)
    if digest != canonical_json_sha256(payload):
        raise ContractError(f"O3a {label} self-digest mismatch")
    return dict(value)


def load_authorization(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / AUTHORIZATION_REL
    value = json.loads(path.read_text(encoding="utf-8"))
    _validate_self_digest(value, "authorization_digest", "authorization")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "AUTHOR_APPROVED_O3A_NATIVE_SCOPE"
        or value.get("run") != "O3A"
        or value.get("official_run_bounds_gps") != O3A_BOUNDS
        or value.get("detectors") != DETECTORS
        or value.get("author_decisions") != RECOMMENDATIONS
        or value.get("outcome_data_accessed") is not False
    ):
        raise ContractError("O3a author authorization is not the approved scope")
    source = value.get("source_decision_gate", {})
    source_path = root / str(source.get("path", ""))
    if not source_path.is_file() or _sha256_file(source_path) != source.get("sha256"):
        raise ContractError("O3a authorization does not bind the historical gate")
    storage = value.get("storage", {})
    if storage.get("primary_scan_raw_cache") != 0:
        raise ContractError("O3a primary scan raw caching must remain disabled")
    return dict(value)


def _reference_contract(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / REFERENCE_REL).read_text(encoding="utf-8"))
    source = manifest["reference_indices"]["o3b_production_k275"]
    forbidden = manifest["reference_indices"]["o4a_native_q4_64_k1216"]
    return {
        "initial_source_representation": {
            "artifact_id": "o3b_production_k275",
            "path": source["path"],
            "sha256": source["sha256"],
            "n_centroids": source["n_centroids"],
            "qrange": source["qrange"],
            "role": "PRIMARY_SCAN_SEED_ONLY",
            "eligible_for_native_o3a_outputs": False,
        },
        "forbidden_o4a_reference": {
            "artifact_id": "o4a_native_q4_64_k1216",
            "sha256": forbidden["sha256"],
            "scientific_import_allowed": False,
        },
    }


def _capture_o3a_runtime(device: str) -> dict[str, Any]:
    environment = dict(capture_runtime_environment(device))
    environment.pop("environment_digest", None)
    packages = dict(environment["packages"])
    for name in ("requests", "scikit-learn"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ContractError(f"canonical O3a dependency is absent: {name}") from exc
    environment["packages"] = dict(sorted(packages.items()))
    return {
        **environment,
        "environment_digest": canonical_json_sha256(environment),
    }


def _source_contract(root: Path) -> dict[str, str]:
    return {path: _sha256_file(root / path) for path in _SOURCE_FILES}


def _normalized_segments(values: Any, detector: str) -> list[list[int]]:
    segments: list[list[int]] = []
    previous_right: int | None = None
    for item in values:
        if len(item) != 2:
            raise ContractError(f"O3a {detector} DQ segment is not a pair")
        left_raw, right_raw = float(item[0]), float(item[1])
        if not left_raw.is_integer() or not right_raw.is_integer():
            raise ContractError(f"O3a {detector} DQ endpoint is not integral GPS")
        left, right = int(left_raw), int(right_raw)
        if left < O3A_BOUNDS[0] or right > O3A_BOUNDS[1] or right <= left:
            raise ContractError(f"O3a {detector} DQ segment is outside run bounds")
        if previous_right is not None and left < previous_right:
            raise ContractError(f"O3a {detector} DQ segments overlap or are unsorted")
        segments.append([left, right])
        previous_right = right
    if not segments:
        raise ContractError(f"O3a {detector} CBC_CAT1 response is empty")
    return segments


def build_dq_snapshot(
    *,
    root: Path = ROOT,
    segment_fetcher: Callable[[str, int, int], Any] | None = None,
) -> dict[str, Any]:
    """Fetch public CBC_CAT1 metadata only and return a self-digested snapshot."""
    authorization = load_authorization(root=root)
    if authorization["author_decisions"]["dq_semantics"] != "CBC_CAT1":
        raise ContractError("O3a authorization does not select CBC_CAT1")
    if segment_fetcher is None:
        from gwosc.timeline import get_segments

        segment_fetcher = get_segments
    segments: dict[str, list[list[int]]] = {}
    summaries: dict[str, dict[str, int]] = {}
    for detector in DETECTORS:
        rows = _normalized_segments(
            segment_fetcher(
                f"{detector}_CBC_CAT1", O3A_BOUNDS[0], O3A_BOUNDS[1]
            ),
            detector,
        )
        segments[detector] = rows
        summaries[detector] = {
            "segment_count": len(rows),
            "livetime_s": sum(right - left for left, right in rows),
        }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_PUBLIC_DQ_ONLY",
        "run": "O3A",
        "official_run_bounds_gps": O3A_BOUNDS,
        "detectors": DETECTORS,
        "source": {
            "provider": "GWOSC",
            "api": "gwosc.timeline.get_segments",
            "release_url": "https://gwosc.org/O3/",
            "flags": {detector: f"{detector}_CBC_CAT1" for detector in DETECTORS},
            "outcome_data_accessed": False,
            "strain_data_accessed": False,
        },
        "query_bounds_gps": O3A_BOUNDS,
        "segments": segments,
        "summaries": summaries,
    }
    return {**body, "snapshot_digest": canonical_json_sha256(body)}


def validate_dq_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    _validate_self_digest(value, "snapshot_digest", "DQ snapshot")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_PUBLIC_DQ_ONLY"
        or value.get("run") != "O3A"
        or value.get("official_run_bounds_gps") != O3A_BOUNDS
        or value.get("query_bounds_gps") != O3A_BOUNDS
        or value.get("detectors") != DETECTORS
    ):
        raise ContractError("O3a DQ snapshot scope mismatch")
    source = value.get("source", {})
    if (
        source.get("provider") != "GWOSC"
        or source.get("api") != "gwosc.timeline.get_segments"
        or source.get("flags")
        != {detector: f"{detector}_CBC_CAT1" for detector in DETECTORS}
        or source.get("outcome_data_accessed") is not False
        or source.get("strain_data_accessed") is not False
    ):
        raise ContractError("O3a DQ snapshot source mismatch")
    normalized: dict[str, list[list[int]]] = {}
    summaries: dict[str, dict[str, int]] = {}
    for detector in DETECTORS:
        rows = _normalized_segments(value.get("segments", {}).get(detector, []), detector)
        normalized[detector] = rows
        summaries[detector] = {
            "segment_count": len(rows),
            "livetime_s": sum(right - left for left, right in rows),
        }
    if value.get("segments") != normalized or value.get("summaries") != summaries:
        raise ContractError("O3a DQ snapshot summaries mismatch")
    return dict(value)


def load_dq_snapshot(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / DQ_SNAPSHOT_REL
    if not path.is_file():
        raise ContractError("O3a CBC_CAT1 snapshot is absent")
    return validate_dq_snapshot(json.loads(path.read_text(encoding="utf-8")))


def write_dq_snapshot(
    *,
    root: Path = ROOT,
    segment_fetcher: Callable[[str, int, int], Any] | None = None,
) -> dict[str, Any]:
    value = build_dq_snapshot(root=root, segment_fetcher=segment_fetcher)
    _write_json(root / DQ_SNAPSHOT_REL, value)
    return value


def build_runtime_contract(
    *, root: Path = ROOT, device: str = "cuda"
) -> dict[str, Any]:
    authorization = load_authorization(root=root)
    environment = _capture_o3a_runtime(device)
    if not environment["operating_system"]["wsl"]:
        raise ContractError("O3a canonical runtime must be frozen inside WSL")
    encoder = {
        "runtime_environment_digest": environment["environment_digest"],
        "model": model_contract_summary(manifest_path=root / REFERENCE_REL),
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_CANONICAL_WSL_CUDA_RUNTIME",
        "runtime_id": RUNTIME_ID,
        "authorization_digest": authorization["authorization_digest"],
        "runtime_environment": environment,
        "encoder_fingerprint": {
            **encoder,
            "fingerprint_digest": canonical_json_sha256(encoder),
        },
        "scientific_boundary": {
            "numerical_toolchain_only": True,
            "windows_scoring_allowed": False,
            "cross_environment_shard_reuse_allowed": False,
            "o4a_scientific_artifact_reuse_allowed": False,
        },
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_runtime_contract(
    value: Mapping[str, Any],
    *,
    root: Path = ROOT,
    require_current: bool = False,
    device: str = "cuda",
) -> dict[str, Any]:
    _validate_self_digest(value, "contract_digest", "runtime contract")
    authorization = load_authorization(root=root)
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_O3A_CANONICAL_WSL_CUDA_RUNTIME"
        or value.get("runtime_id") != RUNTIME_ID
        or value.get("authorization_digest") != authorization["authorization_digest"]
        or not value["runtime_environment"]["operating_system"]["wsl"]
        or value["runtime_environment"]["cuda_device"]["request"] != "cuda"
    ):
        raise ContractError("O3a runtime contract is not canonical WSL/CUDA")
    environment = dict(value["runtime_environment"])
    environment_digest = environment.pop("environment_digest", None)
    if environment_digest != canonical_json_sha256(environment):
        raise ContractError("O3a runtime environment digest mismatch")
    encoder = dict(value["encoder_fingerprint"])
    fingerprint = encoder.pop("fingerprint_digest", None)
    if (
        fingerprint != canonical_json_sha256(encoder)
        or encoder.get("runtime_environment_digest") != environment_digest
        or encoder.get("model")
        != model_contract_summary(manifest_path=root / REFERENCE_REL)
    ):
        raise ContractError("O3a encoder fingerprint mismatch")
    if require_current and _capture_o3a_runtime(device) != value["runtime_environment"]:
        raise ContractError(
            "STOP_ENVIRONMENT_MISMATCH: O3a scoring requires the frozen WSL runtime"
        )
    return dict(value)


def load_runtime_contract(
    *, root: Path = ROOT, require_current: bool = False, device: str = "cuda"
) -> dict[str, Any]:
    path = root / RUNTIME_REL
    if not path.is_file():
        raise ContractError("O3a runtime contract is absent")
    return validate_runtime_contract(
        json.loads(path.read_text(encoding="utf-8")),
        root=root,
        require_current=require_current,
        device=device,
    )


def build_scope_contract(*, root: Path = ROOT) -> dict[str, Any]:
    authorization = load_authorization(root=root)
    runtime = load_runtime_contract(root=root)
    references = _reference_contract(root)
    dq_snapshot = load_dq_snapshot(root=root)
    dq_path = root / DQ_SNAPSHOT_REL
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_SCOPE_PREPARATION_ONLY",
        "run": "O3A",
        "official_run_bounds_gps": O3A_BOUNDS,
        "detectors": DETECTORS,
        "public_dq_semantics": "CBC_CAT1",
        "authorization_digest": authorization["authorization_digest"],
        "runtime_contract_digest": runtime["contract_digest"],
        "scope_execution_authorized": True,
        "pipeline_execution_allowed": False,
        "pipeline_execution_blocker": (
            "stage-specific population/statistical contracts absent"
        ),
        "dq_snapshot": {
            "path": DQ_SNAPSHOT_REL,
            "sha256": _sha256_file(dq_path),
            "snapshot_digest": dq_snapshot["snapshot_digest"],
            "summaries": dq_snapshot["summaries"],
        },
        "references": references,
        "implementation_sources": _source_contract(root),
        "run_dependent_artifacts": {
            "initial_calibration": "FRESH_O3A_ONLY",
            "primary_scan": "FRESH_O3A_ONLY",
            "native_cohort": "FRESH_O3A_ONLY",
            "native_index": "FRESH_O3A_ONLY",
            "native_calibration": "FRESH_O3A_ONLY",
            "thresholds": "FRESH_O3A_DETECTOR_SPECIFIC",
            "classes_and_downstream_products": "FRESH_O3A_ONLY",
        },
        "scientific_invariants": {
            "outcome_blind_population_selection": True,
            "population_disjointness_and_guard_required": True,
            "block_bootstrap_only": True,
            "detector_specific_thresholds": True,
            "intra_and_cross_detector_nulls_comparable": False,
            "whitening_before_qtransform_crop_with_context": True,
            "o4a_populations_thresholds_scores_classes_import_allowed": False,
            "multiscale_a2_role": "DIAGNOSTIC_ONLY_NO_CANDIDATE_PROMOTION",
            "multiscale_requires_independent_o3a_validation": True,
        },
        "storage": authorization["storage"],
        "unresolved_stage_parameters": list(_UNRESOLVED_STAGE_PARAMETERS),
    }
    return {**body, "contract_digest": canonical_json_sha256(body)}


def validate_scope_contract(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    _validate_self_digest(value, "contract_digest", "scope contract")
    authorization = load_authorization(root=root)
    runtime = load_runtime_contract(root=root)
    dq_snapshot = load_dq_snapshot(root=root)
    dq_path = root / DQ_SNAPSHOT_REL
    expected_dq = {
        "path": DQ_SNAPSHOT_REL,
        "sha256": _sha256_file(dq_path),
        "snapshot_digest": dq_snapshot["snapshot_digest"],
        "summaries": dq_snapshot["summaries"],
    }
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "FROZEN_O3A_SCOPE_PREPARATION_ONLY"
        or value.get("run") != "O3A"
        or value.get("official_run_bounds_gps") != O3A_BOUNDS
        or value.get("detectors") != DETECTORS
        or value.get("public_dq_semantics") != "CBC_CAT1"
        or value.get("authorization_digest") != authorization["authorization_digest"]
        or value.get("runtime_contract_digest") != runtime["contract_digest"]
        or value.get("scope_execution_authorized") is not True
        or value.get("pipeline_execution_allowed") is not False
        or value.get("dq_snapshot") != expected_dq
        or tuple(value.get("unresolved_stage_parameters", ()))
        != _UNRESOLVED_STAGE_PARAMETERS
        or value.get("references") != _reference_contract(root)
        or value.get("implementation_sources") != _source_contract(root)
    ):
        raise ContractError("O3a scope contract changed or was silently promoted")
    invariants = value.get("scientific_invariants", {})
    if (
        invariants.get("block_bootstrap_only") is not True
        or invariants.get("intra_and_cross_detector_nulls_comparable") is not False
        or invariants.get("o4a_populations_thresholds_scores_classes_import_allowed")
        is not False
        or invariants.get("multiscale_a2_role")
        != "DIAGNOSTIC_ONLY_NO_CANDIDATE_PROMOTION"
    ):
        raise ContractError("O3a scientific invariants were weakened")
    return dict(value)


def load_scope_contract(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / CONTRACT_REL
    if not path.is_file():
        raise ContractError("O3a scope contract is absent")
    return validate_scope_contract(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def load_stage_decision_gate(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / STAGE_GATE_REL
    if not path.is_file():
        raise ContractError("O3a stage decision gate is absent")
    value = json.loads(path.read_text(encoding="utf-8"))
    _validate_self_digest(value, "gate_digest", "stage decision gate")
    scope = load_scope_contract(root=root)
    dq = load_dq_snapshot(root=root)
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "AUTHOR_DECISION_REQUIRED"
        or value.get("run") != "O3A"
        or value.get("scope_contract_digest") != scope["contract_digest"]
        or value.get("dq_snapshot_digest") != dq["snapshot_digest"]
        or value.get("outcome_data_accessed") is not False
        or value.get("strain_data_accessed") is not False
        or value.get("execution_allowed") is not False
    ):
        raise ContractError("O3a stage decision gate scope mismatch")
    recommendations = value.get("recommendations", {})
    decisions = value.get("author_decisions", {})
    if not isinstance(recommendations, dict) or set(decisions) != set(recommendations):
        raise ContractError("O3a stage decision fields are incomplete")
    if any(decision is not None for decision in decisions.values()):
        raise ContractError("O3a stage decisions must remain unresolved in this gate")
    return dict(value)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def write_runtime_and_scope_contracts(
    *, root: Path = ROOT, device: str = "cuda"
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = build_runtime_contract(root=root, device=device)
    _write_json(root / RUNTIME_REL, runtime)
    scope = build_scope_contract(root=root)
    _write_json(root / CONTRACT_REL, scope)
    return runtime, scope


def write_scope_contract(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_scope_contract(root=root)
    _write_json(root / CONTRACT_REL, value)
    return value


__all__ = [
    "AUTHORIZATION_REL",
    "CONTRACT_REL",
    "DQ_SNAPSHOT_REL",
    "STAGE_GATE_REL",
    "RUNTIME_REL",
    "build_runtime_contract",
    "build_dq_snapshot",
    "build_scope_contract",
    "load_authorization",
    "load_dq_snapshot",
    "load_runtime_contract",
    "load_stage_decision_gate",
    "load_scope_contract",
    "validate_runtime_contract",
    "validate_dq_snapshot",
    "validate_scope_contract",
    "write_runtime_and_scope_contracts",
    "write_dq_snapshot",
    "write_scope_contract",
]
