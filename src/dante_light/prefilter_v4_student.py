"""Random-weight student proxies used only for inference-cost feasibility."""

from __future__ import annotations

import torch


class Raw1DDepthwiseStudentProxy(torch.nn.Module):
    """Tiny raw-strain proxy; this is not a trained or promotable model."""

    def __init__(self) -> None:
        super().__init__()
        self.features = torch.nn.Sequential(
            torch.nn.Conv1d(1, 8, 31, stride=8, padding=15),
            torch.nn.GELU(),
            torch.nn.Conv1d(8, 8, 15, stride=4, padding=7, groups=8),
            torch.nn.Conv1d(8, 16, 1),
            torch.nn.GELU(),
            torch.nn.Conv1d(16, 16, 9, stride=4, padding=4, groups=16),
            torch.nn.Conv1d(16, 32, 1),
            torch.nn.GELU(),
            torch.nn.Conv1d(32, 32, 7, stride=4, padding=3, groups=32),
            torch.nn.Conv1d(32, 64, 1),
            torch.nn.GELU(),
            torch.nn.AdaptiveAvgPool1d(1),
        )
        self.head = torch.nn.Linear(64, 1)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(values).squeeze(-1))


class ComplexSTFT2DStudentProxy(torch.nn.Module):
    """Tiny real/imaginary-STFT proxy; preprocessing cost must be included."""

    def __init__(self) -> None:
        super().__init__()
        self.features = torch.nn.Sequential(
            torch.nn.Conv2d(2, 8, 5, stride=4, padding=2),
            torch.nn.GELU(),
            torch.nn.Conv2d(8, 8, 3, stride=2, padding=1, groups=8),
            torch.nn.Conv2d(8, 16, 1),
            torch.nn.GELU(),
            torch.nn.Conv2d(16, 16, 3, stride=2, padding=1, groups=16),
            torch.nn.Conv2d(16, 32, 1),
            torch.nn.GELU(),
            torch.nn.AdaptiveAvgPool2d(1),
        )
        self.head = torch.nn.Linear(32, 1)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(values).flatten(1))


def trainable_parameter_count(model: torch.nn.Module) -> int:
    return int(sum(parameter.numel() for parameter in model.parameters()))
