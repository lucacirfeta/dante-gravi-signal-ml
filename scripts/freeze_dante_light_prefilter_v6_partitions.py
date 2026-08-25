#!/usr/bin/env python3
"""Freeze outcome-blind DANTE-Light v6 block identities and downloads."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.prefilter_v6_partitions import (
    build_partition_freeze,
    file_sha256,
    load_partition_contract,
)


HEADER = ROOT / "config/dante_light_prefilter_v6_partitions.json"
ENTRIES = ROOT / "config/dante_light_prefilter_v6_partitions.jsonl"
DOWNLOADS = ROOT / "config/dante_light_prefilter_v6_download_manifest.jsonl"
SUMMARY = ROOT / "artifacts/dante_light/prefilter_l4_v6_design/partition_freeze_summary_v6.json"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def main() -> int:
    contract = load_partition_contract()
    complete = build_partition_freeze(contract=contract, root=ROOT)
    rows = complete["rows"]
    downloads = complete["download_rows"]
    _write(ENTRIES, "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows))
    _write(DOWNLOADS, "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in downloads))
    body = {key: value for key, value in complete.items() if key not in {"rows", "download_rows", "manifest_digest"}}
    body["entries_reference"] = {"path": ENTRIES.relative_to(ROOT).as_posix(), "sha256": file_sha256(ENTRIES)}
    body["download_reference"] = {"path": DOWNLOADS.relative_to(ROOT).as_posix(), "sha256": file_sha256(DOWNLOADS)}
    header = {**body, "manifest_digest": complete["manifest_digest"]}
    _write(HEADER, json.dumps(header, indent=2, sort_keys=True, allow_nan=False) + "\n")
    summary = {
        "schema_version": 1,
        "status": "FROZEN_OUTCOME_BLIND_PARTITIONS_VERIFIED",
        "contract_digest": contract["contract_digest"],
        "manifest_digest": complete["manifest_digest"],
        "row_count": len(rows),
        "download_row_count": len(downloads),
        "summary": complete["summary"],
        "download_summary": complete["download_summary"],
        "eligible_pool_digest": complete["eligible_pool_digest"],
        "outcomes_accessed": [],
    }
    summary["artifact_digest"] = canonical_json_sha256(summary)
    _write(SUMMARY, json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps({
        "status": "PASS",
        "manifest_digest": complete["manifest_digest"],
        "download_blocks": len(downloads),
        "download_summary": complete["download_summary"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
