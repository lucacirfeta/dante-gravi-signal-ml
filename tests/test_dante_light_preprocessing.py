from __future__ import annotations

import hashlib

import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from src.dante_light.contracts import WindowIdentity
from src.dante_light.preprocessing import stage_canonical_strain


def test_stage_canonical_strain_fetches_context_and_hashes(monkeypatch) -> None:
    window = WindowIdentity("O4B", "H1", 1400000000, duration_s=32.0)
    values = np.arange(40 * 4096, dtype=np.float64)
    calls = []

    def fetch(detector, start, end, **kwargs):
        calls.append((detector, start, end, kwargs))
        return TimeSeries(values, sample_rate=4096, t0=start)

    monkeypatch.setattr("src.core.data_loader.fetch_strain_data", fetch)
    result = stage_canonical_strain(
        window, local_only=False, remote_only=True
    )
    assert calls == [
        (
            "H1",
            window.gps_start - 4.0,
            window.gps_start + 36.0,
            {"local_only": False, "remote_only": True},
        )
    ]
    assert result["samples"] == values.size
    assert result["strain_sha256"] == hashlib.sha256(values.tobytes()).hexdigest()


def test_stage_canonical_strain_rejects_incomplete_context(monkeypatch) -> None:
    window = WindowIdentity("O4B", "L1", 1400000000, duration_s=32.0)

    def fetch(_detector, start, _end, **_kwargs):
        return TimeSeries(np.zeros(39 * 4096), sample_rate=4096, t0=start)

    monkeypatch.setattr("src.core.data_loader.fetch_strain_data", fetch)
    with pytest.raises(RuntimeError, match="does not cover"):
        stage_canonical_strain(window, local_only=False, remote_only=True)


def test_stage_canonical_strain_rejects_nonfinite_input(monkeypatch) -> None:
    window = WindowIdentity("O4B", "H1", 1400000000, duration_s=32.0)
    values = np.zeros(40 * 4096)
    values[0] = np.nan

    def fetch(_detector, start, _end, **_kwargs):
        return TimeSeries(values, sample_rate=4096, t0=start)

    monkeypatch.setattr("src.core.data_loader.fetch_strain_data", fetch)
    with pytest.raises(RuntimeError, match="non-finite"):
        stage_canonical_strain(window, local_only=False, remote_only=True)
