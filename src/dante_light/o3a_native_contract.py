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
from typing import Any, Mapping

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
            "DQ snapshot and stage-specific population/statistical contracts absent"
        ),
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


__all__ = [
    "AUTHORIZATION_REL",
    "CONTRACT_REL",
    "RUNTIME_REL",
    "build_runtime_contract",
    "build_scope_contract",
    "load_authorization",
    "load_runtime_contract",
    "load_scope_contract",
    "validate_runtime_contract",
    "validate_scope_contract",
    "write_runtime_and_scope_contracts",
]
