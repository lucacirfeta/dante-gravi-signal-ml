from __future__ import annotations

import json

from src.dante_light.o4a_corrected_protocol import (
    OUTPUT_REL,
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
    assert calibration["coverage_counts"] == {
        "H1/complete_only_by_stitch": 117,
        "H1/complete_single_file": 19_587,
        "H1/not_complete_in_frozen_local_manifest": 11,
        "L1/complete_only_by_stitch": 129,
        "L1/complete_single_file": 20_123,
        "L1/not_complete_in_frozen_local_manifest": 4,
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


def test_corrected_protocol_iterators_are_deterministic() -> None:
    calibration = list(iter_calibration_identities(ROOT))
    assert len(calibration) == 39_971
    assert calibration[0]["session_id"] <= calibration[-1]["session_id"]
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
