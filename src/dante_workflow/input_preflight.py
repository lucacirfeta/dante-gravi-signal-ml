"""Common input-binding inspection; never a scientific coverage certificate."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object

if TYPE_CHECKING:
    from .adapters.base import StageAdapter
    from .schema import WorkflowSpec


class InputPreflightError(ValueError):
    """An input binding is absent, changed or not confined to the checkout."""


@dataclass(frozen=True, slots=True)
class InputPreflightBinding:
    """Audited adapter selectors, not new scientific values or policies."""

    config_ref: str
    seal_field: str
    declarations: Mapping[str, tuple[str, ...]]
    references: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        for field in ("config_ref", "seal_field"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise InputPreflightError("binding identifiers must be explicit")
        for field in ("declarations", "references"):
            value = getattr(self, field)
            if not isinstance(value, Mapping) or not value:
                raise InputPreflightError("binding selectors must be non-empty")
            for role, pointer in value.items():
                if (
                    not isinstance(role, str)
                    or not role
                    or not isinstance(pointer, tuple)
                    or not pointer
                    or any(not isinstance(part, str) or not part for part in pointer)
                ):
                    raise InputPreflightError(
                        "selectors require exact named field paths"
                    )
            object.__setattr__(self, field, MappingProxyType(dict(value)))


def _select(payload: Mapping[str, Any], pointer: tuple[str, ...]) -> Any:
    current: Any = payload
    for part in pointer:
        if not isinstance(current, Mapping) or part not in current:
            raise InputPreflightError(f"frozen input field absent: {'/'.join(pointer)}")
        current = current[part]
    return current


def _file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise InputPreflightError("input path must be checkout-relative POSIX")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or not parts.parts:
        raise InputPreflightError("input path must remain inside checkout")
    candidate = root
    for part in parts.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise InputPreflightError("input bindings must not traverse symlinks")
    if not candidate.resolve().is_relative_to(root) or not candidate.is_file():
        raise InputPreflightError(f"input file absent or outside checkout: {relative}")
    return candidate


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise InputPreflightError(f"input file cannot be read: {path}") from exc
    return digest.hexdigest()


def inspect_input_binding(
    spec: WorkflowSpec, adapter: StageAdapter, *, root: Path
) -> dict[str, Any]:
    """Validate declared metadata bytes only, without creating workflow state.

    The result is a bounded administrative observation, not an input admission
    receipt. It cannot authorize execution or establish complete GPS/DQ/sample
    coverage. Hashes are observed during inspection, not under writer exclusion.
    """
    if adapter.spec != spec:
        raise InputPreflightError("adapter and input workflow must be identical")
    root = root.resolve()
    boundary = {
        "schema_version": 1,
        "scope": "FROZEN_INPUT_BINDING_ONLY",
        "observing_run": adapter.observing_run,
        "detectors": list(adapter.detectors),
        "workflow_contract_digest": spec.contract_digest,
        "scientific_execution_ready": False,
        "exact_gps_coverage_checked": False,
        "dq_eligibility_checked": False,
        "raw_samples_checked": False,
        "runtime_equivalence_checked": False,
        "writer_exclusion_established": False,
        "remaining_gates": [
            "EXACT_GPS_DATA_AND_DQ_COVERAGE",
            "RAW_SAMPLE_CONTEXT_AND_VALIDITY",
            "SCIENTIFIC_RUNTIME_AND_SOURCE_PREFLIGHT",
            "STAGE_EXECUTION_AND_INDEPENDENT_VERIFICATION",
        ],
    }
    binding = adapter.input_preflight_binding()
    if binding is None:
        return {
            **boundary,
            "status": "BLOCKED_INPUT_CONTRACT_BINDING",
            "blockers": ["MISSING_AUDITED_INPUT_BINDING"],
        }
    if not isinstance(binding, InputPreflightBinding):
        raise InputPreflightError("adapter must declare a typed input binding")
    if binding.config_ref not in spec.scientific_configs:
        raise InputPreflightError("input contract is not bound by the workflow")
    reference = spec.scientific_configs[binding.config_ref]
    contract_path = _file(root, reference.path)
    # Decode precisely the bytes that were hashed; do not reopen for JSON parsing.
    try:
        contract_bytes = contract_path.read_bytes()
    except OSError as exc:
        raise InputPreflightError("input contract cannot be read") from exc
    if hashlib.sha256(contract_bytes).hexdigest() != reference.sha256:
        raise InputPreflightError("input contract SHA mismatch")
    try:
        payload = strict_json_object(
            contract_bytes.decode("utf-8"), label="frozen input contract"
        )
    except (ValueError, UnicodeError) as exc:
        raise InputPreflightError("invalid frozen input contract JSON") from exc
    body = dict(payload)
    declared = body.pop(binding.seal_field, None)
    if declared != canonical_json_sha256(body):
        raise InputPreflightError("input contract seal mismatch")
    declarations = {
        role: {"field_path": list(pointer), "value": _select(payload, pointer)}
        for role, pointer in binding.declarations.items()
    }
    inputs = {}
    for role, pointer in binding.references.items():
        item = _select(payload, pointer)
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise InputPreflightError("input reference requires exact path and SHA")
        digest = item["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InputPreflightError("input reference SHA must be lowercase SHA-256")
        if _hash(_file(root, item["path"])) != digest:
            raise InputPreflightError(f"frozen input SHA mismatch: {role}")
        inputs[role] = {"field_path": list(pointer), **item}
    if _hash(contract_path) != reference.sha256:
        raise InputPreflightError("input contract changed during inspection")
    return {
        **boundary,
        "status": "PASS_INPUT_CONTRACT_BINDING_ONLY",
        "blockers": [],
        "input_contract": {
            "path": reference.path,
            "sha256": reference.sha256,
            "seal_field": binding.seal_field,
            "seal": declared,
        },
        "declarations": declarations,
        "inputs": inputs,
    }
