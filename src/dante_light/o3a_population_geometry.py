"""Frozen outcome-blind O3a window universes.

This module converts the public CBC_CAT1 segment snapshot into compact,
lossless aligned ranges. It defines which identities may later be evaluated;
it deliberately does not choose the 5,000 calibration members, inspect raw
quality, score windows, or construct candidates.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_native_contract import ROOT, load_dq_snapshot
from src.dante_light.o3a_scale_adequacy import load_stage_contract


MANIFEST_REL = "config/dante_o3a_native_v1_identity_universes.json"
IMPLEMENTATION_REL = "src/dante_light/o3a_population_geometry.py"
ENTRYPOINT_REL = "scripts/freeze_dante_o3a_identity_universes.py"
SCHEMA_VERSION = 1


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _aligned_range(
    segment: Iterable[int],
    *,
    stride_s: int,
    duration_s: int,
    pad_s: int,
) -> tuple[int, int, int] | None:
    raw_left, raw_right = segment
    left = int(raw_left) + pad_s
    right = int(raw_right) - duration_s - pad_s
    first = ((left + stride_s - 1) // stride_s) * stride_s
    if first > right:
        return None
    count = ((right - first) // stride_s) + 1
    return first, first + (count - 1) * stride_s, count


def _ranges(
    segments: Iterable[Iterable[int]],
    *,
    stride_s: int,
    duration_s: int,
    pad_s: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(segments):
        raw_left, raw_right = (int(value) for value in segment)
        aligned = _aligned_range(
            (raw_left, raw_right),
            stride_s=stride_s,
            duration_s=duration_s,
            pad_s=pad_s,
        )
        if aligned is None:
            continue
        first, last, count = aligned
        result.append(
            {
                "dq_segment_index": segment_index,
                "dq_interval_gps": [raw_left, raw_right],
                "first_gps_start": first,
                "last_gps_start": last,
                "count": count,
            }
        )
    return result


def iter_role_identities(
    value: Mapping[str, Any], role: str
) -> Iterator[tuple[str, int]]:
    role_value = value["roles"][role]
    stride = int(role_value["stride_s"])
    for detector in value["detectors"]:
        for item in role_value["ranges_by_detector"][detector]:
            first = int(item["first_gps_start"])
            count = int(item["count"])
            for offset in range(count):
                yield detector, first + offset * stride


def _identity_stream_digest(
    *,
    run: str,
    duration_s: int,
    detectors: Iterable[str],
    ranges_by_detector: Mapping[str, Iterable[Mapping[str, Any]]],
    stride_s: int,
) -> str:
    digest = hashlib.sha256()
    for detector in detectors:
        for item in ranges_by_detector[detector]:
            first = int(item["first_gps_start"])
            count = int(item["count"])
            for offset in range(count):
                gps = first + offset * stride_s
                digest.update(
                    f"{run}|{detector}|{gps}|{duration_s}\n".encode("ascii")
                )
    return digest.hexdigest()


def build_identity_universes(*, root: Path = ROOT) -> dict[str, Any]:
    stage = load_stage_contract(root=root)
    dq = load_dq_snapshot(root=root)
    initial = stage["author_decisions"]["initial_calibration_and_scan"]
    if (
        initial["full_scan_grid"]
        != "GPS_MULTIPLE_OF_32_WITHIN_CBC_CAT1_AND_COMPLETE_CONTEXT"
    ):
        raise ContractError("O3a full-scan grid contract changed")
    duration = int(initial["analysis_duration_s"])
    pad = int(initial["whitening_pad_s"])
    detectors = list(initial["detectors"])
    role_specs = {
        "primary_scan_geometric_universe": duration,
        "initial_calibration_proposal_universe": int(initial["window_stride_s"]),
    }
    roles: dict[str, dict[str, Any]] = {}
    for role, stride in role_specs.items():
        ranges_by_detector = {
            detector: _ranges(
                dq["segments"][detector],
                stride_s=stride,
                duration_s=duration,
                pad_s=pad,
            )
            for detector in detectors
        }
        counts = {
            detector: sum(item["count"] for item in ranges_by_detector[detector])
            for detector in detectors
        }
        roles[role] = {
            "stride_s": stride,
            "duration_s": duration,
            "whitening_pad_s": pad,
            "complete_symmetric_context_required": True,
            "counts_by_detector": counts,
            "total_count": sum(counts.values()),
            "ranges_by_detector": ranges_by_detector,
            "ordered_identity_stream_encoding": (
                "ASCII run|detector|integer_gps_start|duration_s followed by LF; "
                "detector order from manifest and ascending range/start order"
            ),
            "ordered_identity_stream_sha256": _identity_stream_digest(
                run="O3A",
                duration_s=duration,
                detectors=detectors,
                ranges_by_detector=ranges_by_detector,
                stride_s=stride,
            ),
        }

    expected = {
        "primary_scan_geometric_universe": {"H1": 349_925, "L1": 372_986},
        "initial_calibration_proposal_universe": {
            "H1": 174_967,
            "L1": 186_491,
        },
    }
    if any(
        roles[role]["counts_by_detector"] != counts
        for role, counts in expected.items()
    ):
        raise ContractError("O3a identity-universe counts changed")
    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_OUTCOME_BLIND_IDENTITY_UNIVERSES",
        "run": "O3A",
        "detectors": detectors,
        "strain_data_accessed": False,
        "outcome_data_accessed": False,
        "approved_stage_contract": {
            "path": "config/dante_o3a_native_v1_stage_contract.json",
            "sha256": _sha256_file(
                root / "config/dante_o3a_native_v1_stage_contract.json"
            ),
            "contract_digest": stage["contract_digest"],
        },
        "dq_snapshot_digest": dq["snapshot_digest"],
        "implementation": {
            "path": IMPLEMENTATION_REL,
            "sha256": _sha256_file(root / IMPLEMENTATION_REL),
            "entrypoint_path": ENTRYPOINT_REL,
            "entrypoint_sha256": _sha256_file(root / ENTRYPOINT_REL),
        },
        "roles": roles,
        "selection_boundary": {
            "initial_calibration_members_selected": False,
            "raw_quality_evaluated": False,
            "candidate_outcomes_read": False,
            "native_index_or_native_calibration_members_selected": False,
            "next_required_contract": (
                "exact outcome-blind calibration selection and raw-quality "
                "acceptance rule"
            ),
        },
    }
    return {**body, "manifest_digest": canonical_json_sha256(body)}


def validate_identity_universes(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    expected = build_identity_universes(root=root)
    if dict(value) != expected:
        raise ContractError("O3a identity-universe manifest mismatch")
    if value.get("status") != "FROZEN_OUTCOME_BLIND_IDENTITY_UNIVERSES":
        raise ContractError("O3a identity-universe status mismatch")
    return dict(value)


def load_identity_universes(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / MANIFEST_REL
    if not path.is_file():
        raise ContractError("O3a identity-universe manifest is absent")
    return validate_identity_universes(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def write_identity_universes(*, root: Path = ROOT) -> dict[str, Any]:
    value = build_identity_universes(root=root)
    _write_json(root / MANIFEST_REL, value)
    return value


__all__ = [
    "MANIFEST_REL",
    "build_identity_universes",
    "iter_role_identities",
    "load_identity_universes",
    "validate_identity_universes",
    "write_identity_universes",
]
