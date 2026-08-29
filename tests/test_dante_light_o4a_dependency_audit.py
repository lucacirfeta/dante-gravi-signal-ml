from __future__ import annotations

import json

from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.o4a_dependency_audit import OUTPUT, build_dependency_audit


def test_saved_dependency_audit_rebuilds_exactly() -> None:
    saved = json.loads(OUTPUT.read_text(encoding="utf-8"))
    body = dict(saved)
    assert body.pop("artifact_digest") == canonical_json_sha256(body)
    assert saved == build_dependency_audit()


def test_dependency_audit_requires_the_complete_rebuild_chain() -> None:
    value = build_dependency_audit()
    dependencies = value["dependencies"]
    assert dependencies["primary_o3b_index"]["disposition"].startswith("UNAFFECTED")
    assert dependencies["primary_o3b_index"]["complete_pad_sidecars"] == 1017
    primary = dependencies["historical_primary_session_calibrations"]
    assert primary["background_identity_count"] == 39_971
    assert primary["earliest_copy_session_detector_count"] == 82
    assert primary["earliest_copy_calibration_identity_count"] == 38_971
    assert primary["non_earliest_session_identity_count"] == 1_000
    assert primary["non_earliest_sessions_are_required"] is True
    assert primary["earliest_copy_counts"] == {
        "H1/complete_only_by_stitch": 116,
        "H1/complete_single_file": 19_090,
        "H1/not_complete_in_frozen_local_manifest": 9,
        "L1/complete_only_by_stitch": 126,
        "L1/complete_single_file": 19_626,
        "L1/not_complete_in_frozen_local_manifest": 4,
    }
    assert primary["required_session_detector_count"] == 84
    assert primary["required_calibration_identity_count"] == 39_971
    assert primary["cross_boundary_count"] == 246
    assert primary["not_complete_in_local_manifest_count"] == 15
    native = dependencies["native_o4a_index"]
    assert native["disposition"] == "REBUILD_REQUIRED"
    assert native["definitely_cross_boundary_regardless_of_detector_count"] == 4
    thresholds = dependencies["native_o4a_detector_thresholds"]
    assert thresholds["disposition"] == "RECOMPUTE_AFTER_NATIVE_INDEX_REBUILD"
    assert all(
        row["incomplete_padding_count"] == 0
        for row in thresholds["detectors"].values()
    )
    assert value["status"] == "REBUILD_CHAIN_REQUIRED"
