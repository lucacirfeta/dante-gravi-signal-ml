"""Synthetic audit of the frozen PEM max-statistic bootstrap unit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from src.pipeline_v2_production import pem_null_calibration as null


def test_familywise_null_bootstraps_window_indices_not_pairs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    channels = [f"H1:SYNTHETIC_{index}" for index in range(5)]
    starts = np.arange(60, dtype=np.float64) * null.STRIDE_S
    generator = np.random.default_rng(42)
    transforms = {
        name: (
            generator.standard_normal((60, null.N_WELCH, 2))
            + 1j * generator.standard_normal((60, null.N_WELCH, 2))
        ).astype(np.complex64)
        for name in ["H1:STRAIN", *channels]
    }
    monkeypatch.setattr(
        null,
        "_pick_background_span",
        lambda *args, **kwargs: (0, 14400, starts),
    )
    monkeypatch.setattr(
        null,
        "fetch_strain_data",
        lambda *args: SimpleNamespace(
            name="H1:STRAIN", sample_rate=SimpleNamespace(value=1024)
        ),
    )
    monkeypatch.setattr(
        null,
        "_fetch_aux_block",
        lambda channel, *args, **kwargs: SimpleNamespace(
            name=channel, sample_rate=SimpleNamespace(value=1024)
        ),
    )
    monkeypatch.setattr(
        null,
        "_window_segment_ffts",
        lambda series, *args: (transforms[series.name], np.array([20.0, 21.0])),
    )

    class RecordingGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int]] = []

        def integers(self, low: int, high: int, *, size: int) -> np.ndarray:
            self.calls.append((low, high, size))
            return np.arange(size)

    recorder = RecordingGenerator()
    monkeypatch.setattr(null.np.random, "default_rng", lambda seed: recorder)
    result = null.calibrate_event(
        "H1",
        100.0,
        channels,
        run="O3a",
        block_s=14400,
        alpha=0.01,
        n_boot=3,
        seed=42,
        pem_dir=tmp_path,
        candidate_gps=np.array([10.0, 20.0]),
        candidate_exclusion_digest="synthetic-exclusion",
    )
    assert result["channels"] == channels
    assert result["m_channels"] == 5
    assert result["n_windows"] == 60
    assert result["n_surrogate_pairs"] == 60 * 59
    assert recorder.calls == [(0, 60, 60)] * 3
    assert result["threshold_fw_ci95"] == (
        result["threshold_fw"],
        result["threshold_fw"],
    )
