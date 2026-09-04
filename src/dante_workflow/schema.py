"""Strict, content-addressed schema for DANTE workflow orchestration.

This module describes execution order and artifact boundaries only. Scientific
values remain in their existing frozen configuration files and are referenced
by repository-relative path plus SHA-256.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any


SCHEMA_VERSION = 1
REQUIRED_STAGE_NAMES = (
    "PREFLIGHT",
    "ACQUIRE",
    "CALIBRATE",
    "SCAN",
    "COHORT",
    "INDEX",
    "NATIVE_CALIBRATION",
    "RESCORE",
    "THRESHOLDS",
    "CLASSIFY",
    "TAXONOMY",
    "COINCIDENCE",
    "PEM",
    "COMPARE",
    "REPORT",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]*$")
_TOP_LEVEL_KEYS = {
    "schema_version",
    "workflow_id",
    "adapter",
    "scientific_configs",
    "stages",
    "policies",
    "contract_digest",
}
_POLICY_KEYS = {
    "scientific_configs_read_only",
    "new_run_on_contract_change",
    "resume_requires_identical_contract",
    "preserve_historical_runs",
    "hide_outcomes_until_verified",
    "verified_reports_only",
    "ui_worker_independent",
    "no_discovery_or_realtime_claim",
}
_STAGE_KEYS = {
    "name",
    "dependencies",
    "config_refs",
    "required_inputs",
    "expected_outputs",
    "verifier_command",
    "outcome_visibility",
    "resumability",
}
_DEPENDENCY_GATES = {"VERIFIED_STAGE", "CONTENT_DIGESTED_ARTIFACT"}
_VISIBILITY_POLICIES = {"INFRASTRUCTURE_ONLY", "AFTER_VERIFICATION"}
_RESUMABILITY_POLICIES = {
    "NOT_APPLICABLE",
    "RESTART_SAME_CONTRACT",
    "RESUME_IN_PLACE",
}


class WorkflowSchemaError(ValueError):
    """Raised when a workflow specification is incomplete or inconsistent."""


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise WorkflowSchemaError(
            f"{label} fields invalid; missing={missing}, unknown={unknown}"
        )


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise WorkflowSchemaError(f"{label} must be a non-empty identifier")
    return value


def _string_list(value: Any, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise WorkflowSchemaError(f"{label} must be a list of strings")
    result = tuple(value)
    if not allow_empty and not result:
        raise WorkflowSchemaError(f"{label} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise WorkflowSchemaError(f"{label} must contain non-empty strings")
    if len(set(result)) != len(result):
        raise WorkflowSchemaError(f"{label} must not contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class FileReference:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DependencySpec:
    stage: str
    gate: str
    artifact: str | None = None


@dataclass(frozen=True, slots=True)
class StageSpec:
    name: str
    dependencies: tuple[DependencySpec, ...]
    config_refs: tuple[str, ...]
    required_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    verifier_command: tuple[str, ...]
    outcome_visibility: str
    resumability: str


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    schema_version: int
    workflow_id: str
    adapter: str
    scientific_configs: Mapping[str, FileReference]
    stages: tuple[StageSpec, ...]
    policies: Mapping[str, bool]
    contract_digest: str

    def stage(self, name: str) -> StageSpec:
        for stage in self.stages:
            if stage.name == name:
                return stage
        raise KeyError(name)

    def topological_stage_names(self) -> tuple[str, ...]:
        positions = {stage.name: index for index, stage in enumerate(self.stages)}
        indegree = {stage.name: len(stage.dependencies) for stage in self.stages}
        dependants: dict[str, list[str]] = defaultdict(list)
        for stage in self.stages:
            for dependency in stage.dependencies:
                dependants[dependency.stage].append(stage.name)
        ready = sorted(
            (name for name, count in indegree.items() if count == 0),
            key=positions.__getitem__,
        )
        ordered: list[str] = []
        while ready:
            name = ready.pop(0)
            ordered.append(name)
            for dependant in sorted(dependants[name], key=positions.__getitem__):
                indegree[dependant] -= 1
                if indegree[dependant] == 0:
                    ready.append(dependant)
                    ready.sort(key=positions.__getitem__)
        if len(ordered) != len(self.stages):
            raise WorkflowSchemaError("workflow stage dependencies contain a cycle")
        return tuple(ordered)


def _validate_file_reference(
    value: Any, *, name: str, root: Path
) -> FileReference:
    if not isinstance(value, Mapping):
        raise WorkflowSchemaError(f"scientific config {name!r} must be an object")
    _exact_keys(value, {"path", "sha256"}, f"scientific config {name!r}")
    relative = value["path"]
    digest = value["sha256"]
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise WorkflowSchemaError(
            f"scientific config {name!r} path must be repository-relative POSIX text"
        )
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise WorkflowSchemaError(
            f"scientific config {name!r} is missing a lowercase SHA-256 digest"
        )
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkflowSchemaError(
            f"scientific config {name!r} escapes the repository"
        ) from exc
    if not path.is_file():
        raise WorkflowSchemaError(f"scientific config {name!r} is absent: {relative}")
    actual = _file_sha256(path)
    if actual != digest:
        raise WorkflowSchemaError(
            f"scientific config {name!r} digest mismatch: {actual} != {digest}"
        )
    return FileReference(path=relative, sha256=digest)


def _validate_dependency(value: Any, *, stage_name: str) -> DependencySpec:
    if not isinstance(value, Mapping):
        raise WorkflowSchemaError(f"stage {stage_name} dependency must be an object")
    gate = value.get("gate")
    expected = {"stage", "gate", "artifact"} if gate == "CONTENT_DIGESTED_ARTIFACT" else {"stage", "gate"}
    _exact_keys(value, expected, f"stage {stage_name} dependency")
    dependency_stage = _identifier(value["stage"], f"stage {stage_name} dependency stage")
    if gate not in _DEPENDENCY_GATES:
        raise WorkflowSchemaError(f"stage {stage_name} has invalid dependency gate {gate!r}")
    artifact = None
    if gate == "CONTENT_DIGESTED_ARTIFACT":
        artifact = _identifier(
            value["artifact"], f"stage {stage_name} dependency artifact"
        )
    return DependencySpec(stage=dependency_stage, gate=gate, artifact=artifact)


def _validate_stage(value: Any, *, config_names: set[str]) -> StageSpec:
    if not isinstance(value, Mapping):
        raise WorkflowSchemaError("workflow stage must be an object")
    stage_name = str(value.get("name", "<unknown>"))
    _exact_keys(value, _STAGE_KEYS, f"stage {stage_name}")
    name = _identifier(value["name"], "stage name")
    raw_dependencies = value["dependencies"]
    if isinstance(raw_dependencies, (str, bytes)) or not isinstance(
        raw_dependencies, Sequence
    ):
        raise WorkflowSchemaError(f"stage {name} dependencies must be a list")
    dependencies = tuple(
        _validate_dependency(item, stage_name=name) for item in raw_dependencies
    )
    dependency_names = [item.stage for item in dependencies]
    if len(set(dependency_names)) != len(dependency_names):
        raise WorkflowSchemaError(f"stage {name} repeats a dependency")
    config_refs = _string_list(value["config_refs"], f"stage {name} config_refs")
    unknown_refs = sorted(set(config_refs) - config_names)
    if unknown_refs:
        raise WorkflowSchemaError(f"stage {name} has unknown config refs: {unknown_refs}")
    required_inputs = _string_list(
        value["required_inputs"], f"stage {name} required_inputs"
    )
    expected_outputs = _string_list(
        value["expected_outputs"], f"stage {name} expected_outputs"
    )
    verifier_command = _string_list(
        value["verifier_command"], f"stage {name} verifier_command"
    )
    visibility = value["outcome_visibility"]
    if visibility not in _VISIBILITY_POLICIES:
        raise WorkflowSchemaError(f"stage {name} has invalid outcome visibility")
    resumability = value["resumability"]
    if resumability not in _RESUMABILITY_POLICIES:
        raise WorkflowSchemaError(f"stage {name} has invalid resumability")
    return StageSpec(
        name=name,
        dependencies=dependencies,
        config_refs=config_refs,
        required_inputs=required_inputs,
        expected_outputs=expected_outputs,
        verifier_command=verifier_command,
        outcome_visibility=visibility,
        resumability=resumability,
    )


def _validate_graph(stages: tuple[StageSpec, ...]) -> None:
    names = [stage.name for stage in stages]
    if len(set(names)) != len(names):
        raise WorkflowSchemaError("workflow stage names must be unique")
    if set(names) != set(REQUIRED_STAGE_NAMES):
        raise WorkflowSchemaError(
            "workflow must define exactly the frozen 15-stage productization graph"
        )
    stage_by_name = {stage.name: stage for stage in stages}
    for stage in stages:
        unknown = sorted(
            dependency.stage
            for dependency in stage.dependencies
            if dependency.stage not in stage_by_name
        )
        if unknown:
            raise WorkflowSchemaError(
                f"stage {stage.name} has unknown dependencies: {unknown}"
            )
        if any(dependency.stage == stage.name for dependency in stage.dependencies):
            raise WorkflowSchemaError(f"stage {stage.name} depends on itself")

    spec = WorkflowSpec(1, "graph-check", "graph.check", {}, stages, {}, "0" * 64)
    ordered = spec.topological_stage_names()
    ancestors: dict[str, set[str]] = {}
    for name in ordered:
        direct = {dependency.stage for dependency in stage_by_name[name].dependencies}
        ancestors[name] = direct | {
            ancestor
            for dependency in direct
            for ancestor in ancestors[dependency]
        }

    producers: dict[str, str] = {}
    for stage in stages:
        for output in stage.expected_outputs:
            if output in producers:
                raise WorkflowSchemaError(
                    f"artifact {output!r} has multiple producers"
                )
            producers[output] = stage.name
    for stage in stages:
        for dependency in stage.dependencies:
            if dependency.gate == "CONTENT_DIGESTED_ARTIFACT":
                if dependency.artifact not in stage_by_name[dependency.stage].expected_outputs:
                    raise WorkflowSchemaError(
                        f"stage {stage.name} gates on an undeclared artifact"
                    )
                if dependency.artifact not in stage.required_inputs:
                    raise WorkflowSchemaError(
                        f"stage {stage.name} must declare its artifact gate as an input"
                    )
        for required_input in stage.required_inputs:
            if required_input.startswith("external:"):
                continue
            producer = producers.get(required_input)
            if producer is None or producer not in ancestors[stage.name]:
                raise WorkflowSchemaError(
                    f"stage {stage.name} input {required_input!r} is not produced upstream"
                )
    native = stage_by_name["NATIVE_CALIBRATION"]
    native_dependencies = {dependency.stage: dependency for dependency in native.dependencies}
    if native_dependencies.get("COHORT", DependencySpec("", "")).gate != "VERIFIED_STAGE":
        raise WorkflowSchemaError("NATIVE_CALIBRATION requires verified COHORT")
    index_dependency = native_dependencies.get("INDEX")
    if (
        index_dependency is None
        or index_dependency.gate != "CONTENT_DIGESTED_ARTIFACT"
        or index_dependency.artifact != "index_window_manifest"
    ):
        raise WorkflowSchemaError(
            "NATIVE_CALIBRATION requires the content-digested INDEX window manifest"
        )
    rescore_dependencies = {item.stage: item.gate for item in stage_by_name["RESCORE"].dependencies}
    if rescore_dependencies.get("INDEX") != "VERIFIED_STAGE" or rescore_dependencies.get(
        "NATIVE_CALIBRATION"
    ) != "VERIFIED_STAGE":
        raise WorkflowSchemaError(
            "RESCORE requires verified INDEX and NATIVE_CALIBRATION stages"
        )


def validate_workflow_spec(value: Mapping[str, Any], *, root: Path) -> WorkflowSpec:
    """Validate a complete workflow and every pinned scientific reference."""

    try:
        payload = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise WorkflowSchemaError("workflow must be finite JSON data") from exc
    if not isinstance(payload, dict):
        raise WorkflowSchemaError("workflow specification must be an object")
    _exact_keys(payload, _TOP_LEVEL_KEYS, "workflow")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise WorkflowSchemaError(
            f"unsupported workflow schema {payload['schema_version']!r}"
        )
    workflow_id = _identifier(payload["workflow_id"], "workflow_id")
    adapter = _identifier(payload["adapter"], "adapter")
    declared_digest = payload["contract_digest"]
    if not isinstance(declared_digest, str) or not _SHA256_RE.fullmatch(declared_digest):
        raise WorkflowSchemaError("workflow contract_digest must be a lowercase SHA-256")
    body = dict(payload)
    body.pop("contract_digest")
    actual_digest = canonical_json_sha256(body)
    if actual_digest != declared_digest:
        raise WorkflowSchemaError(
            f"workflow contract digest mismatch: {actual_digest} != {declared_digest}"
        )

    root = root.resolve()
    raw_configs = payload["scientific_configs"]
    if not isinstance(raw_configs, Mapping) or not raw_configs:
        raise WorkflowSchemaError("scientific_configs must be a non-empty object")
    scientific_configs: dict[str, FileReference] = {}
    used_paths: set[str] = set()
    for raw_name, reference in raw_configs.items():
        name = _identifier(raw_name, "scientific config name")
        validated = _validate_file_reference(reference, name=name, root=root)
        if validated.path in used_paths:
            raise WorkflowSchemaError(
                f"scientific config path is referenced more than once: {validated.path}"
            )
        used_paths.add(validated.path)
        scientific_configs[name] = validated

    raw_stages = payload["stages"]
    if isinstance(raw_stages, (str, bytes)) or not isinstance(raw_stages, Sequence):
        raise WorkflowSchemaError("stages must be a list")
    stages = tuple(
        _validate_stage(stage, config_names=set(scientific_configs))
        for stage in raw_stages
    )
    _validate_graph(stages)
    for stage in stages:
        for token in stage.verifier_command:
            if token.startswith("scripts/") and token.endswith(".py"):
                verifier_path = (root / token).resolve()
                try:
                    verifier_path.relative_to(root)
                except ValueError as exc:
                    raise WorkflowSchemaError(
                        f"stage {stage.name} verifier escapes the repository"
                    ) from exc
                if not verifier_path.is_file():
                    raise WorkflowSchemaError(
                        f"stage {stage.name} verifier is absent: {token}"
                    )
    referenced_configs = {
        config_ref for stage in stages for config_ref in stage.config_refs
    }
    unused_configs = sorted(set(scientific_configs) - referenced_configs)
    if unused_configs:
        raise WorkflowSchemaError(
            f"scientific configs are not bound to a stage: {unused_configs}"
        )

    raw_policies = payload["policies"]
    if not isinstance(raw_policies, Mapping):
        raise WorkflowSchemaError("policies must be an object")
    _exact_keys(raw_policies, _POLICY_KEYS, "workflow policies")
    if any(value is not True for value in raw_policies.values()):
        raise WorkflowSchemaError("every frozen product policy must remain enabled")

    return WorkflowSpec(
        schema_version=SCHEMA_VERSION,
        workflow_id=workflow_id,
        adapter=adapter,
        scientific_configs=MappingProxyType(scientific_configs),
        stages=stages,
        policies=MappingProxyType(dict(raw_policies)),
        contract_digest=declared_digest,
    )


def load_workflow_spec(path: Path, *, root: Path | None = None) -> WorkflowSpec:
    """Load a workflow JSON file and verify its self-digest and references."""

    path = path.resolve()
    repository_root = root.resolve() if root is not None else path.parent.parent.resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowSchemaError(f"cannot load workflow specification: {path}") from exc
    return validate_workflow_spec(value, root=repository_root)
