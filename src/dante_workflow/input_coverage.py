"""Exact declared primary-window coverage in metadata, not raw admission."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

from .input_preflight import (
    InputPreflightError,
    _file,
    _hash,
    _select,
    inspect_input_binding,
)
from .schema_v2 import strict_json_object

if TYPE_CHECKING:
    from .adapters.base import StageAdapter
    from .schema import WorkflowSpec


class InputCoverageError(InputPreflightError):
    """Declared population or its pinned coverage inputs cannot be validated."""


@dataclass(frozen=True, slots=True)
class InputCoverageBinding:
    """Source-audited selectors and policy label; no shared scientific defaults."""

    population: str
    selection_policy: str
    expected_counts: tuple[str, ...]
    expected_identity_sha256: tuple[str, ...]
    references: Mapping[str, tuple[str, ...]]
    window_fields: Mapping[str, tuple[str, ...]]
    manifest_fields: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        for field in ("population", "selection_policy"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field):
                raise InputCoverageError("coverage population/policy must be explicit")
        for field in ("expected_counts", "expected_identity_sha256"):
            self._pointer(getattr(self, field))
        for field, required in (
            ("references", None),
            (
                "window_fields",
                {"detector", "analysis_start", "duration", "context_interval"},
            ),
            ("manifest_fields", {"detector", "start", "end"}),
        ):
            value = getattr(self, field)
            if (
                not isinstance(value, Mapping)
                or not value
                or (required and set(value) != required)
            ):
                raise InputCoverageError(f"coverage {field} selectors are incomplete")
            for name, pointer in value.items():
                if not isinstance(name, str) or not name:
                    raise InputCoverageError(
                        "coverage reference roles must be explicit"
                    )
                self._pointer(pointer)
            object.__setattr__(self, field, MappingProxyType(dict(value)))

    @staticmethod
    def _pointer(value: Any) -> None:
        if (
            not isinstance(value, tuple)
            or not value
            or any(not isinstance(part, str) or not part for part in value)
        ):
            raise InputCoverageError("coverage field paths must be explicit tuples")


def _number(value: Any) -> float:
    if type(value) not in (int, float):
        raise InputCoverageError(
            "GPS/geometry values must be finite numbers, not coerced strings"
        )
    try:
        result = float(value)
    except OverflowError as exc:
        raise InputCoverageError("GPS/geometry value is outside finite range") from exc
    if not math.isfinite(result):
        raise InputCoverageError("GPS/geometry values must be finite")
    if type(value) is int and int(result) != value:
        raise InputCoverageError("GPS/geometry conversion must not round integers")
    return result


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InputCoverageError(f"coverage input cannot be read: {path}") from exc


def _references(
    root: Path, payload: Mapping[str, Any], binding: InputCoverageBinding
) -> dict[str, Any]:
    result = {}
    for role, pointer in binding.references.items():
        reference = _select(payload, pointer)
        if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
            raise InputCoverageError("coverage reference requires exact path/SHA")
        if not isinstance(reference["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", reference["sha256"]
        ):
            raise InputCoverageError("coverage reference SHA is invalid")
        if _hash(_file(root, reference["path"])) != reference["sha256"]:
            raise InputCoverageError(f"coverage reference SHA mismatch: {role}")
        result[role] = dict(reference)
    return result


def _components(
    manifest_bytes: bytes, binding: InputCoverageBinding, detectors: tuple[str, ...]
):
    spans = {detector: [] for detector in detectors}
    for line in manifest_bytes.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = strict_json_object(line, label="frozen raw manifest row")
        detector = _select(row, binding.manifest_fields["detector"])
        if not isinstance(detector, str) or detector not in spans:
            raise InputCoverageError("manifest detector differs from frozen profile")
        start = _number(_select(row, binding.manifest_fields["start"]))
        end = _number(_select(row, binding.manifest_fields["end"]))
        if end <= start:
            raise InputCoverageError("manifest span must have positive duration")
        spans[detector].append((start, end))
    result = {}
    for detector, values in spans.items():
        merged = []
        for start, end in sorted(values):
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        if not merged:
            raise InputCoverageError(f"manifest has no coverage for {detector}")
        result[detector] = ([start for start, _ in merged], merged)
    return result


def inspect_input_coverage(
    spec: WorkflowSpec, adapter: StageAdapter, *, root: Path
) -> dict[str, Any]:
    """Recheck exactly the frozen primary selection; no data/DQ retuning.

    Hashes and bounds describe frozen metadata only. Physical raw file presence,
    numerical values, DQ flags and live/public coverage are not checked here.
    """
    root = root.resolve()
    inputs = inspect_input_binding(spec, adapter, root=root)
    boundary = {
        "schema_version": 1,
        "scope": "PRIMARY_SCAN_MANIFEST_GPS_CONTEXT_ONLY",
        "observing_run": adapter.observing_run,
        "detectors": list(adapter.detectors),
        "workflow_contract_digest": spec.contract_digest,
        "scientific_execution_ready": False,
        "exact_gps_manifest_coverage_checked": False,
        "live_coverage_checked": False,
        "physical_raw_files_checked": False,
        "raw_samples_checked": False,
        "calibration_coverage_checked": False,
        "dq_flag_eligibility_checked": False,
        "runtime_equivalence_checked": False,
        "writer_exclusion_established": False,
    }
    binding = adapter.input_coverage_binding()
    if inputs["blockers"] or binding is None:
        return {
            **boundary,
            "status": "BLOCKED_INPUT_COVERAGE",
            "blockers": inputs["blockers"] or ["MISSING_AUDITED_COVERAGE_BINDING"],
        }
    if not isinstance(binding, InputCoverageBinding):
        raise InputCoverageError("coverage binding must be typed")
    contract = inputs["input_contract"]
    contract_bytes = _read(_file(root, contract["path"]))
    if hashlib.sha256(contract_bytes).hexdigest() != contract["sha256"]:
        raise InputCoverageError("coverage contract changed before inspection")
    payload = strict_json_object(
        contract_bytes.decode("utf-8"), label="coverage contract"
    )
    references = _references(root, payload, binding)
    counts_expected = _select(payload, binding.expected_counts)
    identity_expected = _select(payload, binding.expected_identity_sha256)
    if (
        not isinstance(counts_expected, dict)
        or set(counts_expected) != set(adapter.detectors)
        or any(
            type(value) is not int or value <= 0 for value in counts_expected.values()
        )
    ):
        raise InputCoverageError(
            "expected detector counts must be explicit positive integers"
        )
    if not isinstance(identity_expected, str) or not re.fullmatch(
        r"[0-9a-f]{64}", identity_expected
    ):
        raise InputCoverageError("expected identity digest is invalid")
    geometry = inputs["declarations"]
    if (
        not {"analysis_duration_s", "left_context_s", "right_context_s"}.issubset(
            geometry
        )
        or "raw_manifest" not in inputs["inputs"]
    ):
        raise InputCoverageError(
            "coverage requires explicit geometry and raw manifest roles"
        )
    duration = _number(geometry["analysis_duration_s"]["value"])
    left = _number(geometry["left_context_s"]["value"])
    right = _number(geometry["right_context_s"]["value"])
    if duration <= 0 or left < 0 or right < 0:
        raise InputCoverageError("declared geometry is invalid")
    manifest = inputs["inputs"]["raw_manifest"]
    manifest_bytes = _read(_file(root, manifest["path"]))
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest["sha256"]:
        raise InputCoverageError("raw manifest changed before coverage inspection")
    components = _components(manifest_bytes, binding, adapter.detectors)
    digest = hashlib.sha256()
    counts = dict.fromkeys(adapter.detectors, 0)
    previous = None
    rows = adapter.iter_input_coverage(root)
    if rows is None:
        raise InputCoverageError("coverage provider absent")
    for row in rows:
        detector = _select(row, binding.window_fields["detector"])
        if not isinstance(detector, str) or detector not in counts:
            raise InputCoverageError("window detector differs from frozen profile")
        start = _number(_select(row, binding.window_fields["analysis_start"]))
        actual_duration = _number(_select(row, binding.window_fields["duration"]))
        interval = _select(row, binding.window_fields["context_interval"])
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise InputCoverageError("window requires an explicit context interval")
        begin, end = map(_number, interval)
        if (
            actual_duration != duration
            or begin != start - left
            or end != start + duration + right
        ):
            raise InputCoverageError("window geometry differs from frozen declaration")
        key = (detector, start)
        if previous is not None and key <= previous:
            raise InputCoverageError("window identities must be unique and ordered")
        previous = key
        starts, merged = components[detector]
        index = bisect_right(starts, begin) - 1
        if index < 0 or merged[index][1] < end:
            raise InputCoverageError(
                "declared window lacks complete manifest context coverage"
            )
        counts[detector] += 1
        try:
            row_bytes = (
                json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise InputCoverageError(
                "window identity must be finite canonical JSON"
            ) from exc
        digest.update(row_bytes)
    if counts != counts_expected or digest.hexdigest() != identity_expected:
        raise InputCoverageError("primary population count/identity digest mismatch")
    if (
        inspect_input_binding(spec, adapter, root=root) != inputs
        or _references(root, payload, binding) != references
    ):
        raise InputCoverageError("coverage inputs changed during inspection")
    return {
        **boundary,
        "status": "PASS_PRIMARY_SCAN_MANIFEST_COVERAGE_ONLY",
        "blockers": [],
        "exact_gps_manifest_coverage_checked": True,
        "population": binding.population,
        "selection_policy": binding.selection_policy,
        "additional_dq_filter_applied": False,
        "input_contract": contract,
        "coverage_references": references,
        "counts": counts,
        "identity_jsonl_sha256": digest.hexdigest(),
        "remaining_gates": [
            "CALIBRATION_INPUT_COVERAGE",
            "PHYSICAL_RAW_AND_SAMPLE_VALIDITY",
            "SCIENTIFIC_RUNTIME_AND_SOURCE_PREFLIGHT",
            "CLEAN_INSTALL_NUMERICAL_EXECUTION_AND_VERIFICATION",
        ],
    }
