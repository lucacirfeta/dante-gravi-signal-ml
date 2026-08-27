from __future__ import annotations

import numpy as np
import pytest
import torch

from src.dante_light.prefilter_v5_protocol import ROOT
from src.dante_light.prefilter_v6_training import (
    BlockBatch,
    _checkpoint_better,
    _model,
    train_replicate,
)


def test_v6_training_builds_every_frozen_architecture() -> None:
    expected = {
        "raw_v5_global_average",
        "raw_teacher_top_fraction",
        "raw_attention_mil",
        "raw_teacher_top_fraction_x2",
    }
    for architecture_id in expected:
        model = _model(ROOT, architecture_id)
        with torch.no_grad():
            output = model(torch.zeros(2, 1, 131072, dtype=torch.float32))
        assert output.shape == (2, 1)
        assert torch.isfinite(output).all()


def test_v6_checkpoint_selection_uses_worst_detector_then_value_loss() -> None:
    incumbent = {
        "minimum_detector_spearman": 0.8,
        "equal_detector_mean_smooth_l1": 0.2,
    }
    assert _checkpoint_better(
        {
            "minimum_detector_spearman": 0.81,
            "equal_detector_mean_smooth_l1": 0.4,
        },
        incumbent,
    )
    assert _checkpoint_better(
        {
            "minimum_detector_spearman": 0.8,
            "equal_detector_mean_smooth_l1": 0.19,
        },
        incumbent,
    )
    assert not _checkpoint_better(dict(incumbent), incumbent)


@pytest.mark.parametrize(
    "objective_id", ["smooth_l1", "equal_gradient_smooth_l1_ranknet"]
)
def test_v6_replicate_smoke_executes_frozen_objectives(
    tmp_path, monkeypatch: pytest.MonkeyPatch, objective_id: str
) -> None:
    class TinyStudent(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.linear = torch.nn.Linear(16, 1)

        def forward(self, values: torch.Tensor) -> torch.Tensor:
            return self.linear(values.squeeze(1))

    class FakeCache:
        def block_indices(self, subset: str):
            return {"H1": [0, 1, 2, 3], "L1": [4, 5, 6, 7]}

        def load_batch(self, h1_blocks, l1_blocks):
            block_count = len(h1_blocks) + len(l1_blocks)
            targets = np.tile(np.linspace(-1.0, 1.0, 8, dtype=np.float32), block_count)
            strain = np.stack(
                [np.linspace(-0.5, 0.5, 16, dtype=np.float32) + value for value in targets]
            )
            return BlockBatch(
                strain=strain,
                targets=targets,
                detectors=np.repeat(np.asarray([0, 1], dtype=np.int8), len(h1_blocks) * 8),
                block_indices=np.repeat(np.asarray(list(h1_blocks) + list(l1_blocks)), 8),
                window_ids=tuple(f"window-{index}" for index in range(targets.size)),
            )

    monkeypatch.setattr(
        "src.dante_light.prefilter_v6_training._model", lambda *_args, **_kwargs: TinyStudent()
    )
    contract = {
        "optimization": {
            "optimizer": {
                "learning_rate": 1e-3,
                "weight_decay": 1e-4,
                "betas": [0.9, 0.999],
                "epsilon": 1e-8,
                "amsgrad": False,
            },
            "batch": {"blocks_per_detector": 4},
            "maximum_epochs": 100,
        },
        "objective": {"value": {"beta": 1.0}},
    }
    summary = train_replicate(
        root=ROOT,
        contract=contract,
        cache=FakeCache(),
        run_dir=tmp_path,
        run_key="a" * 64,
        arm={
            "id": f"arm-{objective_id}",
            "architecture_id": "tiny",
            "objective_id": objective_id,
        },
        replicate_index=0,
        seed=123,
        device=torch.device("cpu"),
        smoke=True,
        limit_batches=1,
    )
    assert summary["status"] == "SMOKE_COMPLETE_NON_PROMOTABLE"
    assert summary["completed_epochs"] == 1
    assert summary["best_validation"]["by_detector"]["H1"]["n"] == 32
