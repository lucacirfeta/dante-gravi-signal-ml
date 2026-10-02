"""Frozen calibration identity metadata and pinned input bytes, not scoring."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from types import MappingProxyType

from .input_coverage import (
    InputCoverageBinding,
    InputCoverageError,
    _components,
    _number,
    _read,
    _references,
)
from .input_preflight import _file, _hash, _select, inspect_input_binding
from .schema import canonical_json_sha256
from .schema_v2 import strict_json_object


@dataclass(frozen=True, slots=True)
class CalibrationInputBinding:
    """Explicit frozen selectors; an unbound profile never borrows a population."""

    inventory: tuple[str, ...]
    inventory_digest: tuple[str, ...]
    inventory_count: tuple[str, ...]
    identity_count: tuple[str, ...]
    expected_coverage: tuple[str, ...]
    expected_contexts: tuple[str, ...]
    expected_sessions: tuple[str, ...]
    references: Mapping[str, tuple[str, ...]]

    def __post_init__(self):
        for name in (
            "inventory",
            "inventory_digest",
            "inventory_count",
            "identity_count",
            "expected_coverage",
            "expected_contexts",
            "expected_sessions",
        ):
            InputCoverageBinding._pointer(getattr(self, name))
        if not isinstance(self.references, Mapping) or not self.references:
            raise InputCoverageError("calibration source binding is absent")
        for name, pointer in self.references.items():
            if not isinstance(name, str) or not name:
                raise InputCoverageError("calibration source role is invalid")
            InputCoverageBinding._pointer(pointer)
        object.__setattr__(self, "references", MappingProxyType(dict(self.references)))


def _inventory(root, payload, binding):
    refs = _select(payload, binding.inventory)
    count = _select(payload, binding.inventory_count)
    if (
        not isinstance(refs, list)
        or not refs
        or type(count) is not int
        or count != len(refs)
        or canonical_json_sha256(refs) != _select(payload, binding.inventory_digest)
    ):
        raise InputCoverageError("calibration inventory count/digest mismatch")
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
            raise InputCoverageError("calibration inventory requires exact references")
        path = _file(root, ref["path"])
        if ref["path"] in seen:
            raise InputCoverageError("duplicate calibration source")
        seen.add(ref["path"])
        if _hash(path) != ref["sha256"]:
            raise InputCoverageError("calibration source SHA mismatch")
    return refs


def _supplement(path, sha, missing, contract, sample_rate):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise InputCoverageError("acquisition receipt needs an explicit SHA pin")
    path = Path(path)
    if not path.is_absolute():
        raise InputCoverageError("acquisition receipt path must be absolute")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise InputCoverageError("acquisition receipt must not traverse symlinks")
    run_dir = path.parent.resolve()
    receipt = _file(run_dir, path.name)
    data = _read(receipt)
    if hashlib.sha256(data).hexdigest() != sha:
        raise InputCoverageError("acquisition receipt SHA mismatch")
    value = strict_json_object(data.decode("utf-8"), label="acquisition receipt")
    body = dict(value)
    digest = body.pop("manifest_digest", None)
    records = body.get("records")
    if (
        digest != canonical_json_sha256(body)
        or body.get("schema_version") != 1
        or body.get("status") != "COMPLETE_CONTENT_ADDRESSED_INPUTS"
        or body.get("protocol_digest") != contract["seal"]
        or body.get("protocol_reference")
        != {"path": contract["path"], "sha256": contract["sha256"]}
        or not isinstance(records, list)
        or type(body.get("record_count")) is not int
        or body["record_count"] != len(records)
        or body.get("record_digest") != canonical_json_sha256(records)
        or body.get("network_fetch_was_outcome_blind") is not True
        or body.get("scores_or_labels_accessed_during_fetch") != []
    ):
        raise InputCoverageError("acquisition receipt seal/parent/format mismatch")
    actual = set()
    for record in records:
        if not isinstance(record, dict):
            raise InputCoverageError("acquisition record must be an object")
        if not isinstance(record.get("detector"), str):
            raise InputCoverageError("acquisition detector is invalid")
        key = (
            record.get("detector"),
            _number(record.get("gps_start")),
            _number(record.get("gps_end")),
        )
        if key in actual or key not in missing:
            raise InputCoverageError("acquisition interval differs from missing inputs")
        actual.add(key)
        raw_path = _file(run_dir, record.get("relative_path"))
        if (
            record.get("sample_rate_hz") != sample_rate
            or type(record.get("sample_count")) is not int
            or record["sample_count"] != (key[2] - key[1]) * sample_rate
            or record.get("size_bytes") != raw_path.stat().st_size
            or _hash(raw_path) != record.get("file_sha256")
        ):
            raise InputCoverageError("acquired input file SHA mismatch")
    if actual != missing:
        raise InputCoverageError("acquisition receipt is incomplete")
    if _hash(receipt) != sha:
        raise InputCoverageError("acquisition receipt changed during inspection")
    return {
        "path": str(receipt),
        "sha256": sha,
        "seal": digest,
        "record_count": len(records),
    }


def inspect_calibration_inputs(
    spec, adapter, *, root, acquisition_manifest=None, acquisition_sha256=None
):
    """Observe frozen identities and bytes; never produce/consume score values."""
    root = Path(root).resolve()
    inputs = inspect_input_binding(spec, adapter, root=root)
    report = {
        "schema_version": 1,
        "scope": "PRIMARY_CALIBRATION_METADATA_AND_INPUT_BYTES_ONLY",
        "observing_run": adapter.observing_run,
        "detectors": list(adapter.detectors),
        "scientific_execution_ready": False,
        "raw_samples_checked": False,
        "score_values_read": False,
        "historical_full_row_digest_checked": False,
        "runtime_equivalence_checked": False,
        "writer_exclusion_established": False,
        "native_calibration_checked": False,
    }
    binding = adapter.calibration_input_binding()
    if inputs["blockers"] or binding is None:
        return {
            **report,
            "status": "BLOCKED_CALIBRATION_INPUTS",
            "blockers": inputs["blockers"] or ["MISSING_CALIBRATION_INPUT_BINDING"],
        }
    if not isinstance(binding, CalibrationInputBinding):
        raise InputCoverageError("calibration input binding must be typed")
    if (acquisition_manifest is None) != (acquisition_sha256 is None):
        raise InputCoverageError("acquisition path and SHA must be supplied together")
    contract = inputs["input_contract"]
    data = _read(_file(root, contract["path"]))
    if hashlib.sha256(data).hexdigest() != contract["sha256"]:
        raise InputCoverageError("calibration contract SHA mismatch")
    payload = strict_json_object(data.decode("utf-8"), label="calibration contract")
    references = _references(root, payload, binding)
    inventory = _inventory(root, payload, binding)
    source_paths = {ref["path"] for ref in inventory}
    geometry = inputs["declarations"]
    if (
        not {
            "analysis_duration_s",
            "left_context_s",
            "right_context_s",
            "sample_rate_hz",
        }.issubset(geometry)
        or "raw_manifest" not in inputs["inputs"]
    ):
        raise InputCoverageError(
            "calibration requires explicit geometry/manifest bindings"
        )
    duration = _number(geometry["analysis_duration_s"]["value"])
    left = _number(geometry["left_context_s"]["value"])
    right = _number(geometry["right_context_s"]["value"])
    sample_rate = _number(geometry["sample_rate_hz"]["value"])
    if duration <= 0 or left < 0 or right < 0 or sample_rate <= 0:
        raise InputCoverageError("calibration geometry is invalid")
    manifest = inputs["inputs"]["raw_manifest"]
    manifest_data = _read(_file(root, manifest["path"]))
    if hashlib.sha256(manifest_data).hexdigest() != manifest["sha256"]:
        raise InputCoverageError("calibration manifest SHA mismatch")
    coverage_binding = adapter.input_coverage_binding()
    if coverage_binding is None:
        raise InputCoverageError("calibration manifest selectors absent")
    components = _components(manifest_data, coverage_binding, adapter.detectors)
    single_spans = {detector: [] for detector in adapter.detectors}
    for line in manifest_data.decode("utf-8").splitlines():
        if line.strip():
            span = strict_json_object(line, label="calibration manifest span")
            detector = _select(span, coverage_binding.manifest_fields["detector"])
            single_spans[detector].append(
                tuple(
                    _number(_select(span, coverage_binding.manifest_fields[key]))
                    for key in ("start", "end")
                )
            )
    coverage = Counter()
    contexts = Counter()
    counts = Counter()
    sessions = set()
    identities = set()
    used_sources = set()
    missing = set()
    rows = adapter.iter_calibration_input_metadata(root, payload)
    if rows is None:
        raise InputCoverageError("calibration metadata reader absent")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "detector",
            "session_id",
            "catalog_gps_start",
            "analysis_gps_start",
            "required_padded_interval",
            "historical_context_disposition",
            "historical_hdf5",
        }:
            raise InputCoverageError(
                "calibration metadata fields differ from audited reader"
            )
        detector = row["detector"]
        source = row["historical_hdf5"]
        session = row["session_id"]
        if (
            not isinstance(detector, str)
            or not isinstance(source, str)
            or detector not in components
            or source not in source_paths
            or type(session) is not int
        ):
            raise InputCoverageError("calibration detector/source/session mismatch")
        catalog = _number(row["catalog_gps_start"])
        key = (source, catalog)
        if key in identities:
            raise InputCoverageError("duplicate calibration identity")
        identities.add(key)
        used_sources.add(source)
        sessions.add((detector, session))
        start = _number(row["analysis_gps_start"])
        interval = row["required_padded_interval"]
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise InputCoverageError("calibration context interval is malformed")
        begin, end = map(_number, interval)
        if begin != start - left or end != start + duration + right:
            raise InputCoverageError("calibration geometry mismatch")
        complete = any(a <= begin and b >= end for a, b in components[detector][1])
        if not isinstance(row["historical_context_disposition"], str):
            raise InputCoverageError("calibration dispositions must be explicit")
        kind = "not_complete_in_frozen_local_manifest"
        if complete:
            kind = (
                "complete_single_file"
                if any(a <= begin and b >= end for a, b in single_spans[detector])
                else "complete_only_by_stitch"
            )
        if not complete:
            missing.add((detector, begin, end))
        coverage[detector + "/" + kind] += 1
        contexts[detector + "/" + row["historical_context_disposition"]] += 1
        counts[detector] += 1
    expected_count = _select(payload, binding.identity_count)
    session_counts = Counter(d for d, _ in sessions)
    if (
        type(expected_count) is not int
        or len(identities) != expected_count
        or used_sources != source_paths
        or dict(coverage) != _select(payload, binding.expected_coverage)
        or dict(contexts) != _select(payload, binding.expected_contexts)
        or dict(session_counts) != _select(payload, binding.expected_sessions)
    ):
        raise InputCoverageError("calibration frozen population/distribution mismatch")
    supplement = None
    if acquisition_manifest is not None:
        supplement = _supplement(
            acquisition_manifest, acquisition_sha256, missing, contract, sample_rate
        )
    if (
        inspect_input_binding(spec, adapter, root=root) != inputs
        or _inventory(root, payload, binding) != inventory
        or _references(root, payload, binding) != references
    ):
        raise InputCoverageError("calibration inputs changed during inspection")
    if (
        supplement is not None
        and _supplement(
            acquisition_manifest, acquisition_sha256, missing, contract, sample_rate
        )
        != supplement
    ):
        raise InputCoverageError("acquired inputs changed during inspection")
    return {
        **report,
        "status": "PASS_CALIBRATION_DECLARED_INPUTS_ONLY"
        if not missing or supplement
        else "BLOCKED_CALIBRATION_SUPPLEMENT_REQUIRED",
        "blockers": []
        if not missing or supplement
        else ["PINNED_ACQUISITION_RECEIPT_REQUIRED"],
        "input_contract": contract,
        "identity_count": len(identities),
        "counts": dict(counts),
        "source_count": len(inventory),
        "source_inventory_digest": _select(payload, binding.inventory_digest),
        "missing_manifest_intervals": len(missing),
        "acquisition_receipt": supplement,
        "calibration_declared_input_coverage_checked": not missing
        or supplement is not None,
    }
