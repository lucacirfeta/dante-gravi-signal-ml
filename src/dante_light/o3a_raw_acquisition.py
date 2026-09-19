"""Frozen O3a GWOSC source inventory and raw acquisition plan.

This module handles public file metadata only.  It does not download or open
strain files, and it does not execute raw acceptance or candidate fallback.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlparse

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o3a_initial_calibration import (
    CONTRACT_REL as SELECTOR_CONTRACT_REL,
    PLAN_REL as CALIBRATION_PLAN_REL,
    load_initial_calibration_plan,
    load_selector_contract,
)
from src.dante_light.o3a_native_contract import (
    DQ_SNAPSHOT_REL,
    ROOT,
    load_dq_snapshot,
)


INVENTORY_REL = "config/dante_o3a_gwosc_4khz_source_inventory_v1.json"
ACQUISITION_REL = (
    "config/dante_o3a_initial_calibration_raw_acquisition_v1.json"
)
IMPLEMENTATION_REL = "src/dante_light/o3a_raw_acquisition.py"
ENTRYPOINT_REL = "scripts/freeze_dante_o3a_raw_acquisition.py"
SCHEMA_VERSION = 1
DATASET = "O3a"
SAMPLE_RATE_HZ = 4096
FORMAT = "hdf5"
PAGESIZE = 5000
WINDOW_DURATION_S = 32
FRAME_DURATION_S = 4096
TARGET_WINDOWS_ROOT = r"E:\o3a"
TARGET_WINDOWS_ROOT_WSL = "/mnt/e/o3a"

_FRAME_RE = re.compile(
    r"^(?P<prefix>[HL])-(?P<detector>[HL]1)_GWOSC_O3a_4KHZ_R1-"
    r"(?P<gps_start>[0-9]+)-(?P<duration_s>[0-9]+)\.hdf5$"
)

UrlFetcher = Callable[[str, int, int], Iterable[str]]


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


def _parent_binding(path: Path, digest_name: str, digest: str) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": _sha256_file(path),
        digest_name: digest,
    }


def _source_binding(root: Path) -> dict[str, str]:
    return {
        "path": IMPLEMENTATION_REL,
        "sha256": _sha256_file(root / IMPLEMENTATION_REL),
        "entrypoint_path": ENTRYPOINT_REL,
        "entrypoint_sha256": _sha256_file(root / ENTRYPOINT_REL),
    }


def _frame_from_url(url: str, detector: str) -> dict[str, Any]:
    parsed = urlparse(str(url))
    trusted_host = parsed.netloc == "gwosc.org" or parsed.netloc.endswith(
        ".gwosc.org"
    )
    if parsed.scheme != "https" or not trusted_host:
        raise ContractError(f"untrusted O3a source URL: {url!r}")
    filename = Path(unquote(parsed.path)).name
    match = _FRAME_RE.fullmatch(filename)
    if match is None or match.group("detector") != detector:
        raise ContractError(f"invalid O3a {detector} frame URL: {url!r}")
    if match.group("prefix") != detector[0]:
        raise ContractError(f"O3a frame prefix mismatch: {url!r}")
    duration = int(match.group("duration_s"))
    if duration != FRAME_DURATION_S:
        raise ContractError(f"unexpected O3a frame duration: {url!r}")
    start = int(match.group("gps_start"))
    return {
        "filename": filename,
        "url": str(url),
        "gps_start": start,
        "gps_end": start + duration,
        "duration_s": duration,
    }


def normalize_source_urls(urls: Iterable[str], detector: str) -> list[dict[str, Any]]:
    frames = [_frame_from_url(url, detector) for url in urls]
    frames.sort(key=lambda item: (item["gps_start"], item["filename"], item["url"]))
    if not frames:
        raise ContractError(f"GWOSC returned no O3a {detector} frames")
    filenames = [str(item["filename"]) for item in frames]
    if len(set(filenames)) != len(filenames):
        raise ContractError(f"duplicate O3a {detector} frame filename")
    intervals = [
        (int(item["gps_start"]), int(item["gps_end"])) for item in frames
    ]
    if len(set(intervals)) != len(intervals):
        raise ContractError(f"duplicate O3a {detector} frame interval")
    return frames


def _frame_stream_sha256(detector: str, frames: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in frames:
        digest.update(
            (
                f"{detector}|{item['gps_start']}|{item['gps_end']}|"
                f"{item['filename']}|{item['url']}\n"
            ).encode("utf-8")
        )
    return digest.hexdigest()


def _default_url_fetcher(detector: str, start: int, end: int) -> Iterable[str]:
    from gwosc.locate import get_urls

    return get_urls(
        detector,
        start,
        end,
        dataset=DATASET,
        sample_rate=SAMPLE_RATE_HZ,
        format=FORMAT,
        pagesize=PAGESIZE,
    )


def build_source_inventory(
    *, root: Path = ROOT, url_fetcher: UrlFetcher | None = None
) -> dict[str, Any]:
    dq = load_dq_snapshot(root=root)
    fetcher = _default_url_fetcher if url_fetcher is None else url_fetcher
    urls_by_detector: dict[str, list[str]] = {}
    query_bounds: dict[str, list[int]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    for detector in dq["detectors"]:
        segments = dq["segments"][detector]
        start = int(segments[0][0])
        end = int(segments[-1][1])
        query_bounds[detector] = [start, end]
        frames = normalize_source_urls(fetcher(detector, start, end), detector)
        urls_by_detector[detector] = [str(item["url"]) for item in frames]
        summaries[detector] = {
            "frame_count": len(frames),
            "first_frame_gps_start": int(frames[0]["gps_start"]),
            "last_frame_gps_end": int(frames[-1]["gps_end"]),
            "frame_stream_sha256": _frame_stream_sha256(detector, frames),
        }

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_PUBLIC_O3A_GWOSC_4KHZ_SOURCE_INVENTORY",
        "run": "O3A",
        "detectors": list(dq["detectors"]),
        "dq_snapshot": _parent_binding(
            root / DQ_SNAPSHOT_REL,
            "snapshot_digest",
            str(dq["snapshot_digest"]),
        ),
        "implementation": _source_binding(root),
        "source_query": {
            "provider": "GWOSC",
            "api": "gwosc.locate.get_urls",
            "dataset": DATASET,
            "sample_rate_hz": SAMPLE_RATE_HZ,
            "format": FORMAT,
            "pagesize": PAGESIZE,
            "query_bounds_by_detector": query_bounds,
            "normalization": "gps_start_then_filename_then_url",
        },
        "summaries": summaries,
        "urls_by_detector": urls_by_detector,
        "execution_boundary": {
            "public_file_metadata_only": True,
            "downloaded_bytes": 0,
            "strain_data_accessed": False,
            "outcome_data_accessed": False,
        },
    }
    return {**body, "inventory_digest": canonical_json_sha256(body)}


def validate_source_inventory(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("inventory_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("O3a source inventory self-digest mismatch")
    dq = load_dq_snapshot(root=root)
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status")
        != "FROZEN_PUBLIC_O3A_GWOSC_4KHZ_SOURCE_INVENTORY"
        or value.get("run") != "O3A"
        or value.get("detectors") != list(dq["detectors"])
        or value.get("implementation") != _source_binding(root)
        or value.get("dq_snapshot")
        != _parent_binding(
            root / DQ_SNAPSHOT_REL,
            "snapshot_digest",
            str(dq["snapshot_digest"]),
        )
    ):
        raise ContractError("O3a source inventory binding mismatch")
    expected_query = {
        "provider": "GWOSC",
        "api": "gwosc.locate.get_urls",
        "dataset": DATASET,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "format": FORMAT,
        "pagesize": PAGESIZE,
        "query_bounds_by_detector": {
            detector: [
                int(dq["segments"][detector][0][0]),
                int(dq["segments"][detector][-1][1]),
            ]
            for detector in dq["detectors"]
        },
        "normalization": "gps_start_then_filename_then_url",
    }
    if value.get("source_query") != expected_query:
        raise ContractError("O3a source inventory query mismatch")
    summaries: dict[str, dict[str, Any]] = {}
    for detector in dq["detectors"]:
        stored = value.get("urls_by_detector", {}).get(detector, [])
        frames = normalize_source_urls([str(url) for url in stored], detector)
        canonical_urls = [str(item["url"]) for item in frames]
        if stored != canonical_urls:
            raise ContractError(f"O3a {detector} source URLs are not canonical")
        summaries[detector] = {
            "frame_count": len(frames),
            "first_frame_gps_start": int(frames[0]["gps_start"]),
            "last_frame_gps_end": int(frames[-1]["gps_end"]),
            "frame_stream_sha256": _frame_stream_sha256(detector, frames),
        }
    if value.get("summaries") != summaries:
        raise ContractError("O3a source inventory summary mismatch")
    if value.get("execution_boundary") != {
        "public_file_metadata_only": True,
        "downloaded_bytes": 0,
        "strain_data_accessed": False,
        "outcome_data_accessed": False,
    }:
        raise ContractError("O3a source inventory exceeded metadata boundary")
    return dict(value)


def load_source_inventory(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / INVENTORY_REL
    if not path.is_file():
        raise ContractError("O3a GWOSC source inventory is absent")
    return validate_source_inventory(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def _inventory_frames(
    inventory: Mapping[str, Any], detector: str
) -> list[dict[str, Any]]:
    return normalize_source_urls(
        [str(url) for url in inventory["urls_by_detector"][detector]], detector
    )


def _cover_interval(
    frames: Sequence[Mapping[str, Any]], start: int, end: int
) -> list[Mapping[str, Any]]:
    if end <= start:
        raise ContractError("raw coverage interval is empty")
    selected: list[Mapping[str, Any]] = []
    cursor = start
    candidates = [
        item
        for item in frames
        if int(item["gps_end"]) > start and int(item["gps_start"]) < end
    ]
    while cursor < end:
        eligible = [item for item in candidates if int(item["gps_start"]) <= cursor]
        if not eligible:
            raise ContractError(f"raw source coverage gap at GPS {cursor}")
        best = max(eligible, key=lambda item: int(item["gps_end"]))
        best_end = int(best["gps_end"])
        if best_end <= cursor:
            raise ContractError(f"raw source coverage does not advance at GPS {cursor}")
        if not selected or selected[-1]["filename"] != best["filename"]:
            selected.append(best)
        cursor = best_end
        candidates = [item for item in candidates if int(item["gps_end"]) > cursor]
    return selected


def build_acquisition_plan(*, root: Path = ROOT) -> dict[str, Any]:
    inventory = load_source_inventory(root=root)
    selector = load_selector_contract(root=root)
    calibration = load_initial_calibration_plan(root=root)
    pad = int(selector["selection"]["complete_symmetric_context_s"])
    duration = int(selector["selection"]["window_duration_s"])
    detector_plans: dict[str, dict[str, Any]] = {}
    total_frames: set[tuple[str, str]] = set()
    for detector in calibration["detectors"]:
        source_frames = _inventory_frames(inventory, detector)
        blocks: list[dict[str, Any]] = []
        required_filenames: set[str] = set()
        for block in calibration["detector_plans"][detector]["selected_blocks"]:
            interval_start = int(block["first_gps_start"]) - pad
            interval_end = int(block["last_gps_start"]) + duration + pad
            coverage = _cover_interval(source_frames, interval_start, interval_end)
            filenames = [str(item["filename"]) for item in coverage]
            required_filenames.update(filenames)
            blocks.append(
                {
                    "stratum_index": int(block["stratum_index"]),
                    "candidate_rank_in_stratum": int(
                        block["candidate_rank_in_stratum"]
                    ),
                    "first_gps_start": int(block["first_gps_start"]),
                    "last_gps_start": int(block["last_gps_start"]),
                    "candidate_block_row_count": int(
                        block["candidate_block_row_count"]
                    ),
                    "output_row_count": int(block["output_row_count"]),
                    "required_raw_interval_gps": [interval_start, interval_end],
                    "source_frame_filenames": filenames,
                }
            )
        by_filename = {
            str(item["filename"]): item for item in source_frames
        }
        selected_frames = []
        for filename in sorted(
            required_filenames,
            key=lambda name: (int(by_filename[name]["gps_start"]), name),
        ):
            item = by_filename[filename]
            selected_frames.append(
                {
                    **item,
                    "target_relative_path": f"{detector}/{filename}",
                    "content_sha256": None,
                    "content_length_bytes": None,
                    "download_status": "NOT_DOWNLOADED",
                }
            )
            total_frames.add((detector, filename))
        detector_plans[detector] = {
            "provisional_block_count": len(blocks),
            "required_source_frame_count": len(selected_frames),
            "blocks": blocks,
            "source_frames": selected_frames,
        }

    body = {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_O3A_INITIAL_CALIBRATION_RAW_ACQUISITION_PLAN",
        "run": "O3A",
        "detectors": list(calibration["detectors"]),
        "parents": {
            "selector_contract": _parent_binding(
                root / SELECTOR_CONTRACT_REL,
                "contract_digest",
                str(selector["contract_digest"]),
            ),
            "initial_calibration_plan": _parent_binding(
                root / CALIBRATION_PLAN_REL,
                "plan_digest",
                str(calibration["plan_digest"]),
            ),
            "source_inventory": _parent_binding(
                root / INVENTORY_REL,
                "inventory_digest",
                str(inventory["inventory_digest"]),
            ),
        },
        "implementation": _source_binding(root),
        "acquisition_scope": {
            "population": "PROVISIONAL_RANK_ZERO_INITIAL_CALIBRATION_BLOCKS_ONLY",
            "raw_acceptance_executed": False,
            "fallback_candidates_included": False,
            "fallback_rule_unchanged": selector["raw_acceptance"][
                "failure_fallback"
            ],
            "fallback_acquisition_requires_versioned_plan_extension": True,
            "complete_block_context_required": True,
            "window_duration_s": WINDOW_DURATION_S,
            "symmetric_whitening_context_s": pad,
        },
        "storage": {
            "windows_target_root": TARGET_WINDOWS_ROOT,
            "wsl_target_root": TARGET_WINDOWS_ROOT_WSL,
            "partial_download_suffix": ".part",
            "atomic_rename_required": True,
            "existing_file_reuse_requires_final_sha256_match": True,
        },
        "detector_plans": detector_plans,
        "summary": {
            "provisional_block_count": sum(
                int(value["provisional_block_count"])
                for value in detector_plans.values()
            ),
            "unique_source_frame_count": len(total_frames),
            "downloaded_bytes": 0,
        },
        "execution_boundary": {
            "download_authorized_by_this_freeze": False,
            "raw_files_opened": False,
            "strain_data_accessed": False,
            "raw_acceptance_executed": False,
            "scoring_executed": False,
            "outcome_data_accessed": False,
        },
    }
    return {**body, "acquisition_digest": canonical_json_sha256(body)}


def validate_acquisition_plan(
    value: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, Any]:
    expected = build_acquisition_plan(root=root)
    if dict(value) != expected:
        raise ContractError("O3a raw acquisition plan mismatch")
    return dict(value)


def load_acquisition_plan(*, root: Path = ROOT) -> dict[str, Any]:
    path = root / ACQUISITION_REL
    if not path.is_file():
        raise ContractError("O3a raw acquisition plan is absent")
    return validate_acquisition_plan(
        json.loads(path.read_text(encoding="utf-8")), root=root
    )


def write_raw_acquisition_freeze(
    *, root: Path = ROOT, url_fetcher: UrlFetcher | None = None
) -> dict[str, Any]:
    inventory = build_source_inventory(root=root, url_fetcher=url_fetcher)
    _write_json(root / INVENTORY_REL, inventory)
    acquisition = build_acquisition_plan(root=root)
    _write_json(root / ACQUISITION_REL, acquisition)
    return acquisition


__all__ = [
    "ACQUISITION_REL",
    "INVENTORY_REL",
    "build_acquisition_plan",
    "build_source_inventory",
    "load_acquisition_plan",
    "load_source_inventory",
    "normalize_source_urls",
    "validate_acquisition_plan",
    "validate_source_inventory",
    "write_raw_acquisition_freeze",
]
