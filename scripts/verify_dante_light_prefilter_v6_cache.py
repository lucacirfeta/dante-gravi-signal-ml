#!/usr/bin/env python3
"""Fail-closed verifier for the frozen v6 Phase-B raw-window cache."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_cache import (
    _timeseries_record,
    load_phase_b_downloads,
)
from src.dante_light.prefilter_v6_partitions import file_sha256


DEFAULT_CACHE = Path(os.environ.get("DANTE_V6_RAW_CACHE_ROOT", r"E:\dante_cache\dante_light\prefilter_l4_v6_raw"))
DEFAULT_ARTIFACT = ROOT / "artifacts/dante_light/prefilter_l4_v6_cache/phase_b_raw_cache_summary_v6.json"


def verify(*, cache_root: Path, artifact_path: Path, deep: bool, allow_smoke: bool = False) -> dict[str, object]:
    summary = json.loads(artifact_path.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 raw-cache summary digest mismatch")
    allowed = {"COMPLETE"} | ({"SMOKE_ONLY"} if allow_smoke else set())
    if summary.get("status") not in allowed:
        raise ContractError("v6 raw cache is not complete")
    for field in (
        "phase_c_rows_accessed",
        "phase_d_rows_accessed",
        "o4b_rows_accessed",
        "teacher_scores_accessed",
    ):
        if summary.get(field) != []:
            raise ContractError(f"v6 raw cache crossed its boundary: {field}")
    run_dir = cache_root / summary["cache_location"]["run_subdirectory"]
    ledger_path = run_dir / summary["cache_manifest"]["path"]
    if not ledger_path.is_file() or file_sha256(ledger_path) != summary["cache_manifest"]["sha256"]:
        raise ContractError("v6 raw-cache ledger is missing or stale")
    rows = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != int(summary["cached_interval_count"]):
        raise ContractError("v6 raw-cache ledger count mismatch")
    if canonical_json_sha256(rows) != summary["cache_manifest"]["records_digest"]:
        raise ContractError("v6 raw-cache ledger records digest mismatch")
    expected = load_phase_b_downloads(root=ROOT)[1]
    expected_ids = {
        (row["detector"], int(row["block_index"]), float(row["gps_start"]), float(row["gps_end"]))
        for row in expected
    }
    actual_ids = {
        (row["detector"], int(row["block_index"]), float(row["gps_start"]), float(row["gps_end"]))
        for row in rows
    }
    if summary["status"] == "COMPLETE" and actual_ids != expected_ids:
        raise ContractError("v6 complete raw-cache identities differ from the frozen manifest")
    if not actual_ids.issubset(expected_ids):
        raise ContractError("v6 raw cache contains an unauthorized identity")
    for row in rows:
        record_body = dict(row)
        record_digest = record_body.pop("record_digest", None)
        if record_digest != canonical_json_sha256(record_body):
            raise ContractError("v6 raw-cache record digest mismatch")
        path = run_dir / row["relative_path"]
        if not path.is_file() or file_sha256(path) != row["file_sha256"]:
            raise ContractError("v6 raw-cache file hash mismatch")
        if deep:
            observed = _timeseries_record(path, row, sample_rate_hz=int(row["sample_rate_hz"]))
            for key in ("sample_count", "strain_values_sha256"):
                if observed[key] != row[key]:
                    raise ContractError(f"v6 raw-cache deep mismatch: {key}")
    return {
        "status": "PASS",
        "artifact_digest": declared,
        "cached_interval_count": len(rows),
        "deep": deep,
        "phase_c_rows_accessed": summary["phase_c_rows_accessed"],
        "phase_d_rows_accessed": summary["phase_d_rows_accessed"],
        "o4b_rows_accessed": summary["o4b_rows_accessed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(
        cache_root=args.cache_root.resolve(),
        artifact_path=args.artifact.resolve(),
        deep=args.deep,
    ), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
