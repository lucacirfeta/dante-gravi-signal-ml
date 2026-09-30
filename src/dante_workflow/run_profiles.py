"""Read-only public-run profiles; availability is not scientific authorization.

No data, fit, null or outcome is opened here. A bound workflow still needs its
own scientific preflight, input receipts, runtime and standalone verifiers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from .adapters import build_adapter
from .schema import canonical_json_sha256, load_workflow_spec


DEFAULT_REGISTRY_RELATIVE = Path("config/dante_workflow_runs_v1.json")
_DETECTORS = frozenset({"H1", "L1", "V1"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_SCOPE = "PUBLIC_STRAIN_CATALOGUE_NOT_COVERAGE_OR_VALIDATION"
_REMAINING_GATES = (
    "EXACT_GPS_DATA_AND_DQ_COVERAGE",
    "FROZEN_REFERENCE_CALIBRATION_AND_POPULATION_RECEIPTS",
    "SCIENTIFIC_RUNTIME_AND_SOURCE_PREFLIGHT",
    "STAGE_EXECUTION_AND_INDEPENDENT_VERIFICATION",
)


class RunProfileError(ValueError):
    """Reject unsupported or unbound run selection before creating state."""


def _keys(value: Any, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise RunProfileError(f"{label} must have exactly {sorted(expected)}")


def _detectors(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise RunProfileError("explicit non-empty detector selection is required")
    if any(not isinstance(item, str) or item not in _DETECTORS for item in value):
        raise RunProfileError("detector scope is limited to H1, L1 and V1")
    if len(set(value)) != len(value):
        raise RunProfileError("duplicate detectors are not allowed")
    return tuple(sorted(value))


def _url(value: Any) -> str:
    if not isinstance(value, str):
        raise RunProfileError("catalogue URLs must be GWOSC HTTPS URLs")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "gwosc.org"
        or parsed.query
        or parsed.fragment
    ):
        raise RunProfileError("catalogue URLs must be GWOSC HTTPS URLs")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RunProfileError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _read_object(path: Path) -> dict[str, Any]:
    try:
        result = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RunProfileError(
            f"could not read profile or parent contract: {path}"
        ) from exc
    if not isinstance(result, dict):
        raise RunProfileError("profile and parent contracts must be JSON objects")
    return result


@dataclass(frozen=True, slots=True)
class ContractBinding:
    path: str
    contract_digest: str
    detectors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "contract_digest": self.contract_digest,
            "detectors": list(self.detectors),
        }


def _binding(value: Any, *, root: Path, method: bool) -> ContractBinding | None:
    if value is None:
        return None
    expected = {"path", "contract_digest", "detectors"}
    if method:
        expected.add("detector_scope_path")
    _keys(value, expected, "contract binding")
    path_text = value["path"]
    if not isinstance(path_text, str) or "\\" in path_text or ":" in path_text:
        raise RunProfileError("binding path must be a checkout-relative POSIX path")
    relative = PurePosixPath(path_text)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:1] != ("config",)
        or relative.suffix != ".json"
    ):
        raise RunProfileError("binding path must remain under checkout config/")
    path = (root / path_text).resolve()
    if not path.is_relative_to(root / "config"):
        raise RunProfileError("binding path resolves outside checkout config/")
    declared = value["contract_digest"]
    if not isinstance(declared, str) or not _SHA256.fullmatch(declared):
        raise RunProfileError("parent contract digest must be lowercase SHA-256")
    payload = _read_object(path)
    body = dict(payload)
    actual_declared = body.pop("contract_digest", None)
    if actual_declared != declared or canonical_json_sha256(body) != declared:
        raise RunProfileError(f"parent contract digest mismatch: {path_text}")
    detectors = _detectors(value["detectors"])
    if method:
        pointer = value["detector_scope_path"]
        if (
            not isinstance(pointer, list)
            or not pointer
            or any(not isinstance(part, str) or not part for part in pointer)
        ):
            raise RunProfileError("method detector scope path must be explicit")
        scope: Any = payload
        for part in pointer:
            if not isinstance(scope, dict) or part not in scope:
                raise RunProfileError(
                    "method detector scope path is absent from parent"
                )
            scope = scope[part]
        if _detectors(scope) != detectors:
            raise RunProfileError("method detector scope differs from frozen parent")
    return ContractBinding(path_text, declared, detectors)


@dataclass(frozen=True, slots=True)
class RunProfile:
    name: str
    public_strain_detectors: tuple[str, ...]
    data_url: str
    method_contract: ContractBinding | None
    workflow_contract: ContractBinding | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "public_strain_detectors": list(self.public_strain_detectors),
            "data_url": self.data_url,
            "method_contract": self.method_contract.to_dict()
            if self.method_contract
            else None,
            "workflow_contract": self.workflow_contract.to_dict()
            if self.workflow_contract
            else None,
        }


@dataclass(frozen=True, slots=True)
class RunRegistry:
    registry_id: str
    registry_digest: str
    catalogue_source: str
    checked_on: str
    profiles: Mapping[str, RunProfile]
    repository_root: Path

    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "RUN_PROFILE_CATALOGUE",
            "scope": _SCOPE,
            "registry_id": self.registry_id,
            "registry_digest": self.registry_digest,
            "catalogue_source": self.catalogue_source,
            "checked_on": self.checked_on,
            "runs": [profile.to_dict() for profile in self.profiles.values()],
        }

    def profile(self, observing_run: str) -> RunProfile:
        if isinstance(observing_run, str):
            for name, profile in self.profiles.items():
                if name.casefold() == observing_run.casefold():
                    return profile
        raise RunProfileError(f"unknown observing run: {observing_run!r}; no fallback")

    def readiness(self, observing_run: str, detectors: Sequence[str]) -> dict[str, Any]:
        profile = self.profile(observing_run)
        selected = _detectors(detectors)
        unavailable = sorted(set(selected) - set(profile.public_strain_detectors))
        if unavailable:
            raise RunProfileError(
                f"{unavailable} strain is not published for {profile.name}"
            )
        blockers: list[str] = []
        method = profile.method_contract
        workflow = profile.workflow_contract
        if method is None or not set(selected).issubset(method.detectors):
            blockers.append("MISSING_DETECTOR_METHOD_CONTRACT")
        if workflow is None:
            blockers.append("MISSING_WORKFLOW_ADAPTER_CONTRACT")
        elif selected != workflow.detectors:
            blockers.append("DETECTOR_SELECTION_DIFFERS_FROM_FROZEN_WORKFLOW")
        return {
            "schema_version": 1,
            "status": "BLOCKED_RUN_PROFILE"
            if blockers
            else "PASS_RUN_PROFILE_BINDING_ONLY",
            "observing_run": profile.name,
            "registry_digest": self.registry_digest,
            "public_strain_detectors": list(selected),
            "catalogue_checked_on": self.checked_on,
            "data_url": profile.data_url,
            "method_contract": method.to_dict() if method else None,
            "workflow_contract": workflow.to_dict() if workflow else None,
            "blockers": blockers,
            "remaining_gates": list(_REMAINING_GATES),
            "scientific_execution_ready": False,
            "live_coverage_checked": False,
        }

    def resolve_workflow(self, observing_run: str, detectors: Sequence[str]) -> Path:
        report = self.readiness(observing_run, detectors)
        if report["blockers"]:
            raise RunProfileError(
                f"run profile blocked: {', '.join(report['blockers'])}"
            )
        binding = self.profile(observing_run).workflow_contract
        assert binding is not None  # readiness rejects an unbound workflow
        return self.repository_root / binding.path


def validate_run_registry(value: Any, *, root: Path) -> RunRegistry:
    _keys(
        value,
        {
            "schema_version",
            "registry_id",
            "catalogue_source",
            "checked_on",
            "runs",
            "registry_digest",
        },
        "run registry",
    )
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise RunProfileError("unsupported run registry schema")
    registry_id = value["registry_id"]
    if not isinstance(registry_id, str) or not _NAME.fullmatch(registry_id):
        raise RunProfileError("registry_id must be an identifier")
    body = dict(value)
    digest = body.pop("registry_digest")
    if (
        not isinstance(digest, str)
        or not _SHA256.fullmatch(digest)
        or canonical_json_sha256(body) != digest
    ):
        raise RunProfileError("run registry digest mismatch")
    source = _url(value["catalogue_source"])
    checked_on = value["checked_on"]
    try:
        if (
            not isinstance(checked_on, str)
            or date.fromisoformat(checked_on).isoformat() != checked_on
        ):
            raise ValueError("invalid date")
    except ValueError as exc:
        raise RunProfileError("checked_on must be an ISO date") from exc
    root = root.resolve()
    raw_profiles = value["runs"]
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise RunProfileError("runs must be a non-empty list")
    profiles: dict[str, RunProfile] = {}
    folded_names: set[str] = set()
    for raw in raw_profiles:
        _keys(
            raw,
            {
                "name",
                "public_strain_detectors",
                "data_url",
                "method_contract",
                "workflow_contract",
            },
            "run profile",
        )
        name = raw["name"]
        if (
            not isinstance(name, str)
            or not _NAME.fullmatch(name)
            or name.casefold() in folded_names
        ):
            raise RunProfileError("run names must be unique identifiers")
        folded_names.add(name.casefold())
        available = _detectors(raw["public_strain_detectors"])
        method = _binding(raw["method_contract"], root=root, method=True)
        workflow = _binding(raw["workflow_contract"], root=root, method=False)
        for binding in (method, workflow):
            if binding and not set(binding.detectors).issubset(available):
                raise RunProfileError("contract detector scope exceeds public profile")
        if method:
            parent_run = _read_object(root / method.path).get("run")
            if parent_run is not None and (
                not isinstance(parent_run, str)
                or parent_run.casefold() != name.casefold()
            ):
                raise RunProfileError(
                    "method parent observing run differs from profile"
                )
        if workflow:
            spec = load_workflow_spec(root / workflow.path, root=root)
            adapter = build_adapter(spec)
            if adapter.observing_run != name:
                raise RunProfileError("adapter observing run differs from profile")
            if tuple(sorted(adapter.detectors)) != workflow.detectors:
                raise RunProfileError("adapter detector scope differs from profile")
            if (
                method is None
                or method.detectors != workflow.detectors
                or method.path
                not in {
                    reference.path for reference in spec.scientific_configs.values()
                }
            ):
                raise RunProfileError(
                    "workflow must bind the same method and detector scope"
                )
        profiles[name] = RunProfile(
            name, available, _url(raw["data_url"]), method, workflow
        )
    return RunRegistry(
        registry_id, digest, source, checked_on, MappingProxyType(profiles), root
    )


def load_run_registry(path: Path, *, root: Path) -> RunRegistry:
    return validate_run_registry(_read_object(path), root=root)
