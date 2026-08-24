from __future__ import annotations

import json

import numpy as np
import pytest
import torch

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v5_protocol import ROOT
from src.dante_light.prefilter_v5_training import (
    NumericalTrainingFailure,
    _finite_tensor,
    _model,
    _optimizer,
    epoch_block_batches,
    student_input,
    training_run_key,
)
from src.dante_light.prefilter_v5_training_contract import load_training_freeze


def _contract() -> dict:
    return load_training_freeze(root=ROOT)


def _stft_contract() -> dict:
    protocol = json.loads(
        (ROOT / "config/dante_light_prefilter_protocol_v5.json").read_text(
            encoding="utf-8"
        )
    )
    return protocol["approved_design"]["students"]["complex_stft_2d"]["stft"]


def test_epoch_batches_are_balanced_deterministic_and_epoch_specific() -> None:
    blocks = {detector: list(range(12)) for detector in ("H1", "L1")}
    kwargs = {
        "block_indices": blocks,
        "seed": 123456789012345,
        "blocks_per_detector_batch": 4,
        "shuffle": True,
    }
    first = epoch_block_batches(epoch=1, **kwargs)
    second = epoch_block_batches(epoch=1, **kwargs)
    later = epoch_block_batches(epoch=2, **kwargs)
    assert first == second
    assert first != later
    assert len(first) == 3
    assert all(len(h1) == len(l1) == 4 for h1, l1 in first)
    assert sorted(value for batch in first for value in batch[0]) == list(range(12))
    assert sorted(value for batch in first for value in batch[1]) == list(range(12))


def test_epoch_batches_reject_unfilled_frozen_batch() -> None:
    with pytest.raises(ContractError):
        epoch_block_batches(
            {"H1": list(range(10)), "L1": list(range(10))},
            seed=1,
            epoch=1,
            blocks_per_detector_batch=4,
            shuffle=True,
        )


def test_student_inputs_match_frozen_shapes_and_float32() -> None:
    strain = np.zeros((2, 32 * 4096), dtype=np.float32)
    stft = _stft_contract()
    raw = student_input(strain, arm="raw_1d_depthwise", stft_contract=stft)
    complex_stft = student_input(
        strain, arm="complex_stft_2d", stft_contract=stft
    )
    assert raw.shape == (2, 1, 131072)
    assert complex_stft.shape == (2, 2, 252, 255)
    assert raw.dtype == complex_stft.dtype == torch.float32


def test_student_input_and_tensor_checks_fail_on_nonfinite_values() -> None:
    strain = np.zeros((1, 1024), dtype=np.float32)
    strain[0, 5] = np.nan
    with pytest.raises(NumericalTrainingFailure):
        student_input(
            strain,
            arm="raw_1d_depthwise",
            stft_contract=_stft_contract(),
        )
    with pytest.raises(NumericalTrainingFailure):
        _finite_tensor(torch.tensor([float("inf")]), "test")


def test_optimizer_is_fixed_adamw_without_scheduler_or_clipping() -> None:
    contract = _contract()
    model = _model("raw_1d_depthwise")
    optimizer = _optimizer(model, contract["design"])
    group = optimizer.param_groups[0]
    assert isinstance(optimizer, torch.optim.AdamW)
    assert group["lr"] == 0.001
    assert group["weight_decay"] == 0.0001
    assert group["betas"] == (0.9, 0.999)
    assert contract["design"]["optimization"]["scheduler"]["name"] == "none"
    assert contract["design"]["optimization"]["gradient_clipping"] is False


def test_training_run_key_binds_code_environment_and_smoke_scope() -> None:
    contract = _contract()
    references = {"training": {"path": "x", "sha256": "a" * 64}}
    environment = {"torch": "test", "device_type": "cpu"}
    full = training_run_key(
        contract,
        code_references=references,
        environment=environment,
        smoke=False,
        smoke_batches=None,
    )
    smoke = training_run_key(
        contract,
        code_references=references,
        environment=environment,
        smoke=True,
        smoke_batches=1,
    )
    changed = training_run_key(
        contract,
        code_references=references,
        environment={**environment, "device_type": "cuda"},
        smoke=False,
        smoke_batches=None,
    )
    assert len({full, smoke, changed}) == 3


def test_training_contract_keeps_all_protected_partitions_closed() -> None:
    contract = _contract()
    assert contract["development_rows_accessed"] == []
    assert contract["confirmation_rows_accessed"] == []
    assert contract["o4b_rows_accessed"] == []
    assert contract["design"]["scope"]["morphology_labels_allowed"] is False
