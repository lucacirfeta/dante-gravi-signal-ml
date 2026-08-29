"""Sample-level audit of non-identical raw spans that overlap in O4a."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.o4a_corrected_protocol import RAW_MANIFEST_REL, ROOT
from src.dante_light.prefilter_v5_protocol import repository_reference, sha256_path


OUTPUT_REL = "artifacts/dante_light/o4a_v1_parity/overlapping_raw_span_audit.json"
IMPLEMENTATION_REL = "src/dante_light/o4a_overlap_audit.py"


def _rows(root: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (root / RAW_MANIFEST_REL).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _overlap_pairs(root: Path) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    pairs = []
    rows = _rows(root)
    for detector in ("H1", "L1"):
        subset = sorted(
            (row for row in rows if row["detector"] == detector),
            key=lambda row: (float(row["gps_start"]), float(row["gps_end"])),
        )
        for index, left in enumerate(subset):
            for right in subset[index + 1 :]:
                if float(right["gps_start"]) >= float(left["gps_end"]):
                    break
                if (
                    float(left["gps_start"]) < float(right["gps_end"])
                    and float(right["gps_start"]) < float(left["gps_end"])
                ):
                    pairs.append((left, right))
    counts = Counter(left["detector"] for left, _ in pairs)
    if counts != {"H1": 1, "L1": 5}:
        raise ContractError("corrected O4a overlapping-span pair count changed")
    return pairs


def _source(root: Path, raw_root: Path, row: Mapping[str, Any]) -> Path:
    copies = sorted(row["physical_copies"], key=lambda item: item["relative_path"])
    available = [raw_root / str(copy["relative_path"]) for copy in copies]
    available = [path.resolve() for path in available if path.is_file()]
    if not available:
        raise ContractError("overlapping raw span has no available physical copy")
    path = available[0]
    if sha256_path(path) != row["sha256"]:
        raise ContractError(f"overlapping raw span hash mismatch: {path}")
    return path


def build_overlap_audit(
    *, root: Path = ROOT, raw_root: Path = Path("E:/o4a")
) -> dict[str, Any]:
    from gwpy.timeseries import TimeSeries

    root = root.resolve()
    raw_root = raw_root.resolve()
    records = []
    duplicate_windows = Counter()
    for left, right in _overlap_pairs(root):
        detector = str(left["detector"])
        start = max(float(left["gps_start"]), float(right["gps_start"]))
        end = min(float(left["gps_end"]), float(right["gps_end"]))
        left_path = _source(root, raw_root, left)
        right_path = _source(root, raw_root, right)
        left_series = TimeSeries.read(left_path).crop(start, end)
        right_series = TimeSeries.read(right_path).crop(start, end)
        if int(round(float(left_series.sample_rate.value))) != 4096:
            left_series = left_series.resample(4096)
        if int(round(float(right_series.sample_rate.value))) != 4096:
            right_series = right_series.resample(4096)
        left_values = np.ascontiguousarray(left_series.value)
        right_values = np.ascontiguousarray(right_series.value)
        expected_samples = int(round((end - start) * 4096))
        if left_values.shape != (expected_samples,) or right_values.shape != (expected_samples,):
            raise ContractError("overlapping raw span crop is incomplete")
        exact = bool(np.array_equal(left_values, right_values, equal_nan=True))
        finite = bool(np.isfinite(left_values).all() and np.isfinite(right_values).all())
        max_delta = float(np.max(np.abs(left_values - right_values))) if finite else None
        duplicate_windows[detector] += int((end - start) // 32)
        records.append(
            {
                "detector": detector,
                "overlap_interval": [start, end],
                "overlap_duration_s": end - start,
                "overlap_32s_window_memberships": int((end - start) // 32),
                "left": {
                    "interval": [float(left["gps_start"]), float(left["gps_end"])],
                    "file_sha256": left["sha256"],
                    "strain_overlap_sha256": hashlib.sha256(left_values.tobytes()).hexdigest(),
                },
                "right": {
                    "interval": [float(right["gps_start"]), float(right["gps_end"])],
                    "file_sha256": right["sha256"],
                    "strain_overlap_sha256": hashlib.sha256(right_values.tobytes()).hexdigest(),
                },
                "sample_count": expected_samples,
                "all_finite": finite,
                "sample_exact_equal": exact,
                "max_abs_sample_delta": max_delta,
            }
        )
    if duplicate_windows != {"H1": 72, "L1": 328}:
        raise ContractError("overlapping raw duplicate-window count changed")
    if not all(row["all_finite"] and row["sample_exact_equal"] for row in records):
        raise ContractError("overlapping raw spans are not sample-identical")
    body = {
        "schema_version": 1,
        "status": "PASS_SAMPLE_EXACT_OVERLAPS",
        "raw_manifest_reference": repository_reference(root, root / RAW_MANIFEST_REL),
        "implementation_reference": repository_reference(root, root / IMPLEMENTATION_REL),
        "pair_count": len(records),
        "pair_counts": dict(Counter(row["detector"] for row in records)),
        "duplicate_window_memberships": dict(duplicate_windows),
        "records": records,
        "scientific_conclusion": (
            "Non-identical logical spans that overlap contain bit-identical strain "
            "over every shared sample; detector+GPS deduplication does not select "
            "between conflicting measurements."
        ),
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def validate_overlap_audit(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(value)
    digest = payload.pop("artifact_digest", None)
    if digest != canonical_json_sha256(payload):
        raise ContractError("overlapping raw span audit self-digest mismatch")
    if (
        payload.get("status") != "PASS_SAMPLE_EXACT_OVERLAPS"
        or payload.get("pair_counts") != {"H1": 1, "L1": 5}
        or payload.get("duplicate_window_memberships") != {"H1": 72, "L1": 328}
        or not all(
            row.get("all_finite") is True and row.get("sample_exact_equal") is True
            for row in payload.get("records", [])
        )
    ):
        raise ContractError("overlapping raw span audit did not pass")
    return dict(value)


def write_overlap_audit(
    *, root: Path = ROOT, raw_root: Path = Path("E:/o4a"), output: Path | None = None
) -> dict[str, Any]:
    value = build_overlap_audit(root=root, raw_root=raw_root)
    path = output or (root / OUTPUT_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return value

