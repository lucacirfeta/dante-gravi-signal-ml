"""Real-data validation of manifest-bound adjacent-file context stitching."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from gwpy.timeseries import TimeSeries

from src.core.patch_producer import load_frozen_raw_manifest, read_complete_context
from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.prefilter_v5_protocol import sha256_path


ROOT = Path(__file__).resolve().parents[2]
RAW_MANIFEST = ROOT / "artifacts/dante_light/prefilter_l4_v5_design/raw_file_manifest_v5.jsonl"
PARITY_MANIFEST = ROOT / "config/dante_light_o4a_v1_parity_manifest.json"
PARITY_CONTRACT = ROOT / "config/dante_light_o4a_v1_parity_contract.json"
PARITY_ENTRIES = ROOT / "config/dante_light_o4a_v1_parity_manifest.jsonl"
PARITY_MISSING = ROOT / "config/dante_light_o4a_v1_parity_missing.jsonl"
OUTPUT = ROOT / "artifacts/dante_light/o4a_v1_parity/context_stitch_validation.json"
DEFAULT_RAW_ROOT = Path("E:/o4a")
DEFAULT_CACHE_ROOT = Path("E:/dante_cache/dante_light/o4a_v1_comparison")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _array_sha256(value: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


def build_context_validation(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> dict[str, Any]:
    manifest_header = json.loads(PARITY_MANIFEST.read_text(encoding="utf-8"))
    parity_contract = json.loads(PARITY_CONTRACT.read_text(encoding="utf-8"))
    if (
        manifest_header.get("status") != "FROZEN_BEFORE_RESCORING"
        or manifest_header.get("entries_file_sha256") != sha256_path(PARITY_ENTRIES)
        or manifest_header.get("missing_file_sha256") != sha256_path(PARITY_MISSING)
    ):
        raise RuntimeError("frozen parity population provenance mismatch")
    missing = _load_jsonl(PARITY_MISSING)
    entries = {row["case_id"]: row for row in _load_jsonl(PARITY_ENTRIES)}
    selected_missing = next(
        row for row in missing if row["local_stitch"]["complete_padded_coverage"]
    )
    entry = entries[selected_missing["case_id"]]
    detector = str(entry["catalog_identity"]["detector"])
    analysis_start = float(entry["window"]["gps_start"])
    duration = float(entry["window"]["duration_s"])
    representation = parity_contract["representation"]
    pad = float(representation["whitening_pad_s"])
    request_start = analysis_start - pad
    request_end = analysis_start + duration + pad

    frozen = load_frozen_raw_manifest(
        RAW_MANIFEST, raw_root=raw_root, detector=detector
    )
    result = read_complete_context(
        frozen.entries,
        gps_start=request_start,
        gps_end=request_end,
        sample_rate_hz=int(representation["sample_rate_hz"]),
        expected_sha256=frozen.expected_sha256,
    )
    cached_path = (
        cache_root
        / "raw"
        / detector
        / f"{detector}_{int(request_start)}_{int(request_end)}.hdf5"
    )
    if not cached_path.is_file():
        raise FileNotFoundError(cached_path)
    cached = TimeSeries.read(cached_path)
    stitched_values = np.asarray(result.series.value)
    cached_values = np.asarray(cached.value)
    if not np.array_equal(stitched_values, cached_values):
        raise RuntimeError("manifest stitching differs from frozen parity-cache strain")
    body = {
        "schema_version": 1,
        "status": "PASS_SAMPLE_EXACT",
        "case_id": entry["case_id"],
        "detector": detector,
        "analysis_gps_start": analysis_start,
        "context_interval_gps": [request_start, request_end],
        "sample_rate_hz": int(result.series.sample_rate.value),
        "sample_count": int(len(result.series)),
        "maximum_absolute_sample_difference": float(
            np.max(np.abs(stitched_values - cached_values), initial=0.0)
        ),
        "stitched_strain_sha256": _array_sha256(stitched_values),
        "parity_cache_strain_sha256": _array_sha256(cached_values),
        "sources": [
            {
                "path": source.path.resolve().relative_to(raw_root.resolve()).as_posix(),
                "sha256": source.sha256,
                "declared_interval_gps": [source.block_start, source.block_end],
                "used_interval_gps": [source.used_start, source.used_end],
            }
            for source in result.sources
        ],
        "references": {
            "raw_manifest": {
                "path": RAW_MANIFEST.relative_to(ROOT).as_posix(),
                "sha256": sha256_path(RAW_MANIFEST),
            },
            "parity_manifest": {
                "path": PARITY_MANIFEST.relative_to(ROOT).as_posix(),
                "sha256": sha256_path(PARITY_MANIFEST),
            },
            "parity_contract": {
                "path": PARITY_CONTRACT.relative_to(ROOT).as_posix(),
                "sha256": sha256_path(PARITY_CONTRACT),
            },
            "implementation": {
                "path": "src/core/patch_producer.py",
                "sha256": sha256_path(ROOT / "src/core/patch_producer.py"),
            },
        },
        "external_storage": {
            "raw_root_alias": "DANTE_O4A_RAW_ROOT",
            "parity_cache_root_alias": "DANTE_O4A_V1_PARITY_CACHE_ROOT",
            "large_strain_files_committed": False,
        },
        "scientific_boundary": {
            "establishes_real_file_boundary_sample_equivalence": True,
            "establishes_full_corrected_o4a_run": False,
            "changes_historical_artifacts": False,
        },
    }
    return {**body, "artifact_digest": canonical_json_sha256(body)}


def write_context_validation(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    output: Path = OUTPUT,
) -> dict[str, Any]:
    value = build_context_validation(raw_root=raw_root, cache_root=cache_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return value
