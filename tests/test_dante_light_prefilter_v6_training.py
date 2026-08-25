from __future__ import annotations

import torch

from src.dante_light.prefilter_v5_protocol import ROOT
from src.dante_light.prefilter_v6_training import _checkpoint_better, _model


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
