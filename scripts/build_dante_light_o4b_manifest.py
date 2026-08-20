#!/usr/bin/env python3
"""Freeze an outcome-blind O4b CAT1 shadow-evaluation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import (  # noqa: E402
    RepresentationContract,
    WindowIdentity,
    canonical_json_sha256,
)


O4B_START_GPS = 1396796418
O4B_END_GPS = 1422118818
WINDOW_S = 32
WHITENING_PAD_S = 4
WINDOWS_PER_DETECTOR_BLOCK = 128
DETECTORS = ("H1", "L1")

# The first candidate block (days 30--32) was consumed by the v1 infrastructure
# preflight and is therefore excluded in full from the v2 held-out evaluation.
TUNING_INTERVAL = (O4B_START_GPS + 30 * 86400, O4B_START_GPS + 32 * 86400)
EVALUATION_BLOCKS = (
    (O4B_START_GPS + 90 * 86400, O4B_START_GPS + 92 * 86400),
    (O4B_START_GPS + 150 * 86400, O4B_START_GPS + 152 * 86400),
    (O4B_START_GPS + 210 * 86400, O4B_START_GPS + 212 * 86400),
)

DEFAULT_SNAPSHOT = ROOT / "config" / "dante_light_o4b_cat1_segments_v1.json"
DEFAULT_OUTPUT = ROOT / "config" / "dante_light_o4b_shadow_v2.json"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def encoded_json(payload: Any, *, compact: bool = False) -> bytes:
    if compact:
        text = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    else:
        text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
    return (text + "\n").encode("utf-8")


def fetch_dq_snapshot() -> dict[str, Any]:
    """Fetch only public DQ metadata; no strain or DANTE outcome is read."""
    from gwosc.timeline import get_segments

    query_start = min(start for start, _ in EVALUATION_BLOCKS)
    query_end = max(end for _, end in EVALUATION_BLOCKS)
    segments: dict[str, list[list[float]]] = {}
    for detector in DETECTORS:
        flag = f"{detector}_CBC_CAT1"
        values = get_segments(flag, query_start, query_end)
        segments[detector] = [
            [float(left), float(right)] for left, right in values
        ]
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "frozen_dq_only",
        "run": "O4B",
        "official_run_bounds_gps": [O4B_START_GPS, O4B_END_GPS],
        "source": {
            "provider": "GWOSC",
            "flags": {detector: f"{detector}_CBC_CAT1" for detector in DETECTORS},
            "release_url": "https://gwosc.org/O4/O4b/",
            "outcome_data_accessed": False,
        },
        "query_bounds_gps": [query_start, query_end],
        "segments": segments,
    }
    payload["snapshot_sha256"] = canonical_json_sha256(payload)
    return payload


def select_windows(
    segments: list[list[float]],
    block_start: int,
    block_end: int,
    *,
    count: int = WINDOWS_PER_DETECTOR_BLOCK,
) -> list[int]:
    """Select the first aligned windows whose whitening context is CAT1."""
    selected: list[int] = []
    for raw_left, raw_right in sorted(segments):
        left = max(float(raw_left), float(block_start)) + WHITENING_PAD_S
        right = min(float(raw_right), float(block_end)) - WHITENING_PAD_S
        current = int(math.ceil(left / WINDOW_S) * WINDOW_S)
        while current + WINDOW_S <= right:
            selected.append(current)
            if len(selected) == count:
                return selected
            current += WINDOW_S
    raise RuntimeError(
        f"CAT1 block [{block_start}, {block_end}] provides only "
        f"{len(selected)}/{count} padded windows"
    )


def build(
    snapshot_path: Path = DEFAULT_SNAPSHOT,
    output_path: Path = DEFAULT_OUTPUT,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    recorded_hash = snapshot.pop("snapshot_sha256", None)
    if recorded_hash != canonical_json_sha256(snapshot):
        raise RuntimeError("O4b CAT1 snapshot digest mismatch")
    if snapshot.get("status") != "frozen_dq_only":
        raise RuntimeError("O4b CAT1 snapshot is not frozen")
    if snapshot.get("source", {}).get("outcome_data_accessed") is not False:
        raise RuntimeError("O4b selection is not outcome-blind")

    entries: list[dict[str, Any]] = []
    block_counts: dict[str, dict[str, int]] = {}
    for block_index, (block_start, block_end) in enumerate(EVALUATION_BLOCKS, 1):
        block_name = f"block_{block_index}"
        block_counts[block_name] = {}
        for detector in DETECTORS:
            starts = select_windows(
                snapshot["segments"][detector],
                block_start,
                block_end,
                count=WINDOWS_PER_DETECTOR_BLOCK,
            )
            block_counts[block_name][detector] = len(starts)
            for gps_start in starts:
                window = WindowIdentity("O4B", detector, gps_start, WINDOW_S)
                value: dict[str, Any] = {
                    "window": window.to_dict(),
                    "roles": ["o4b_shadow_evaluation", f"o4b_{block_name}"],
                    "source_kind": "public_strain",
                    "expected": {},
                    "metadata": {
                        "selection_basis": "GWOSC CBC_CAT1 only",
                        "block_index": block_index,
                        "block_bounds_gps": [block_start, block_end],
                        "whitening_context_cat1": True,
                    },
                }
                value["case_id"] = f"dlc1-{canonical_json_sha256(value)[:24]}"
                entries.append(value)
    entries.sort(key=lambda item: item["case_id"])
    if any(entry["expected"] for entry in entries):
        raise RuntimeError("O4b evaluation manifest contains outcome fields")

    entries_path = output_path.with_suffix(".jsonl")
    entries_bytes = b"".join(encoded_json(entry, compact=True) for entry in entries)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "locked_before_scoring",
        "purpose": "DANTE-Light temporally held-out O4b shadow evaluation",
        "run": "O4B",
        "official_run_bounds_gps": [O4B_START_GPS, O4B_END_GPS],
        "raw_strain_embedded": False,
        "outcome_fields_used_for_selection": [],
        "representation": RepresentationContract.from_reference_manifest(
            ROOT / "config" / "reference_artifacts.json"
        ).to_dict(),
        "selection_contract": {
            "detectors": list(DETECTORS),
            "dq_flags": [f"{detector}_CBC_CAT1" for detector in DETECTORS],
            "window_s": WINDOW_S,
            "whitening_pad_s": WHITENING_PAD_S,
            "rule": "first 128 aligned padded-CAT1 windows per detector and fixed block",
            "tuning_interval_gps": list(TUNING_INTERVAL),
            "evaluation_blocks_gps": [list(block) for block in EVALUATION_BLOCKS],
        },
        "dq_snapshot": {
            "path": snapshot_path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(snapshot_path),
            "snapshot_sha256": recorded_hash,
        },
        "counts": {
            "entries": len(entries),
            "unique_windows": len(
                {entry["window"]["window_id"] for entry in entries}
            ),
            "by_block_and_detector": block_counts,
        },
        "entries_path": entries_path.relative_to(ROOT).as_posix(),
        "entries_file_sha256": sha256_bytes(entries_bytes),
        "entries_sha256": canonical_json_sha256(entries),
    }
    payload["manifest_sha256"] = canonical_json_sha256(payload)
    return payload, entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh-dq", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    snapshot_path = args.snapshot.resolve()
    output_path = args.output.resolve()
    if args.refresh_dq:
        if snapshot_path.exists() and not args.check:
            raise RuntimeError(
                f"refusing to overwrite frozen DQ snapshot: {snapshot_path}"
            )
        snapshot = fetch_dq_snapshot()
        if not args.check:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            snapshot_path.write_bytes(encoded_json(snapshot))
    payload, entries = build(snapshot_path, output_path)
    entries_path = output_path.with_suffix(".jsonl")
    payload_bytes = encoded_json(payload)
    entries_bytes = b"".join(encoded_json(entry, compact=True) for entry in entries)
    if args.check:
        if (
            not output_path.is_file()
            or output_path.read_bytes() != payload_bytes
            or not entries_path.is_file()
            or entries_path.read_bytes() != entries_bytes
        ):
            raise RuntimeError("stale O4b shadow manifest")
        print(f"PASS {output_path} {payload['manifest_sha256']}")
        return 0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload_bytes)
    entries_path.write_bytes(entries_bytes)
    print(json.dumps(payload["counts"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
