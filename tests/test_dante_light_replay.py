from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.benchmark_dante_light import percentile_summary, select_cases
from src.dante_light.contracts import WindowIdentity, canonical_json_sha256


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "dante_light_replay_v1.json"


def load_manifest() -> dict:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries_path = ROOT / value["entries_path"]
    assert hashlib.sha256(entries_path.read_bytes()).hexdigest() == value[
        "entries_file_sha256"
    ]
    value["entries"] = [
        json.loads(line)
        for line in entries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return value


def test_frozen_replay_manifest_has_complete_declared_cohorts() -> None:
    value = load_manifest()
    assert value["schema_version"] == 1
    assert value["status"] == "frozen"
    assert value["raw_strain_embedded"] is False
    assert value["counts"] == {
        "entries": 9388,
        "unique_windows": 9387,
        "roles": {
            "background_stratified": 552,
            "candidate_non_background": 7640,
            "cbc_control": 249,
            "cbc_injection": 750,
            "forum_candidate": 1,
            "known_glitch": 180,
            "threshold_boundary": 60,
        },
    }


def test_replay_manifest_and_entries_digests_are_self_consistent() -> None:
    value = load_manifest()
    assert value["entries_sha256"] == canonical_json_sha256(value["entries"])
    value.pop("entries")
    declared = value.pop("manifest_sha256")
    assert declared == canonical_json_sha256(value)


def test_every_replay_case_has_valid_stable_identity_and_no_machine_path() -> None:
    value = load_manifest()
    case_ids = set()
    forum = []
    for item in value["entries"]:
        identity = WindowIdentity.from_dict(item["window"])
        assert identity.window_id == item["window"]["window_id"]
        assert item["case_id"].startswith("dlc1-")
        assert item["case_id"] not in case_ids
        case_ids.add(item["case_id"])
        encoded = json.dumps(item, sort_keys=True)
        assert "E:\\" not in encoded
        assert "/mnt/e/" not in encoded
        if "forum_candidate" in item["roles"]:
            forum.append(item)
    assert len(case_ids) == value["counts"]["entries"]
    assert len(forum) == 1
    assert forum[0]["window"]["detector"] == "L1"
    assert forum[0]["window"]["gps_start"] == 1382955232.0


def test_available_replay_sources_still_match_frozen_hashes() -> None:
    """Verify local evidence when present; clean clones retain its ledger."""
    for source in load_manifest()["source_artifacts"]:
        path = ROOT / source["path"]
        if not path.is_file():
            continue
        assert path.stat().st_size == source["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]


def test_benchmark_selection_is_deterministic_detector_interleaved() -> None:
    manifest = load_manifest()
    first = select_cases(manifest, {"background_stratified"}, 8)
    second = select_cases(manifest, {"background_stratified"}, 8)
    assert [item["case_id"] for item in first] == [
        item["case_id"] for item in second
    ]
    assert [item["window"]["detector"] for item in first] == [
        "H1",
        "L1",
        "H1",
        "L1",
        "H1",
        "L1",
        "H1",
        "L1",
    ]
    assert all(item["source_kind"] != "synthetic_injection" for item in first)
    for detector in ("H1", "L1"):
        gps = [
            item["window"]["gps_start"]
            for item in first
            if item["window"]["detector"] == detector
        ]
        assert len(gps) == 4
        assert max(gps) - min(gps) > 10_000_000


def test_benchmark_percentile_summary_is_complete() -> None:
    summary = percentile_summary([1.0, 2.0, 3.0, 4.0])
    assert summary["count"] == 4
    assert summary["total_s"] == 10.0
    assert summary["p50_s"] == 2.5
    assert summary["p95_s"] >= summary["p50_s"]
    assert summary["p99_s"] >= summary["p95_s"]
