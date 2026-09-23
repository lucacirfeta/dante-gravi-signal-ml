#!/usr/bin/env python3
"""Read-only GWOSC 16 kHz coverage audit for the frozen O3a CBC_CAT1 geometry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DQ_PATH = ROOT / "config/dante_o3a_cbc_cat1_segments_v1.json"
OLD_PATH = ROOT / "config/dante_o3a_gwosc_4khz_source_inventory_v1.json"
API = "https://gwosc.org/api/v2/datasets/O3a_16KHZ_R1/strain-files"
FRAME_RE = re.compile(
    r"^([HL])-([HL]1)_GWOSC_O3a_(4|16)KHZ_R1-(\d+)-(\d+)\.hdf5$"
)


def frame_interval(url: str, detector: str, rate_khz: int) -> tuple[int, int]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "gwosc.org":
        raise ValueError("unexpected GWOSC frame host")
    match = FRAME_RE.fullmatch(Path(parsed.path).name)
    if (
        match is None
        or match.group(1) != detector[0]
        or match.group(2) != detector
        or int(match.group(3)) != rate_khz
    ):
        raise ValueError("unexpected GWOSC frame name or sampling rate")
    start, duration = int(match.group(4)), int(match.group(5))
    if duration != 4096:
        raise ValueError("unexpected GWOSC frame duration")
    return start, start + duration


def uncovered_segments(
    segments: list[list[int]], frames: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Return CBC_CAT1 gaps, including partial gaps at segment boundaries."""
    frames = sorted(frames)
    gaps: list[tuple[int, int]] = []
    index = 0
    for begin, end in segments:
        cursor = begin
        while index < len(frames) and frames[index][1] <= cursor:
            index += 1
        next_index = index
        while cursor < end and next_index < len(frames):
            frame_start, frame_end = frames[next_index]
            if frame_start > cursor:
                gaps.append((cursor, min(frame_start, end)))
                cursor = min(frame_start, end)
            if frame_end > cursor and frame_start <= cursor:
                cursor = min(frame_end, end)
            next_index += 1
        if cursor < end:
            gaps.append((cursor, end))
    return gaps


def audit(
    pages: list[dict], dq: dict, historical: dict
) -> dict:
    if not pages or any(page["page_number"] != n for n, page in enumerate(pages, 1)):
        raise ValueError("missing or unordered GWOSC API page")
    expected = pages[0]["results_count"]
    if any(
        page["results_count"] != expected or page["num_pages"] != len(pages)
        for page in pages
    ):
        raise ValueError("GWOSC API pagination changed during audit")
    rows = [row for page in pages for row in page["results"]]
    if len(rows) != expected:
        raise ValueError("GWOSC API row count mismatch")
    if historical["source_query"]["sample_rate_hz"] != 4096:
        raise ValueError("historical inventory is not the frozen 4 kHz source")
    if historical["dq_snapshot"]["sha256"] != hashlib.sha256(DQ_PATH.read_bytes()).hexdigest():
        raise ValueError("frozen CBC_CAT1 snapshot hash mismatch")

    detectors = {}
    for detector in ("H1", "L1"):
        current = []
        for row in rows:
            if row["detector"] != detector:
                continue
            if row["sample_rate_kHz"] != 16:
                raise ValueError(f"{detector} API row is not 16 kHz")
            current.append(frame_interval(row["hdf5_url"], detector, 16))
        historical_intervals = [
            frame_interval(url, detector, 4)
            for url in historical["urls_by_detector"][detector]
        ]
        if len(current) != len(set(current)):
            raise ValueError(f"duplicate {detector} 16 kHz intervals")
        if len(historical_intervals) != len(set(historical_intervals)):
            raise ValueError(f"duplicate {detector} historical intervals")
        missing = set(historical_intervals) - set(current)
        extra = set(current) - set(historical_intervals)
        gaps = uncovered_segments(dq["segments"][detector], current)
        detectors[detector] = {
            "frame_count_16khz": len(current),
            "historical_4khz_frame_count": len(historical_intervals),
            "missing_historical_intervals": len(missing),
            "extra_16khz_intervals": len(extra),
            "cbc_cat1_segment_count": len(dq["segments"][detector]),
            "uncovered_cbc_cat1_intervals": len(gaps),
            "first_gap": list(gaps[0]) if gaps else None,
        }
    passed = all(
        result["missing_historical_intervals"] == 0
        and result["extra_16khz_intervals"] == 0
        and result["uncovered_cbc_cat1_intervals"] == 0
        for result in detectors.values()
    )
    return {
        "status": "PASS_METADATA_COVERAGE" if passed else "FAIL_METADATA_COVERAGE",
        "source": API,
        "api_row_count": len(rows),
        "api_page_count": len(pages),
        "strain_bytes_read": 0,
        "detectors": detectors,
    }


def main() -> int:
    pages = []
    page_number = 1
    while True:
        with urlopen(f"{API}?format=json&pagesize=500&page={page_number}", timeout=45) as response:
            page = json.load(response)
        pages.append(page)
        if page_number >= page["num_pages"]:
            break
        page_number += 1
    result = audit(
        pages,
        json.loads(DQ_PATH.read_text(encoding="utf-8")),
        json.loads(OLD_PATH.read_text(encoding="utf-8")),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS_METADATA_COVERAGE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
