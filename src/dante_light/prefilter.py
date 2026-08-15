"""Research-only cheap trigger features and promotion guard."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math

import numpy as np

from src.dante_light.contracts import ContractError, LightDisposition, WindowIdentity


@dataclass(frozen=True, slots=True)
class ExcessEnergyFeatures:
    rms: float
    crest_factor: float
    peak_band_fraction: float
    high_quantile_power: float

    def __post_init__(self) -> None:
        for name in ("rms", "crest_factor", "peak_band_fraction", "high_quantile_power"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ContractError(f"non-finite prefilter feature {name}")
            object.__setattr__(self, name, value)


def extract_excess_energy_features(
    whitened: np.ndarray,
    *,
    sample_rate_hz: int = 4096,
    band_hz: tuple[float, float] = (20.0, 1024.0),
) -> ExcessEnergyFeatures:
    values = np.asarray(whitened, dtype=np.float64)
    if values.ndim != 1 or values.size < sample_rate_hz:
        raise ContractError("prefilter expects at least one second of 1D strain")
    if not np.all(np.isfinite(values)):
        raise ContractError("prefilter strain contains non-finite samples")
    rms = float(np.sqrt(np.mean(values * values)))
    crest = 0.0 if rms == 0.0 else float(np.max(np.abs(values)) / rms)
    spectrum = np.abs(np.fft.rfft(values)) ** 2
    frequencies = np.fft.rfftfreq(values.size, 1.0 / sample_rate_hz)
    selected = spectrum[(frequencies >= band_hz[0]) & (frequencies <= band_hz[1])]
    if selected.size == 0 or float(selected.sum()) == 0.0:
        fraction = 0.0
        high_quantile = 0.0
    else:
        fraction = float(selected.max() / selected.sum())
        high_quantile = float(np.quantile(selected, 0.999) / np.median(selected + 1e-30))
    return ExcessEnergyFeatures(rms, crest, fraction, high_quantile)


@dataclass(frozen=True, slots=True)
class PrefilterContract:
    contract_id: str
    status: str
    crest_threshold: float
    band_fraction_threshold: float
    audit_fraction: float
    seed: int

    def __post_init__(self) -> None:
        if self.status not in {"research_only", "promoted"}:
            raise ContractError("prefilter status must be research_only or promoted")
        if not 0.0 <= float(self.audit_fraction) <= 1.0:
            raise ContractError("audit_fraction must be in [0,1]")
        if float(self.crest_threshold) <= 0 or float(self.band_fraction_threshold) <= 0:
            raise ContractError("prefilter thresholds must be positive")

    def would_escalate(self, features: ExcessEnergyFeatures) -> bool:
        return (
            features.crest_factor >= self.crest_threshold
            or features.peak_band_fraction >= self.band_fraction_threshold
        )

    def audit_selected(self, window: WindowIdentity) -> bool:
        digest = hashlib.sha256(
            f"{self.seed}:{window.window_id}".encode("ascii")
        ).digest()
        uniform = int.from_bytes(digest[:8], "big") / float(2**64)
        return uniform < self.audit_fraction

    def route(
        self, window: WindowIdentity, features: ExcessEnergyFeatures
    ) -> LightDisposition:
        if self.status != "promoted":
            raise ContractError(
                "research-only prefilter cannot change scientific selection"
            )
        if self.would_escalate(features):
            return LightDisposition.ESCALATE
        if self.audit_selected(window):
            return LightDisposition.AUDIT_SAMPLE
        return LightDisposition.NOT_ESCALATED
