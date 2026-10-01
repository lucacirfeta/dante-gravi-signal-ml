"""Explicit, hash-bound profile graphs; the frozen v1 contract stays separate.

Loading a graph describes a workflow. It does not register an adapter, approve
scientific parameters or assert data coverage. Executable adapter dispatch is
still fail-closed and separate from schema validation.
"""

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from .schema import (
    FileReference,
    GraphProfile,
    WorkflowSchemaError,
    WorkflowSpec,
    _exact_keys,
    _identifier,
    _POLICY_KEYS,
    _SHA256_RE,
    _string_list,
    _TOP_LEVEL_KEYS,
    _validate_file_reference,
    _validate_graph,
    _validate_stage,
    canonical_json_sha256,
)

_PROFILE_KEYS = {
    "schema_version",
    "profile_id",
    "observing_run",
    "detectors",
    "adapter",
    "stages",
    "contract_digest",
}


def strict_json_object(text: str, *, label: str) -> dict[str, Any]:
    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise WorkflowSchemaError(f"{label} duplicate JSON field: {key}")
            result[key] = value
        return result

    def reject_constant(value):
        raise WorkflowSchemaError(f"{label} must be finite JSON: {value}")

    try:
        value = json.loads(
            text, object_pairs_hook=unique_fields, parse_constant=reject_constant
        )
    except json.JSONDecodeError as exc:
        raise WorkflowSchemaError(f"cannot parse {label}") from exc
    if not isinstance(value, dict):
        raise WorkflowSchemaError(f"{label} must be an object")
    return value


def _check_seal(value: Mapping[str, Any], *, label: str) -> str:
    body = dict(value)
    declared = body.pop("contract_digest")
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise WorkflowSchemaError(f"{label} seal must be a lowercase SHA-256")
    try:
        actual = canonical_json_sha256(body)
    except (ValueError, TypeError) as exc:
        raise WorkflowSchemaError(f"{label} must be finite JSON") from exc
    if actual != declared:
        raise WorkflowSchemaError(f"{label} seal digest mismatch")
    return declared


def _load_profile(reference: Any, *, root: Path) -> tuple[GraphProfile, dict]:
    if not isinstance(reference, Mapping):
        raise WorkflowSchemaError("graph profile reference must be an object")
    _exact_keys(reference, {"path", "sha256"}, "graph profile reference")
    relative, declared = reference["path"], reference["sha256"]
    if (
        not isinstance(relative, str)
        or not relative
        or ":" in relative
        or "\\" in relative
    ):
        raise WorkflowSchemaError(
            "graph profile path must be checkout-relative POSIX text"
        )
    parts = PurePosixPath(relative)
    if (
        parts.is_absolute()
        or ".." in parts.parts
        or len(parts.parts) < 2
        or parts.parts[0] != "config"
    ):
        raise WorkflowSchemaError(
            "graph profile path must remain under checkout config/"
        )
    if not isinstance(declared, str) or not _SHA256_RE.fullmatch(declared):
        raise WorkflowSchemaError(
            "graph profile file digest must be a lowercase SHA-256"
        )
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkflowSchemaError("graph profile path escapes checkout") from exc
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise WorkflowSchemaError(f"graph profile is absent: {relative}") from exc
    if hashlib.sha256(raw).hexdigest() != declared:
        raise WorkflowSchemaError("graph profile file digest mismatch")
    try:
        value = strict_json_object(raw.decode("utf-8"), label="graph profile")
    except UnicodeError as exc:
        raise WorkflowSchemaError("graph profile must be UTF-8 JSON") from exc
    _exact_keys(value, _PROFILE_KEYS, "graph profile")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise WorkflowSchemaError("unsupported graph profile schema")
    seal = _check_seal(value, label="graph profile")
    detectors = _string_list(value["detectors"], "profile detectors")
    if any(item not in {"H1", "L1", "V1"} for item in detectors):
        raise WorkflowSchemaError(
            "profile detectors must be explicit H1/L1/V1 identifiers"
        )
    return GraphProfile(
        profile_id=_identifier(value["profile_id"], "profile id"),
        observing_run=_identifier(value["observing_run"], "profile observing run"),
        detectors=detectors,
        reference=FileReference(relative, declared),
        contract_digest=seal,
    ), value


