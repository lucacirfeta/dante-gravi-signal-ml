"""Detector-specific chronological drift alarms with no automatic adaptation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

import numpy as np

from src.dante_light.contracts import ContractError


class DriftState(str, Enum):
    OK = "OK"
    ALERT = "ALERT"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class DriftContract:
    detector: str
    reference_median: float
    reference_mad: float
    median_shift_limit_mad: float = 5.0
    tail_rate_limit: float = 0.03
    tail_threshold: float = 0.0
    minimum_block_size: int = 64

    def __post_init__(self) -> None:
        if self.reference_mad <= 0 or not math.isfinite(self.reference_mad):
            raise ContractError("reference_mad must be finite and positive")
        if self.minimum_block_size <= 0:
            raise ContractError("minimum_block_size must be positive")
        if not 0.0 <= self.tail_rate_limit <= 1.0:
            raise ContractError("tail_rate_limit must be in [0,1]")


@dataclass(frozen=True, slots=True)
class DriftResult:
    state: DriftState
    n: int
    median: float | None
    median_shift_mad: float | None
    tail_rate: float | None
    freeze_adaptation: bool


def evaluate_score_block(
    scores: np.ndarray, contract: DriftContract
) -> DriftResult:
    values = np.asarray(scores, dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise ContractError("drift block must be finite and one-dimensional")
    if values.size < contract.minimum_block_size:
        return DriftResult(
            DriftState.INSUFFICIENT,
            int(values.size),
            None,
            None,
            None,
            True,
        )
    median = float(np.median(values))
    shift = abs(median - contract.reference_median) / contract.reference_mad
    tail_rate = float(np.mean(values > contract.tail_threshold))
    alert = (
        shift > contract.median_shift_limit_mad
        or tail_rate > contract.tail_rate_limit
    )
    return DriftResult(
        DriftState.ALERT if alert else DriftState.OK,
        int(values.size),
        median,
        float(shift),
        tail_rate,
        alert,
    )
