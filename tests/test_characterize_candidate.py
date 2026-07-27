"""Focused tests for the generic independent characterization recipe."""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest
from gwpy.timeseries import TimeSeries

from src.pipeline_v2_production.characterize_candidate import (
    _load_production_coincidence,
    _loudness_summary,
    _max_signed_corr_with_lag,
    _peak_hz,
    run,
)


def test_peak_hz_uses_short_raw_asd_recipe() -> None:
    sample_rate = 1024
    time = np.arange(4 * sample_rate) / sample_rate
    strain = TimeSeries(np.sin(2 * np.pi * 28.0 * time), sample_rate=sample_rate)

    assert _peak_hz(strain, (26.0, 42.0)) == pytest.approx(28.0)


def test_signed_correlation_reports_peak_and_lag() -> None:
    rng = np.random.default_rng(7)
    sample_rate = 1024
    shift_samples = 5
    first_values = rng.normal(size=4096)
    second_values = np.zeros_like(first_values)
    second_values[shift_samples:] = first_values[:-shift_samples]
    first = TimeSeries(first_values, sample_rate=sample_rate)
    second = TimeSeries(second_values, sample_rate=sample_rate)

    correlation, lag_s = _max_signed_corr_with_lag(first, second)

    assert correlation > 0.99
    assert abs(lag_s) == pytest.approx(shift_samples / sample_rate)


def test_loudness_primary_ratio_uses_mean_not_median() -> None:
    summary = _loudness_summary(100.0, [1.0, 1.0, 10.0])

    assert summary["ratio_to_background_mean"] == pytest.approx(25.0)
    assert summary["ratio_to_background_median_diagnostic"] == pytest.approx(100.0)


def test_production_lookup_keeps_veto_fields_separate(tmp_path) -> None:
    artifact = tmp_path / "coincidence.json"
    artifact.write_text(
        json.dumps(
            {
                "summary": {"run": "O4a"},
                "events": [
                    {
                        "gps": 1382955228.0,
                        "detector": "L1",
                        "partner": "H1",
                        "t_offset_s": 24.65,
                        "f_lo": 20.0,
                        "f_hi": 66.0,
                        "cc_onsource": 0.0716,
                        "cc_null_mean": 0.197,
                        "cc_null_max": 0.286,
                        "n_null": 7,
                        "patch_iou": 0.0074,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = _load_production_coincidence(
        "L1",
        1382955228.0,
        artifact=artifact,
    )

    assert result is not None
    assert result["cc_onsource"] == pytest.approx(0.0716)
    assert "time-shift/null veto" in result["interpretation"]


def test_run_is_generic_and_does_not_hardcode_forum_candidate(
    monkeypatch,
    tmp_path,
) -> None:
    class FakeSeries:
        value = np.ones(32)
        sample_rate = SimpleNamespace(value=1024.0)

        def bandpass(self, *_band):
            return self

    monkeypatch.setattr(
        "src.pipeline_v2_production.characterize_candidate._fetch_raw",
        lambda *_args, **_kwargs: FakeSeries(),
    )
    monkeypatch.setattr(
        "src.pipeline_v2_production.characterize_candidate._descriptor_whitened",
        lambda *_args, **_kwargs: FakeSeries(),
    )
    monkeypatch.setattr(
        "src.pipeline_v2_production.characterize_candidate._peak_hz",
        lambda *_args, **_kwargs: 31.0,
    )
    monkeypatch.setattr(
        "src.pipeline_v2_production.characterize_candidate._inband_energy",
        lambda *_args, **_kwargs: 10.0,
    )
    monkeypatch.setattr(
        "src.pipeline_v2_production.characterize_candidate."
        "_max_signed_corr_with_lag",
        lambda *_args, **_kwargs: (0.1, 0.002),
    )

    result = run(
        "H1",
        2_000_000_000.0,
        2_000_000_010.0,
        band=(30.0, 40.0),
        partner="L1",
        n_background=2,
        catalog_gps=None,
        output_dir=tmp_path,
        record_provenance=False,
    )

    assert result["gps"] == 2_000_000_000.0
    assert result["feature_gps"] == 2_000_000_010.0
    assert result["band_hz"] == [30.0, 40.0]
    assert result["loudness_ratio_to_background_mean"] == pytest.approx(1.0)
    assert (tmp_path / "characterize_H1_2000000000.json").exists()
