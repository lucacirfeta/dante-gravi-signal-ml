from __future__ import annotations

import copy

import pytest

from src.dante_light.contracts import ContractError, canonical_json_sha256
from src.pipeline_v3_multiscale.efficiency_v2 import ROOT, _block_key
from src.pipeline_v3_multiscale.efficiency_v2_a1_cohort import (
    _expected_run_key,
    load_a1_cohort_contract,
    select_a1_cohort_rows,
    validate_a1_cohort_contract,
)


def _rehash(payload: dict) -> dict:
    value = copy.deepcopy(payload)
    value.pop("contract_digest", None)
    value["contract_digest"] = canonical_json_sha256(value)
    return value


def test_a1_cohort_contract_accepts_checked_in_freeze() -> None:
    contract = load_a1_cohort_contract(ROOT)
    assert (
        contract["population"]["roles"]["heldout_background"][
            "source_blocks_per_detector"
        ]
        == 1000
    )
    assert contract["expected_cardinality"]["rows_total"] == 2280
    assert contract["selection"]["complete_exploratory_cohort_blocks_excluded"]
    assert contract["scientific_boundary"]["heldout_outcomes_opened"] is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["population"]["roles"]["heldout_background"].update(
                source_blocks_per_detector=999
            ),
            "population",
        ),
        (
            lambda value: value["selection"].update(
                complete_exploratory_cohort_blocks_excluded=False
            ),
            "selection",
        ),
        (
            lambda value: value["expected_cardinality"].update(rows_total=2279),
            "cardinality",
        ),
        (
            lambda value: value["scientific_boundary"].update(
                heldout_outcomes_opened=True
            ),
            "scientific boundary",
        ),
    ],
)
def test_a1_cohort_contract_rejects_scientific_drift(mutation, message: str) -> None:
    contract = load_a1_cohort_contract(ROOT)
    mutation(contract)
    with pytest.raises(ContractError, match=message):
        validate_a1_cohort_contract(_rehash(contract), root=ROOT)


def _block(detector: str, index: int) -> dict:
    start = float(index * 300)
    return {
        "detector": detector,
        "gps_start": start,
        "gps_end": start + 200.0,
        "source_relative_path": f"{detector}/{index}.hdf5",
        "source_sha256": f"{index + 1:064x}",
    }


def test_a1_selection_excludes_exploratory_blocks_and_preserves_role_disjointness() -> (
    None
):
    contract = load_a1_cohort_contract(ROOT)
    contract["population"]["roles"]["heldout_background"][
        "source_blocks_per_detector"
    ] = 2
    contract["population"]["roles"]["heldout_primary_injection"][
        "source_blocks_per_detector"
    ] = 1
    contract["population"]["roles"]["heldout_secondary_control"][
        "source_blocks_per_detector"
    ] = 1
    raw_blocks = {
        detector: [_block(detector, i) for i in range(5)] for detector in ("H1", "L1")
    }
    geometry = {
        detector: [
            {
                "detector": detector,
                "gps_start": float(i * 300 + 50),
                "expected_clean_image_sha256": "a" * 64,
                "source_identity_digest": "b" * 64,
            }
            for i in range(5)
        ]
        for detector in ("H1", "L1")
    }
    exploratory = [
        {"detector": detector, "raw_block": raw_blocks[detector][0]}
        for detector in ("H1", "L1")
    ]
    rows, audit = select_a1_cohort_rows(
        contract=contract,
        raw_blocks=raw_blocks,
        scan_geometry=geometry,
        candidate_times=[],
        canonical_forbidden_blocks=set(),
        exploratory_rows=exploratory,
    )
    assert len(rows) == 8
    assert len({(row["detector"], _block_key(row["raw_block"])) for row in rows}) == 8
    assert all(row["raw_block"]["gps_start"] != 0.0 for row in rows)
    assert all(value["exploratory_blocks_excluded"] == 1 for value in audit.values())


def test_a1_run_key_binds_contract_and_exploratory_cohort() -> None:
    contract = load_a1_cohort_contract(ROOT)
    baseline = _expected_run_key(contract)
    changed = copy.deepcopy(contract)
    changed["contract_digest"] = "0" * 64
    assert baseline != _expected_run_key(changed)
    changed = copy.deepcopy(contract)
    changed["exploratory_cohort"]["artifact_digest"] = "0" * 64
    assert baseline != _expected_run_key(changed)
