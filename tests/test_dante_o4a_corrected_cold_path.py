from pathlib import Path

import pytest

from src.dante_light.o4a_corrected_cold_path import build_contract


@pytest.fixture(scope="module")
def contract() -> dict:
    return build_contract()


def test_cold_path_selection_is_outcome_blind_and_disjoint(contract: dict) -> None:
    selection = contract["selection"]
    assert selection["outcomes_used"] == []
    assert selection["prior_warm_canary_spans_excluded"] is True
    assert len(selection["spans"]) == 8
    assert {(row["group"], row["detector"]) for row in selection["spans"]} == {
        (group, detector) for group in range(4) for detector in ("H1", "L1")
    }
    assert all(len(row["expected_gps_starts"]) == 96 for row in selection["spans"])


def test_cold_path_gate_inherits_frozen_speedup(contract: dict) -> None:
    promotion = contract["benchmark"]["promotion"]
    assert promotion["minimum_speedup"] == 2.0
    assert promotion["source"] == "config/dante_o4a_corrected_performance_v2.json"
    assert contract["scientific_boundary"]["performance_only"] is True
