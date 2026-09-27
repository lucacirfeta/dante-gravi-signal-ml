"""Read-only external-data gates for the paired diagnostic PEM comparison."""

from __future__ import annotations

import re
import json
from bisect import bisect_right
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.dante_light.contracts import ContractError
from src.dante_light.contracts import canonical_json_sha256
from src.core.index_contract import sha256_file
from src.dante_light.o3a_native_contract import ROOT, load_dq_snapshot


_MANIFEST_ROW = re.compile(
    r"(?P<md5>[0-9a-f]{32})\s+(?P<detector>[HLV]1)/(?P<epoch>\d+)/"
    r"(?P<name>[HLV]-[HLV]1_GWOSC_[A-Za-z0-9_]+-\d+-\d+\.hdf5)"
)


def load_background_source_contract(*, root: Path = ROOT) -> dict[str, Any]:
    """Validate the frozen public source and parent identities before fetching."""
    from src.dante_light.o3a_o4a_common_pem_contract import load_contract
    from src.dante_light.o3a_raw_acquisition import (
        _inventory_frames,
        load_source_inventory,
    )
    from src.dante_light.o4a_pem_raw_replay import load_contract as load_raw_contract

    path = root / "config/dante_o3a_o4a_common_pem_background_v1.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    digest = contract.pop("contract_digest", None)
    if digest != canonical_json_sha256(contract):
        raise ContractError("common PEM background source contract digest changed")
    contract["contract_digest"] = digest
    if (
        contract["schema_version"] != 1
        or contract["status"] != "FROZEN_PUBLIC_SOURCE_PREFLIGHT_NO_PAIRED_MEASUREMENT"
        or contract["boundary"]
        != {
            "paired_outcomes_opened": False,
            "background_frames_acquired_for_this_stage": False,
            "diagnostic_only": True,
            "published_md5_required_each_frame": True,
            "independent_numerical_span_replay_required": True,
        }
    ):
        raise ContractError("common PEM background source boundary changed")
    if (
        contract["common_input"]["path"] != "config/dante_o3a_o4a_common_pem_v1.json"
        or contract["source_parents"]["O3a"]["path"]
        != "config/dante_o3a_gwosc_4khz_source_inventory_v1.json"
        or contract["source_parents"]["O4a"]["path"]
        != "config/dante_o3a_o4a_pem_raw_replay_v2.json"
    ):
        raise ContractError("common PEM background source parent path changed")
    for reference in (
        contract["common_input"],
        *contract["source_parents"].values(),
    ):
        parent = (root / reference["path"]).resolve()
        if (
            not parent.is_relative_to(root.resolve())
            or sha256_file(parent) != reference["sha256"]
        ):
            raise ContractError("common PEM background source parent changed")
    load_contract(root=root)
    o3a_inventory = load_source_inventory(root=root)
    o4a_raw = load_raw_contract(root=root)["source"]
    durations = {
        int(frame["gps_end"]) - int(frame["gps_start"])
        for detector in ("H1", "L1")
        for frame in _inventory_frames(o3a_inventory, detector)
    }
    if len(durations) != 1:
        raise ContractError("common PEM O3a source frame duration is not unique")
    for run in ("O3a", "O4a"):
        source = contract["sources"][run]
        release = source["release"]
        if (
            release != f"{run}_4KHZ_R1"
            or source["manifest_url"]
            != f"https://gwosc.org/archive/md5/{release}/strain-hdf.txt"
            or source["archive_url_prefix"]
            != f"https://gwosc.org/archive/data/{release}/"
            or re.fullmatch(r"[0-9a-f]{64}", source["manifest_sha256"]) is None
            or source["required_unique_frames_preflight"] <= 0
            or source["historical_span_selection_replayed"] <= 0
        ):
            raise ContractError("common PEM background public source changed")
    if (
        contract["sources"]["O3a"]["frame_duration_s"] not in durations
        or contract["sources"]["O3a"]["sample_rate_hz"]
        != o3a_inventory["source_query"]["sample_rate_hz"]
    ):
        raise ContractError("common PEM O3a source inventory mismatch")
    o4a = contract["sources"]["O4a"]
    if (
        o4a["frame_duration_s"] != o4a_raw["frame_duration_s"]
        or o4a["sample_rate_hz"] != o4a_raw["sample_rate_hz"]
        or o4a["metadata"]
        != {
            detector: {
                "FrameType": o4a_raw["frame_type"][detector],
                "StrainChannel": o4a_raw["strain_channel"][detector],
            }
            for detector in ("H1", "L1")
        }
    ):
        raise ContractError("common PEM O4a source parent mismatch")
    return contract


