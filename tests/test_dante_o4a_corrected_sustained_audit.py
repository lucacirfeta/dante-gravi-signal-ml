import pytest

from src.dante_light.o4a_corrected_sustained_audit import build_contract


@pytest.fixture(scope="module")
def contract() -> dict:
    return build_contract()


def test_sustained_selection_is_fresh_and_representative(contract: dict) -> None:
    selection = contract["selection"]
    assert selection["outcomes_used"] == []
    assert selection["all_prior_canaries_excluded"] is True
    assert len(selection["spans"]) == 64
    keys = [
        (row["detector"], row["gps_start"], row["gps_end"], row["sha256"])
        for row in selection["spans"]
    ]
    assert len(keys) == len(set(keys))
    for detector in ("H1", "L1"):
        rows = [row for row in selection["spans"] if row["detector"] == detector]
        metrics = rows[0]["bundle_metrics"]
        assert len(rows) == 32
        assert len(metrics["duration_values_s"]) >= 2
        assert metrics["overlap_adjacent_pair_count"] >= 1
        assert metrics["expected_output_count"] >= 2_000
        assert all(row["bundle_metrics"] == metrics for row in rows)


def test_sustained_audit_cannot_promote_or_access_outcomes(contract: dict) -> None:
    assert contract["benchmark"]["promotion_allowed"] is False
    assert contract["benchmark"]["raw_series_cache_files"] == 0
    assert contract["benchmark"]["executor_backend"] == "process"
    boundary = contract["scientific_boundary"]
    assert boundary["thresholds_or_taxonomy_accessed"] is False
    assert boundary["can_refreeze_protocol"] is False
