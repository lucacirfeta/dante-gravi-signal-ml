from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "benchmarks" / "dante_light_l0_baseline.json"
RESULTS = ROOT / "benchmarks" / "dante_light_l0_baseline.jsonl"
MANIFEST = ROOT / "config" / "dante_light_replay_v1.json"
L1_CONTROL = ROOT / "benchmarks" / "dante_light_l1_canonical_control.json"
L1_SHARED = ROOT / "benchmarks" / "dante_light_l1_shared_encoder.json"
L1_SCORE_ONLY_CONTROL = (
    ROOT / "benchmarks" / "dante_light_l1_score_only_canonical_control.json"
)
L1_SCORE_ONLY_SHARED = (
    ROOT / "benchmarks" / "dante_light_l1_score_only_shared.json"
)


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_l0_baseline_is_complete_exact_and_self_consistent() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    rows = _load_jsonl(RESULTS)

    assert report["schema_version"] == 1
    assert report["status"] == "complete"
    assert report["scientific_mode"] == "historical_exact_replay"
    assert report["prefilter"] == "none"
    assert report["warmup_excluded_from_summary"] is True
    assert report["code_state"]["tracked_dirty"] is False

    assert report["coverage"] == {
        "drops": 0,
        "failures": [],
        "measured_windows": 16,
        "queue_depth": 0,
    }
    assert report["selection"]["repeat_count"] == 2
    assert report["selection"]["warmup_count"] == 1
    assert report["results_jsonl"]["rows"] == 17
    assert len(rows) == 17
    assert hashlib.sha256(RESULTS.read_bytes()).hexdigest() == report[
        "results_jsonl"
    ]["sha256"]
    assert b"\r\n" not in RESULTS.read_bytes()

    assert report["numerical_repeat_max_abs_delta"] <= 1.0e-7
    assert report["golden_score_atol"] == 2.0e-7
    assert report["golden_expected_max_abs_delta"] <= report["golden_score_atol"]
    assert report["throughput_windows_per_s"] > 0.0
    assert report["resources"]["peak_rss_bytes"] > 0


def test_l0_repeats_are_identical_and_cover_the_frozen_cases() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    manifest_header = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest_entries = _load_jsonl(ROOT / manifest_header["entries_path"])
    by_case = {entry["case_id"]: entry for entry in manifest_entries}
    rows = _load_jsonl(RESULTS)

    warmup = [row for row in rows if row["phase"] == "warmup"]
    measured = [row for row in rows if row["phase"] == "measured"]
    assert len(warmup) == 1
    assert warmup[0]["repeat"] is None
    assert len(measured) == 16

    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in measured:
        grouped[row["case_id"]].append(row)
    assert set(grouped) == set(report["selection"]["selected_case_ids"])
    assert all(len(repeats) == 2 for repeats in grouped.values())

    exact_fields = (
        "input_sha256",
        "native_score",
        "native_top_k_sha256",
        "primary_score",
        "primary_top_k_sha256",
        "window_id",
    )
    for case_id, repeats in grouped.items():
        assert sorted(row["repeat"] for row in repeats) == [0, 1]
        assert all(
            repeats[0][field] == repeats[1][field] for field in exact_fields
        )
        assert repeats[0]["window_id"] == by_case[case_id]["window"]["window_id"]

    detectors = [by_case[case_id]["window"]["detector"] for case_id in grouped]
    assert detectors.count("H1") == 4
    assert detectors.count("L1") == 4
    for detector in ("H1", "L1"):
        gps = [
            by_case[case_id]["window"]["gps_start"]
            for case_id in grouped
            if by_case[case_id]["window"]["detector"] == detector
        ]
        assert max(gps) - min(gps) > 10_000_000


def test_l0_stage_timings_have_ordered_quantiles() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    required = {
        "data_read_s",
        "whitening_s",
        "q_transform_s",
        "rendering_s",
        "primary_score_total_s",
        "native_score_total_s",
        "persistence_s",
        "end_to_end_s",
    }
    assert required <= set(report["stage_timings"])
    for name, summary in report["stage_timings"].items():
        assert summary["count"] == 16, name
        assert 0.0 <= summary["p50_s"] <= summary["p95_s"] <= summary["p99_s"], name
        assert summary["total_s"] >= 0.0, name
        assert 0.0 <= summary["fraction_of_end_to_end"] <= 1.0, name


