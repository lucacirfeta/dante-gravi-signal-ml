"""Production phase-aware feature contract for DANTE-Light L4 v4."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np

from src.dante_light.contracts import ContractError
from src.dante_light.prefilter_v4_phase import extract_phase_feasibility_features
from src.dante_light.prefilter_v4_protocol import PHASE_FEATURES


@dataclass(frozen=True, slots=True)
class PrefilterFeaturesV4:
    values: dict[str, float]

    def __post_init__(self) -> None:
        if tuple(self.values) != PHASE_FEATURES:
            raise ContractError("v4 phase feature order/schema mismatch")
        clean = {name: float(value) for name, value in self.values.items()}
        if not all(math.isfinite(value) for value in clean.values()):
            raise ContractError("v4 phase feature vector contains non-finite values")
        object.__setattr__(self, "values", clean)


def extract_prefilter_v4_features(
    whitened: np.ndarray,
    *,
    config: Mapping[str, Any],
) -> PrefilterFeaturesV4:
    """Extract the frozen six-feature primary from a clean whitened window."""

    values = np.asarray(whitened, dtype=np.float64)
    sample_rate = int(config["sample_rate_hz"])
    expected = int(round(float(config.get("analysis_duration_s", 32.0)) * sample_rate))
    if values.ndim != 1 or abs(values.size - expected) > 1:
        raise ContractError(f"v4 phase extractor requires a 32 s 1-D window: {values.shape}")
    extracted = extract_phase_feasibility_features(
        values,
        sample_rate_hz=sample_rate,
        analysis_band_hz=config["analysis_band_hz"],
        config=config["phase_parameters"],
    )
    ordered = {name: extracted[name] for name in PHASE_FEATURES}
    if set(extracted) != set(PHASE_FEATURES):
        raise ContractError("v4 phase formula returned an unexpected schema")
    return PrefilterFeaturesV4(ordered)
