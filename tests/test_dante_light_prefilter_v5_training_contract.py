from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v5_protocol import ROOT
from src.dante_light.prefilter_v5_training_contract import (
    DEFAULT_CONTRACT,
    DEFAULT_DESIGN,
    _float32_from_hex,
    assign_training_blocks,
    load_training_freeze,
    target_standardization,
    validate_training_design,
)


def _design() -> dict:
    return json.loads(DEFAULT_DESIGN.read_text(encoding="utf-8"))


def test_training_design_records_approved_fixed_lr_contract() -> None:
    design = validate_training_design(_design())
    optimization = design["optimization"]
    assert optimization["optimizer"] == {
        "name": "AdamW",
        "learning_rate": 0.001,
        "weight_decay": 0.0001,
        "betas": [0.9, 0.999],
        "epsilon": 1e-08,
        "amsgrad": False,
    }
    assert optimization["scheduler"]["name"] == "none"
    assert optimization["scheduler"]["intentional"] is True
    assert optimization["maximum_epochs"] == 100
    assert optimization["early_stopping"] is False
    assert optimization["checkpoint_selection"]["tie_break"] == "earliest_epoch"


def test_training_design_records_fail_closed_replicate_policy() -> None:
    design = validate_training_design(_design())
    failure = design["numerical_failure"]
    assert (
        failure["nonfinite_input_activation_prediction_loss_gradient_or_parameter"]
        == "FAILED"
    )
    assert failure["failed_replicate_blocks_candidate_promotion"] is True
    assert (
        failure["infrastructure_interruption"]
        == "INCOMPLETE_RERUN_SAME_SEED_ALLOWED"
    )


@pytest.mark.parametrize(
    "field",
    [
        "development_access_allowed",
        "confirmation_access_allowed",
        "o4b_access_allowed",
        "morphology_labels_allowed",
        "routing_enabled",
    ],
)
def test_training_design_rejects_widened_outcome_access(field: str) -> None:
    design = copy.deepcopy(_design())
    design["scope"][field] = True
    with pytest.raises(ContractError):
        validate_training_design(design)


def test_internal_split_is_detector_stratified_deterministic_and_disjoint() -> None:
    keys = [(detector, index) for detector in ("H1", "L1") for index in range(20)]
    kwargs = {
        "fit_fraction": 0.9,
        "seed_purpose": "training_fit_validation_split",
        "parent_digests": [character * 64 for character in "abcd"],
    }
    first, first_seeds = assign_training_blocks(keys, **kwargs)
    second, second_seeds = assign_training_blocks(keys, **kwargs)
    assert first == second
    assert first_seeds == second_seeds
    assert len({(row["detector"], row["block_index"]) for row in first}) == 40
    for detector in ("H1", "L1"):
        assert sum(
            row["detector"] == detector and row["subset"] == "fit"
            for row in first
        ) == 18
        assert sum(
            row["detector"] == detector and row["subset"] == "validation"
            for row in first
        ) == 2


def test_target_standardization_uses_fit_subset_only() -> None:
    def row(detector: str, subset: str, value: float) -> dict:
        return {
            "detector": detector,
            "subset": subset,
            "teacher_target_float32_hex": np.float32(value).tobytes().hex(),
        }

    targets = [
        row("H1", "fit", 1.0),
        row("H1", "fit", 3.0),
        row("H1", "validation", 1000.0),
        row("L1", "fit", 2.0),
        row("L1", "fit", 6.0),
        row("L1", "validation", -1000.0),
    ]
    result = target_standardization(targets)
    assert result["H1"] == {
        "fit_count": 2,
        "mean_float64": 2.0,
        "standard_deviation_float64_ddof0": 1.0,
    }
    assert result["L1"] == {
        "fit_count": 2,
        "mean_float64": 4.0,
        "standard_deviation_float64_ddof0": 2.0,
    }


def test_float32_target_parser_rejects_nonfinite_values() -> None:
    assert _float32_from_hex(np.float32(0.25).tobytes().hex()) == np.float32(0.25)
    with pytest.raises(ContractError):
        _float32_from_hex(np.float32(np.nan).tobytes().hex())


def test_training_design_is_inside_repository() -> None:
    assert DEFAULT_DESIGN.resolve().is_relative_to(ROOT.resolve())


def test_saved_training_freeze_is_complete_portable_and_outcome_closed() -> None:
    contract = load_training_freeze(DEFAULT_CONTRACT, root=ROOT)
    assert contract["status"] == "FROZEN_TRAINING_ONLY_BEFORE_STUDENT_FIT"
    assert contract["training_contract_digest"] == (
        "e2d21a930d71fe8ff276c0b3814ccaf73603fdaba02bd27cce2f400bd38a3e25"
    )
    assert contract["internal_split"]["block_counts"] == {
        "H1": {"fit": 1080, "validation": 120},
        "L1": {"fit": 1080, "validation": 120},
    }
    assert contract["internal_split"]["row_counts"] == {
        "H1": {"fit": 8640, "validation": 960},
        "L1": {"fit": 8640, "validation": 960},
    }
    assert contract["development_rows_accessed"] == []
    assert contract["confirmation_rows_accessed"] == []
    assert contract["o4b_rows_accessed"] == []