def test_l0_report_does_not_publish_machine_local_data_paths() -> None:
    encoded = REPORT.read_text(encoding="utf-8")
    assert "E:\\" not in encoded
    assert "/mnt/e/" not in encoded
    for digest in json.loads(encoded)["source_sha256"].values():
        assert len(digest) == 64
        int(digest, 16)


def test_l1_shared_encoder_is_exact_and_meets_frozen_adoption_gate() -> None:
    control = json.loads(L1_CONTROL.read_text(encoding="utf-8"))
    shared = json.loads(L1_SHARED.read_text(encoding="utf-8"))
    control_rows = _load_jsonl(L1_CONTROL.with_suffix(".jsonl"))
    shared_rows = _load_jsonl(L1_SHARED.with_suffix(".jsonl"))

    assert control["status"] == shared["status"] == "complete"
    assert control["engine"] == "canonical"
    assert shared["engine"] == "shared_encoder"
    assert control["code_state"] == shared["code_state"]
    assert control["code_state"]["tracked_dirty"] is False
    assert control["selection"] == shared["selection"]
    assert control["representation"] == shared["representation"]
    assert control["coverage"] == shared["coverage"] == {
        "drops": 0,
        "failures": [],
        "measured_windows": 16,
        "queue_depth": 0,
    }

    exact_fields = (
        "case_id",
        "expected_native_score",
        "input_sha256",
        "native_score",
        "native_top_k_sha256",
        "phase",
        "primary_score",
        "primary_top_k_sha256",
        "repeat",
        "window_id",
    )
    assert len(control_rows) == len(shared_rows) == 17
    for expected, actual in zip(control_rows, shared_rows, strict=True):
        assert all(expected[field] == actual[field] for field in exact_fields)

    for report, report_path in ((control, L1_CONTROL), (shared, L1_SHARED)):
        result_path = report_path.with_suffix(".jsonl")
        assert hashlib.sha256(result_path.read_bytes()).hexdigest() == report[
            "results_jsonl"
        ]["sha256"]
        assert report["numerical_repeat_max_abs_delta"] <= 1.0e-7
        assert report["golden_expected_max_abs_delta"] <= report[
            "golden_score_atol"
        ]

    speedup = shared["throughput_windows_per_s"] / control[
        "throughput_windows_per_s"
    ]
    assert speedup >= 1.10
    assert shared["resources"]["peak_rss_bytes"] <= control["resources"][
        "peak_rss_bytes"
    ]


def test_l1_score_only_path_preserves_scalars_and_clears_adoption_gate() -> None:
    control = json.loads(L1_SCORE_ONLY_CONTROL.read_text(encoding="utf-8"))
    shared = json.loads(L1_SCORE_ONLY_SHARED.read_text(encoding="utf-8"))
    control_rows = _load_jsonl(L1_SCORE_ONLY_CONTROL.with_suffix(".jsonl"))
    shared_rows = _load_jsonl(L1_SCORE_ONLY_SHARED.with_suffix(".jsonl"))

    assert control["engine"] == "canonical"
    assert shared["engine"] == "shared_encoder_score_only"
    assert (
        control["source_hash_semantics"]
        == shared["source_hash_semantics"]
        == "utf8_lf_v1"
    )
    assert control["code_state"] == shared["code_state"]
    assert control["code_state"]["tracked_dirty"] is False
    assert control["selection"] == shared["selection"]
    assert control["coverage"] == shared["coverage"]
    assert control["coverage"]["failures"] == []
    assert control["coverage"]["drops"] == 0

    scalar_fields = (
        "case_id",
        "expected_native_score",
        "input_sha256",
        "native_score",
        "phase",
        "primary_score",
        "primary_top_k_sha256",
        "repeat",
        "window_id",
    )
    assert len(control_rows) == len(shared_rows) == 17
    for expected, actual in zip(control_rows, shared_rows, strict=True):
        assert all(expected[field] == actual[field] for field in scalar_fields)
        assert expected["native_top_k_sha256"] is not None
        assert actual["native_top_k_sha256"] is None

    speedup = shared["throughput_windows_per_s"] / control[
        "throughput_windows_per_s"
    ]
    assert speedup >= 1.10
    assert shared["numerical_repeat_max_abs_delta"] <= 1.0e-7
    assert shared["golden_expected_max_abs_delta"] <= shared["golden_score_atol"]
