from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.o3a_population_geometry import (
    build_identity_universes,
    iter_role_identities,
    load_identity_universes,
    validate_identity_universes,
)


ROOT = Path(__file__).resolve().parents[1]


def test_identity_universes_match_frozen_o3a_geometry() -> None:
    value = load_identity_universes(root=ROOT)
    assert value["roles"]["primary_scan_geometric_universe"][
        "counts_by_detector"
    ] == {"H1": 349_925, "L1": 372_986}
    assert value["roles"]["initial_calibration_proposal_universe"][
        "counts_by_detector"
    ] == {"H1": 174_967, "L1": 186_491}
    assert value["strain_data_accessed"] is False
    assert value["outcome_data_accessed"] is False


def test_compact_ranges_expand_to_exact_unique_aligned_identities() -> None:
    value = load_identity_universes(root=ROOT)
    for role, stride in (
        ("primary_scan_geometric_universe", 32),
        ("initial_calibration_proposal_universe", 64),
    ):
        rows = list(iter_role_identities(value, role))
        expected = value["roles"][role]
        assert len(rows) == expected["total_count"]
        assert len(rows) == len(set(rows))
        assert all(gps % stride == 0 for _detector, gps in rows)
        assert rows == sorted(rows, key=lambda item: (item[0], item[1]))


def test_calibration_universe_is_an_explicit_scan_subset() -> None:
    value = load_identity_universes(root=ROOT)
    scan = set(iter_role_identities(value, "primary_scan_geometric_universe"))
    calibration = set(
        iter_role_identities(value, "initial_calibration_proposal_universe")
    )
    assert calibration < scan
    assert value["selection_boundary"]["initial_calibration_members_selected"] is False


def test_identity_manifest_rejects_range_drift() -> None:
    value = build_identity_universes(root=ROOT)
    mutated = copy.deepcopy(value)
    mutated["roles"]["primary_scan_geometric_universe"]["ranges_by_detector"][
        "H1"
    ][0]["first_gps_start"] += 32
    with pytest.raises(ContractError, match="manifest mismatch"):
        validate_identity_universes(mutated, root=ROOT)
