from __future__ import annotations

import json
from pathlib import Path

from src.dante_light.contracts import canonical_json_sha256
from src.dante_light.o4a_v1_edge_audit import DEFAULT_OUTPUT


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_edge_padding_audit_is_self_consistent() -> None:
    value = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    body = dict(value)
    digest = body.pop("artifact_digest")
    assert digest == canonical_json_sha256(body)
    assert value["status"] == "CONFIRMED_HISTORICAL_EDGE_PADDING_DEFECT"
    assert value["not_a_pass"] is True
    assert value["completed_records"] == 10_429
    assert value["source_counts"] == {
        "existing_raw_mirror": 10_260,
        "gwosc_open_data": 7,
        "verified_local_raw_stitch": 162,
    }
    assert value["source_score_mismatch_counts"] == {
        "gwosc_open_data": 7,
        "verified_local_raw_stitch": 162,
    }
    assert value["changed_class_count"] == 120
    assert value["changed_route_count"] == 97
    assert value["edge_geometry"]["historical_effective_right_padding_s"] == 0.0
    assert value["edge_family_counts"] == {"Family_01": 169}
    reproduction = value["clipped_context_reproduction"]
    assert reproduction["effective_right_padding_s"] == 0.0
    assert reproduction["absolute_native_score_delta"] <= value["score_absolute_tolerance"]
    assert value["scientific_boundary"]["requires_complete_o4a_rescan"] is True
    assert value["scientific_boundary"]["single_case_clipped_context_causality_established"] is True
    assert value["scientific_boundary"]["all_edge_windows_historical_score_parity_established"] is False
