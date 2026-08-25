#!/usr/bin/env python3
"""Fail-closed verifier for DANTE-Light v6 partitions and download list."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.dante_light.prefilter_v6_partitions import (
    build_partition_freeze,
    file_sha256,
    load_partition_contract,
)


HEADER = ROOT / "config/dante_light_prefilter_v6_partitions.json"
ENTRIES = ROOT / "config/dante_light_prefilter_v6_partitions.jsonl"
DOWNLOADS = ROOT / "config/dante_light_prefilter_v6_download_manifest.jsonl"
SUMMARY = ROOT / "artifacts/dante_light/prefilter_l4_v6_design/partition_freeze_summary_v6.json"


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify() -> dict[str, object]:
    contract = load_partition_contract()
    recomputed = build_partition_freeze(contract=contract, root=ROOT)
    for path in (HEADER, ENTRIES, DOWNLOADS, SUMMARY):
        if not path.is_file():
            raise ContractError(f"v6 frozen partition file missing: {path.name}")
    rows = _jsonl(ENTRIES)
    downloads = _jsonl(DOWNLOADS)
    if rows != recomputed["rows"] or downloads != recomputed["download_rows"]:
        raise ContractError("v6 frozen partition rows do not recompute exactly")
    header = json.loads(HEADER.read_text(encoding="utf-8"))
    if header["manifest_digest"] != recomputed["manifest_digest"]:
        raise ContractError("v6 partition header digest mismatch")
    if header["entries_reference"]["sha256"] != file_sha256(ENTRIES):
        raise ContractError("v6 partition entries reference mismatch")
    if header["download_reference"]["sha256"] != file_sha256(DOWNLOADS):
        raise ContractError("v6 download reference mismatch")
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    body = dict(summary)
    declared = body.pop("artifact_digest", None)
    if declared != canonical_json_sha256(body):
        raise ContractError("v6 partition summary digest mismatch")
    if summary["manifest_digest"] != recomputed["manifest_digest"]:
        raise ContractError("v6 partition summary references the wrong manifest")
    return {
        "status": "PASS",
        "manifest_digest": recomputed["manifest_digest"],
        "row_count": len(rows),
        "download_row_count": len(downloads),
        "download_summary": recomputed["download_summary"],
        "outcomes_accessed": recomputed["outcomes_accessed"],
    }


def main() -> int:
    print(json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
