"""Snapshot public segment metadata only; never fetch strain or run science."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
from urllib.request import urlopen


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save_json(path, payload):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def validate_request(request):
    if request["scope"] != "DRAFT_METADATA_ONLY_NOT_SCIENTIFIC_ADMISSION":
        raise ValueError("metadata-only scope required")
    if request["scientific_execution_ready"] is not False:
        raise ValueError("scientific execution is forbidden")
    if request["population_allocation"] is not None:
        raise ValueError("population allocation is not authorized")
    if request["whitening_context_geometry"] is not None:
        raise ValueError("context geometry is not qualified")
    start, end = request["gps_start"], request["gps_end"]
    if type(start) is not int or type(end) is not int or start >= end:
        raise ValueError("invalid integer GPS bounds")
    detectors = request["detectors"]
    if not detectors or len(set(detectors)) != len(detectors):
        raise ValueError("duplicate or empty detectors")
    if set(detectors) - {"H1", "L1", "V1"}:
        raise ValueError("unsupported draft detector")
    flags = request["dq_flags"] + request["no_hw_inj_flags"]
    if "DATA" not in request["dq_flags"] or not request["no_hw_inj_flags"]:
        raise ValueError("DATA and injection annotations required")
    if len(flags) != len(set(flags)) or any(
        not re.fullmatch(r"[A-Z0-9_]+", flag) for flag in flags
    ):
        raise ValueError("invalid or duplicate flag")
    if any(not flag.startswith("NO_") for flag in request["no_hw_inj_flags"]):
        raise ValueError("injection mask must use explicit NO flags")
    for name in ("workers", "timeout_s", "max_response_bytes"):
        if (
            type(request["transport"][name]) is not int
            or request["transport"][name] <= 0
        ):
            raise ValueError("invalid transport bound")
    check_url(request["dataset_metadata_url"])
    check_url(request["timeline_base_url"])


def check_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "gwosc.org" or parsed.query:
        raise ValueError("only official HTTPS metadata URLs allowed")
    if not (
        parsed.path.startswith("/timeline/segments/json/")
        or re.fullmatch(r"/archive/dataset/[A-Za-z0-9_]+/json/", parsed.path)
    ):
        raise ValueError("strain and non-metadata URLs are forbidden")


def fetch(url, transport):
    check_url(url)
    with urlopen(url, timeout=transport["timeout_s"]) as response:
        check_url(response.url)
        if response.status != 200:
            raise ValueError("metadata response must be HTTP200")
        raw = response.read(transport["max_response_bytes"] + 1)
    if len(raw) > transport["max_response_bytes"]:
        raise ValueError("metadata response too large")
    return raw


def parse_segments(payload, dataset, flag_id, start, end):
    if (
        payload.get("dataset") != dataset
        or payload.get("id") != flag_id
        or type(payload.get("start")) is not int
        or type(payload.get("end")) is not int
        or payload["start"] != start
        or payload["end"] != end
    ):
        raise ValueError("timeline query identity mismatch")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise ValueError("missing segment list")
    previous_end = start
    for row in segments:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError("invalid segment row")
        left, right = row
        if type(left) is not int or type(right) is not int:
            raise ValueError("integer endpoints required")
        if not start <= left < right <= end or left < previous_end:
            raise ValueError("out-of-range, unsorted or overlapping segment")
        previous_end = right
    return segments


def intersect(first, second):
    """Half-open integer segment intersection, without window selection."""
    result = []
    i = j = 0
    while i < len(first) and j < len(second):
        a, b = first[i]
        c, d = second[j]
        if max(a, c) < min(b, d):
            result.append([max(a, c), min(b, d)])
        if b <= d:
            i += 1
        else:
            j += 1
    return result


def subtract(first, second):
    """Return first minus second; preserve unknown/no-mask-pass interpretation."""
    result = []
    j = 0
    for left, right in first:
        cursor = left
        while j < len(second) and second[j][1] <= left:
            j += 1
        k = j
        while k < len(second) and second[k][0] < right:
            c, d = second[k]
            if c > cursor:
                result.append([cursor, min(c, right)])
            cursor = max(cursor, d)
            k += 1
        if cursor < right:
            result.append([cursor, right])
    return result


def seconds(segments):
    return sum(right - left for left, right in segments)


def snapshot(request_path, output):
    request_raw = request_path.read_bytes()
    request = json.loads(request_raw)
    validate_request(request)
    output.mkdir(parents=True, exist_ok=False)
    raw_dir = output / "raw_metadata"
    raw_dir.mkdir()
    with (output / "request.json").open("xb") as stream:
        stream.write(request_raw)
    transport = request["transport"]
    metadata_raw = fetch(request["dataset_metadata_url"], transport)
    with (raw_dir / "dataset.json").open("xb") as stream:
        stream.write(metadata_raw)
    metadata = json.loads(metadata_raw)
    if metadata.get("shortName") != request["dataset"]:
        raise ValueError("dataset identity mismatch")
    if metadata["npoints"] != request["sample_rate_hz"] * metadata["duration"]:
        raise ValueError("dataset sampling mismatch")
    published = {bit["shortName"]: bit["mask"] for bit in metadata["bits"]}
    for mask, key in ((0, "dq_flags"), (1, "no_hw_inj_flags")):
        if set(request[key]) != {
            name for name, value in published.items() if value == mask
        }:
            raise ValueError("published flag set changed; no silent omission")
    start, end = request["gps_start"], request["gps_end"]

    def obtain(item):
        detector, flag = item
        flag_id = f"{detector}_{flag}"
        url = f"{request['timeline_base_url']}{flag_id}/{start}/{end - start}/"
        raw = fetch(url, transport)
        with (raw_dir / f"{flag_id}.json").open("xb") as stream:
            stream.write(raw)
        segments = parse_segments(
            json.loads(raw), request["timeline_dataset"], flag_id, start, end
        )
        return flag_id, {"url": url, "sha256": digest(raw), "segments": segments}

    jobs = [
        (detector, flag)
        for detector in request["detectors"]
        for flag in request["dq_flags"] + request["no_hw_inj_flags"]
    ]
    with ThreadPoolExecutor(max_workers=transport["workers"]) as pool:
        timelines = dict(pool.map(obtain, jobs))
    candidates = {}
    for detector in request["detectors"]:
        available = timelines[f"{detector}_DATA"]["segments"]
        background = available
        for flag in request["no_hw_inj_flags"]:
            background = intersect(
                background, timelines[f"{detector}_{flag}"]["segments"]
            )
        flagged = subtract(available, background)
        if seconds(background) + seconds(flagged) != seconds(available):
            raise ValueError("metadata partition accounting mismatch")
        candidates[detector] = {
            "data_segments": available,
            "background_candidate_segments": background,
            "data_not_passing_all_no_hw_inj_masks": flagged,
            "data_seconds": seconds(available),
            "background_candidate_seconds": seconds(background),
            "not_passing_no_hw_inj_seconds": seconds(flagged),
            "dq_annotations": {
                flag: {
                    "data_passing_seconds": seconds(
                        intersect(
                            available, timelines[f"{detector}_{flag}"]["segments"]
                        )
                    ),
                    "used_as_veto": False,
                }
                for flag in request["dq_flags"]
                if flag != "DATA"
            },
        }
    result = {
        "scope": request["scope"],
        "scientific_execution_ready": False,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "request_sha256": digest(request_raw),
        "dataset_metadata_sha256": digest(metadata_raw),
        "dataset": request["dataset"],
        "gps_start": start,
        "gps_end": end,
        "timelines": timelines,
        "detectors": candidates,
        "population_allocation": None,
        "context_coverage_verified": False,
        "strain_files_inspected": 0,
        "known_injection_morphologies_verified": False,
        "note": "Unassigned metadata intervals, not windows/null/calibration. Non-passing NO masks are annotations, not verified injection events.",
    }
    save_json(output / "proposal.json", result)
    print(
        json.dumps(
            {
                det: {
                    key: value for key, value in row.items() if key.endswith("seconds")
                }
                for det, row in candidates.items()
            },
            sort_keys=True,
        )
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # On failure preserve partial files and traceback; never mutate an existing
    # destination merely because mkdir rejected it. No automatic retry/resume.
    snapshot(args.request, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