def parse_official_frame_manifest(
    data: bytes, *, release: str, frame_duration_s: int
) -> dict[tuple[str, int], dict[str, Any]]:
    """Validate the public MD5 list for one frozen GWOSC 4 kHz release."""
    if release not in ("O3a_4KHZ_R1", "O4a_4KHZ_R1") or frame_duration_s <= 0:
        raise ContractError("common PEM background release/geometry is invalid")
    frames: dict[tuple[str, int], dict[str, Any]] = {}
    try:
        lines = data.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ContractError("common PEM background manifest is not ASCII") from exc
    for line in lines:
        match = _MANIFEST_ROW.fullmatch(line.strip())
        if match is None:
            raise ContractError("common PEM background manifest row is invalid")
        detector = match.group("detector")
        filename = match.group("name")
        prefix = f"{detector[0]}-{detector}_GWOSC_{release}-"
        suffix = f"-{frame_duration_s}.hdf5"
        if not filename.startswith(prefix) or not filename.endswith(suffix):
            raise ContractError("common PEM background frame release is invalid")
        if detector == "V1":
            # O3a's published checksum list also contains Virgo; the paired
            # PEM comparison remains H1/L1 only.
            continue
        start = int(filename[len(prefix) : -len(suffix)])
        key = detector, start
        if key in frames:
            raise ContractError("common PEM background frame is duplicated")
        frames[key] = {
            "detector": detector,
            "gps_start": start,
            "filename": filename,
            "relative_path": f"{detector}/{match.group('epoch')}/{filename}",
            "md5": match.group("md5"),
        }
    if not frames:
        raise ContractError("common PEM background manifest is empty")
    return frames


def plan_background_frames(
    *,
    detector: str,
    start: int,
    end: int,
    manifest: Mapping[tuple[str, int], Mapping[str, Any]],
    frame_duration_s: int,
) -> list[dict[str, Any]]:
    """Find gap-free official-frame coverage without reading strain or outcomes."""
    if detector not in ("H1", "L1") or start >= end or frame_duration_s <= 0:
        raise ContractError("common PEM background span is invalid")
    starts = sorted(gps for ifo, gps in manifest if ifo == detector)
    cursor = start
    pieces: list[dict[str, Any]] = []
    while cursor < end:
        index = bisect_right(starts, cursor) - 1
        if index < 0 or cursor >= starts[index] + frame_duration_s:
            raise ContractError("common PEM official background frames have a gap")
        frame = manifest[detector, starts[index]]
        right = min(end, starts[index] + frame_duration_s)
        pieces.append({**frame, "used_interval_gps": [cursor, right]})
        cursor = right
    return pieces


def verify_o3a_cat1_equivalence(*, root: Path = ROOT) -> dict[str, Any]:
    """Recheck that the PEM core's BURST_CAT1 equals frozen O3a CBC_CAT1."""
    from gwosc.timeline import get_segments

    snapshot = load_dq_snapshot(root=root)
    start, end = (int(value) for value in snapshot["query_bounds_gps"])
    report: dict[str, Any] = {"status": "PASS_CAT1_EQUIVALENCE", "detectors": {}}
    for detector in snapshot["detectors"]:
        expected = snapshot["segments"][detector]
        fetched: dict[str, list[list[int]]] = {}
        for category in ("CBC", "BURST"):
            flag = f"{detector}_{category}_CAT1"
            fetched[category] = [
                [int(left), int(right)]
                for left, right in get_segments(flag, start, end)
            ]
        if fetched["CBC"] != expected or fetched["BURST"] != expected:
            raise ContractError(
                f"{detector} public CBC/BURST CAT1 differs from frozen O3a DQ"
            )
        report["detectors"][detector] = {
            "segment_count": len(expected),
            "livetime_s": sum(right - left for left, right in expected),
        }
    return report
