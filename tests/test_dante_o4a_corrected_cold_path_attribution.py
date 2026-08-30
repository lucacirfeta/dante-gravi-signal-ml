import pytest

from src.dante_light.o4a_corrected_cold_path_attribution import build_contract


@pytest.fixture(scope="module")
def contract() -> dict:
    return build_contract()


def test_attribution_canary_is_fresh_disjoint_and_outcome_blind(contract: dict) -> None:
    selection = contract["selection"]
    assert selection["outcomes_used"] == []
    assert selection["all_prior_canaries_excluded"] is True
    assert len(selection["spans"]) == 6
    keys = [
        (row["detector"], row["gps_start"], row["gps_end"], row["sha256"])
        for row in selection["spans"]
    ]
    assert len(keys) == len(set(keys))
    assert all(len(row["expected_gps_starts"]) == 96 for row in selection["spans"])


def test_attribution_modes_do_not_define_candidate_outcomes(contract: dict) -> None:
    assert contract["benchmark"]["modes"] == [
        "score_only", "full_all", "full_all_identity_db"
    ]
    assert contract["benchmark"]["interpretation"]["promotion_allowed"] is False
    assert (
        contract["benchmark"]["database"]
        ["diagnostic_schema_has_no_candidate_or_disposition_field"]
        is True
    )
    boundary = contract["scientific_boundary"]
    assert boundary["thresholds_or_taxonomy_accessed"] is False
    assert boundary["uniform_full_materialization_without_thresholds"] is True
    assert boundary["can_refreeze_protocol"] is False