def validate_profile_workflow(payload: dict, *, root: Path) -> WorkflowSpec:
    """Validate v2 without relaxing the v1 field set or graph contract."""
    _exact_keys(payload, _TOP_LEVEL_KEYS | {"graph_profile"}, "workflow v2")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 2:
        raise WorkflowSchemaError("unsupported workflow v2 schema")
    workflow_id = _identifier(payload["workflow_id"], "workflow_id")
    adapter = _identifier(payload["adapter"], "adapter")
    seal = _check_seal(payload, label="workflow v2")
    root = root.resolve()
    profile, raw_profile = _load_profile(payload["graph_profile"], root=root)
    if raw_profile["adapter"] != adapter:
        raise WorkflowSchemaError("graph profile adapter differs from workflow")
    if not isinstance(payload["stages"], list) or not payload["stages"]:
        raise WorkflowSchemaError("profile graph must not be empty")
    if payload["stages"] != raw_profile["stages"]:
        raise WorkflowSchemaError("workflow differs from sealed profile graph")

    raw_configs = payload["scientific_configs"]
    if not isinstance(raw_configs, Mapping) or not raw_configs:
        raise WorkflowSchemaError("scientific_configs must be a non-empty object")
    configs = {}
    used_paths = set()
    for raw_name, reference in raw_configs.items():
        name = _identifier(raw_name, "scientific config name")
        validated = _validate_file_reference(reference, name=name, root=root)
        if validated.path in used_paths:
            raise WorkflowSchemaError(
                "scientific config path is referenced more than once"
            )
        used_paths.add(validated.path)
        configs[name] = validated
    for stage in payload["stages"]:
        if not isinstance(stage, Mapping):
            raise WorkflowSchemaError("workflow stage must be an object")
        for field in ("outcome_visibility", "resumability"):
            if not isinstance(stage.get(field), str):
                raise WorkflowSchemaError(f"stage {field} must be text")
        dependencies = stage.get("dependencies")
        if not isinstance(dependencies, list):
            raise WorkflowSchemaError("stage dependencies must be a list")
        for dependency in dependencies:
            if not isinstance(dependency, Mapping) or not isinstance(
                dependency.get("gate"), str
            ):
                raise WorkflowSchemaError("stage dependency gate must be text")
    stages = tuple(
        _validate_stage(stage, config_names=set(configs)) for stage in payload["stages"]
    )
    _validate_graph(stages, profile_graph=True)
    for stage in stages:
        for token in stage.verifier_command:
            if token.startswith("scripts/") and token.endswith(".py"):
                path = (root / token).resolve()
                try:
                    path.relative_to(root)
                except ValueError as exc:
                    raise WorkflowSchemaError(
                        f"stage {stage.name} verifier escapes the repository"
                    ) from exc
                if not path.is_file():
                    raise WorkflowSchemaError(
                        f"stage {stage.name} verifier is absent: {token}"
                    )
    referenced = {name for stage in stages for name in stage.config_refs}
    if set(configs) != referenced:
        raise WorkflowSchemaError("scientific configs are not bound to a stage")
    policies = payload["policies"]
    if not isinstance(policies, Mapping):
        raise WorkflowSchemaError("policies must be an object")
    _exact_keys(policies, _POLICY_KEYS, "workflow policies")
    if any(value is not True for value in policies.values()):
        raise WorkflowSchemaError("every frozen product policy must remain enabled")
    return WorkflowSpec(
        schema_version=2,
        workflow_id=workflow_id,
        adapter=adapter,
        scientific_configs=MappingProxyType(configs),
        stages=stages,
        policies=MappingProxyType(dict(policies)),
        contract_digest=seal,
        graph_profile=profile,
    )
