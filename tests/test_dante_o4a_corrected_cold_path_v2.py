import pytest

from src.dante_light.o4a_corrected_cold_path_v2 import build_contract


@pytest.fixture(scope="module")
def contract() -> dict:
    return build_contract()


def test_raw_series_cache_canary_is_fresh_and_outcome_blind(contract: dict) -> None:
    selection = contract["selection"]
    assert selection["outcomes_used"] == []
    assert selection["all_prior_canaries_excluded"] is True
    assert len(selection["spans"]) == 8
    assert all(len(row["expected_gps_starts"]) == 96 for row in selection["spans"])


def test_raw_series_cache_candidate_preserves_scientific_contract(contract: dict) -> None:
    assert contract["benchmark"]["arms"]["uncached"]["raw_series_cache_files"] == 0
    assert contract["benchmark"]["arms"]["cache3"]["raw_series_cache_files"] == 3
    assert contract["benchmark"]["promotion"]["minimum_speedup"] == 2.0
    boundary = contract["scientific_boundary"]
    assert boundary["hash_verification_preserved"] is True
    assert boundary["whitening_context_preserved"] is True
