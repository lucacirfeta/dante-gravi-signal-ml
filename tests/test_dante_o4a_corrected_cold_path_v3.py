import pytest

from src.dante_light.o4a_corrected_cold_path_v3 import build_contract


@pytest.fixture(scope="module")
def contract() -> dict:
    return build_contract()


def test_edge_cache_canary_is_fresh_outcome_blind_and_disjoint(contract: dict) -> None:
    selection = contract["selection"]
    assert selection["outcomes_used"] == []
    assert selection["all_prior_canaries_excluded"] is True
    assert selection["invalid_v2_superseded"] is True
    assert len(selection["spans"]) == 24
    keys = [
        (row["detector"], row["gps_start"], row["gps_end"], row["sha256"])
        for row in selection["spans"]
    ]
    assert len(keys) == len(set(keys))


def test_each_chain_is_contiguous_and_exercises_cross_file_context(contract: dict) -> None:
    for group in range(4):
        for detector in ("H1", "L1"):
            rows = sorted(
                (
                    row
                    for row in contract["selection"]["spans"]
                    if row["group"] == group and row["detector"] == detector
                ),
                key=lambda row: row["chain_position"],
            )
            assert len(rows) == 3
            assert rows[0]["gps_end"] == rows[1]["gps_start"]
            assert rows[1]["gps_end"] == rows[2]["gps_start"]
            assert rows[0]["chain_expected_window_count"] >= 300
            assert rows[0]["chain_cross_file_context_count"] >= 4
            assert all(
                row["chain_cross_file_gps_starts"]
                == rows[0]["chain_cross_file_gps_starts"]
                for row in rows
            )


def test_cache_candidate_preserves_scientific_contract(contract: dict) -> None:
    assert contract["benchmark"]["arms"]["uncached"]["raw_series_cache_files"] == 0
    assert contract["benchmark"]["arms"]["cache3"]["raw_series_cache_files"] == 3
    assert contract["benchmark"]["promotion"]["minimum_speedup"] == 2.0
    boundary = contract["scientific_boundary"]
    assert boundary["hash_verification_preserved"] is True
    assert boundary["whitening_context_preserved"] is True
