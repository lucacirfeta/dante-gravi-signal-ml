from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import subprocess
import sys

from src.dante_light.prefilter_v6_partitions import load_partition_contract


ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "config/dante_light_prefilter_v6_partitions.json"
ENTRIES = ROOT / "config/dante_light_prefilter_v6_partitions.jsonl"
DOWNLOADS = ROOT / "config/dante_light_prefilter_v6_download_manifest.jsonl"
PLANNING = ROOT / "artifacts/dante_light/prefilter_l4_v6_design/phase_b_planning_audit_v6.json"


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_frozen_v6_partitions_recompute_outcome_blind() -> None:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/verify_dante_light_prefilter_v6_partitions.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    verified = json.loads(completed.stdout)
    assert verified["status"] == "PASS"
    assert verified["row_count"] == 1080
    assert verified["outcomes_accessed"] == []


def test_partitions_are_disjoint_balanced_and_use_block_independence() -> None:
    contract = load_partition_contract()
    rows = _rows(ENTRIES)
    keys = [row["block_key"] for row in rows]
    assert len(keys) == len(set(keys))
    for detector in contract["signal"]["detectors"]:
        for partition, expected in contract["partition_contract"]["blocks_per_detector"].items():
            selected = [row for row in rows if row["detector"] == detector and row["partition"] == partition]
            assert len(selected) == expected
            strata = Counter(row["span_stratum"] for row in selected)
            assert max(strata.values()) - min(strata.values()) <= 1
        phase_b = [row for row in rows if row["detector"] == detector and row["partition"] == "phase_b"]
        assert Counter(row["subset"] for row in phase_b) == Counter({"fit": 144, "internal_validation": 36})
        for subset in ("fit", "internal_validation"):
            strata = Counter(row["span_stratum"] for row in phase_b if row["subset"] == subset)
            assert max(strata.values()) - min(strata.values()) <= 1
        phase_c = [row for row in rows if row["detector"] == detector and row["partition"] == "phase_c"]
        assert all(row["subset"] == "sealed" for row in phase_c)
        assert all(len(row["selected_window_starts"]) == 1 for row in phase_c)


def test_eligible_pool_matches_the_prior_outcome_blind_audit() -> None:
    planning = json.loads(PLANNING.read_text(encoding="utf-8"))
    header = json.loads(HEADER.read_text(encoding="utf-8"))
    for detector in ("H1", "L1"):
        assert header["eligible_pool_digest"][detector] == planning["capacity"][detector]["official_eligible_block_keys_digest"]


def test_downloads_are_post_selection_padded_windows_only() -> None:
    contract = load_partition_contract()
    rows = _rows(ENTRIES)
    downloads = _rows(DOWNLOADS)
    expected = {row["block_key"] for row in rows if not row["selected_windows_currently_local"]}
    assert {row["block_key"] for row in downloads} == expected
    assert contract["selection_contract"]["local_availability_used_for_selection"] is False
    assert contract["download_contract"]["fetch_interval"] == "each_missing_selected_window_with_4s_pad_on_both_sides"
    for row in downloads:
        assert row["missing_padded_window_count"] == len(row["fetch_intervals"])
        assert all(interval["gps_end"] - interval["gps_start"] == 40.0 for interval in row["fetch_intervals"])
