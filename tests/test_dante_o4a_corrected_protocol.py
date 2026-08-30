from __future__ import annotations

import json
from pathlib import Path

from src.dante_light.o4a_corrected_protocol import (
    CURRENT_OUTPUT_REL as OUTPUT_REL,
    ROOT,
    build_corrected_protocol,
    iter_calibration_identities,
    iter_scan_identities,
    validate_corrected_protocol,
)


def test_corrected_protocol_population_and_scientific_boundaries() -> None:
    value = build_corrected_protocol(ROOT)
    validate_corrected_protocol(value, ROOT)
    calibration = value["calibration_population"]
    assert calibration["identity_count"] == 39_971
    assert calibration["session_detector_counts"] == {"H1": 42, "L1": 42}
    assert calibration["score_reuse_allowed"] is False
    assert value["scientific_change"]["threshold_or_score_tolerance_change"] is False
    assert value["scientific_change"]["cross_environment_shard_reuse_allowed"] is False
    assert value["execution_parameters"] == {
        "primary_calibration": {"device": "cuda", "workers": 8, "batch_size": 32},
        "primary_scan": {
            "device": "cuda",
            "workers": 8,
            "batch_size": 32,
            "detector_mode": "parallel_shared_scorer",
            "queue_depth_batches": 2,
            "queue_topology": "single_combined_bounded_queue",
            "database_commit_rows": 1024,
            "patch_executor_backend": "process",
            "raw_series_cache_files": 0,
        },
    }
    assert value["scientific_change"]["performance_only_refreeze"] is True
    assert value["scientific_change"]["scoring_function_or_population_changed"] is False
    assert value["scientific_change"]["thresholds_or_validation_rules_changed"] is False
    assert value["scientific_change"]["prior_scan_outcomes_inspected"] is False
    assert value["administrative_refreeze"]["active_patch_producer"] == {
        "executor_backend": "process",
        "raw_series_cache_files": 0,
    }
    assert value["administrative_refreeze"]["prior_calibration_or_scan_shard_reuse_allowed"] is False
    assert value["canonical_runtime"]["required_for"] == [
        "primary_calibration",
        "primary_scan",
    ]
    assert calibration["coverage_counts"] == {
        "H1/complete_only_by_stitch": 272,
        "H1/complete_single_file": 19_425,
        "H1/not_complete_in_frozen_local_manifest": 18,
        "L1/complete_only_by_stitch": 291,
        "L1/complete_single_file": 19_955,
        "L1/not_complete_in_frozen_local_manifest": 10,
    }
    assert calibration["historical_context_counts"] == {
        "H1/HISTORICAL_FULL_SYMMETRIC_4S": 19_425,
        "H1/HISTORICAL_LEFT_TRUNCATED_4S": 162,
        "H1/HISTORICAL_RIGHT_TRUNCATED_4S": 128,
        "L1/HISTORICAL_FULL_SYMMETRIC_4S": 19_954,
        "L1/HISTORICAL_LEFT_TRUNCATED_4S": 169,
        "L1/HISTORICAL_RIGHT_TRUNCATED_4S": 133,
    }
    assert calibration["replay_disposition_counts"] == {
        "H1/CORRECTED_CONTEXT_NO_REPLAY": 290,
        "H1/REQUIRE_EXACT_REPLAY": 19_425,
        "L1/CORRECTED_CONTEXT_NO_REPLAY": 302,
        "L1/REQUIRE_EXACT_REPLAY": 19_954,
    }
    scan = value["scan_population"]
    assert scan["eligible_total"] == 811_251
    assert scan["eligible_counts"] == {"H1": 401_442, "L1": 409_809}
    assert scan["excluded_unique_total"] == 72_053
    assert scan["excluded_unique_counts"] == {"H1": 40_470, "L1": 31_583}
    assert scan["excluded_invalid_raw_or_context_total"] == 71_553
    assert scan["excluded_invalid_raw_or_context_counts"] == {
        "H1": 40_163,
        "L1": 31_390,
    }
    assert scan["eligible_total"] + scan["excluded_unique_total"] == 883_304
    assert scan["excluded_component_edge_total"] == 1_018
    assert scan["overlapping_span_duplicate_window_memberships"] == {
        "H1": 72,
        "L1": 328,
    }
    assert value["scientific_boundary"]["publication_or_submission_authorized"] is False


def test_v4_refreeze_preserves_v3_scientific_contract() -> None:
    current = build_corrected_protocol(ROOT)
    previous = json.loads(
        (ROOT / Path("config/dante_o4a_corrected_protocol_v3.json")).read_text(
            encoding="utf-8"
        )
    )
    for key in (
        "representation",
        "canonical_runtime",
        "calibration_population",
        "scan_population",
        "execution_order",
        "scientific_boundary",
    ):
        assert current[key] == previous[key]
    assert current["execution_parameters"]["primary_calibration"] == previous[
        "execution_parameters"
    ]["primary_calibration"]
    for key, value in previous["execution_parameters"]["primary_scan"].items():
        assert current["execution_parameters"]["primary_scan"][key] == value


def test_corrected_protocol_iterators_are_deterministic() -> None:
    calibration = list(iter_calibration_identities(ROOT))
    assert len(calibration) == 39_971
    assert calibration[0]["session_id"] <= calibration[-1]["session_id"]
    by_identity = {
        (row["session_id"], row["detector"], row["catalog_gps_start"]): row
        for row in calibration
    }
    left = by_identity[(1368973312, "H1", 1369227264.0)]
    assert left["analysis_gps_start"] == 1369227264.0
    assert left["required_padded_interval"] == [1369227260.0, 1369227300.0]
    assert left["replay_disposition"] == "CORRECTED_CONTEXT_NO_REPLAY"
    right = by_identity[(1368973312, "H1", 1369280476.0)]
    assert right["analysis_gps_start"] == 1369280480.0
    assert right["required_padded_interval"] == [1369280476.0, 1369280516.0]
    assert right["replay_disposition"] == "CORRECTED_CONTEXT_NO_REPLAY"
    full = by_identity[(1368973312, "H1", 1369206812.0)]
    assert full["analysis_gps_start"] == 1369206816.0
    assert full["replay_disposition"] == "REQUIRE_EXACT_REPLAY"
    count = 0
    previous = {"H1": None, "L1": None}
    for row in iter_scan_identities(ROOT):
        detector = row["detector"]
        if previous[detector] is not None:
            assert row["analysis_gps_start"] > previous[detector]
        previous[detector] = row["analysis_gps_start"]
        assert row["context_disposition"] == "COMPLETE_SYMMETRIC_4S_VALID_RAW"
        assert row["exclusion_reasons"] == []
        count += 1
    assert count == build_corrected_protocol(ROOT)["scan_population"]["eligible_total"]


def test_saved_corrected_protocol_is_current_when_present() -> None:
    path = ROOT / OUTPUT_REL
    if path.is_file():
        stored = json.loads(path.read_text(encoding="utf-8"))
        validate_corrected_protocol(stored, ROOT)
        assert stored == build_corrected_protocol(ROOT)
