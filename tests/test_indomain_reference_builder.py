"""Tests for src.indomain_reference_builder — all offline/mocked."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers — synthetic DataFrame matching Zenodo CSV schema
# ---------------------------------------------------------------------------


def _make_df(
    n: int = 10,
    label: str = "Blip",
    detector: str = "H1",
    confidence: float = 0.99,
    snr: float = 10.0,
    base_gps: float = 1250000000.0,
) -> pd.DataFrame:
    """Return a synthetic Gravity Spy classifications DataFrame."""
    return pd.DataFrame(
        {
            "event_time": [base_gps + i * 100 for i in range(n)],
            "ifo": [detector] * n,
            "ml_label": [label] * n,
            "ml_confidence": [confidence] * n,
            "peak_frequency": [100.0] * n,
            "snr": [snr] * n,
        }
    )


# ---------------------------------------------------------------------------
# Tests — select_reference_events
# ---------------------------------------------------------------------------


class TestSelectReferenceEvents:
    """Tests for the CSV filtering and sampling logic."""

    def test_filters_confidence(self, tmp_path: Path) -> None:
        """Only rows with ml_confidence >= min_confidence are returned."""
        from src.indomain_reference_builder import select_reference_events

        # Mix of low and high confidence
        df_low = _make_df(n=5, confidence=0.90)
        df_high = _make_df(n=5, confidence=0.99, base_gps=1250100000.0)
        df = pd.concat([df_low, df_high], ignore_index=True)
        csv_path = tmp_path / "test.csv"
        df.to_csv(csv_path, index=False)

        result = select_reference_events(csv_path, min_confidence=0.95)

        assert len(result) == 5
        assert (result["ml_confidence"] >= 0.95).all()

    def test_max_per_class(self, tmp_path: Path) -> None:
        """At most max_per_class samples are returned per label."""
        from src.indomain_reference_builder import select_reference_events

        df = _make_df(n=50, label="Blip", confidence=0.99)
        csv_path = tmp_path / "test.csv"
        df.to_csv(csv_path, index=False)

        result = select_reference_events(csv_path, max_per_class=30)

        blip_count = len(result[result["ml_label"] == "Blip"])
        assert blip_count == 30

    def test_excludes_labels(self, tmp_path: Path) -> None:
        """Entries with excluded labels are removed from results."""
        from src.indomain_reference_builder import select_reference_events

        df_good = _make_df(n=5, label="Blip")
        df_bad = _make_df(n=5, label="None_of_the_Above", base_gps=1250100000.0)
        df = pd.concat([df_good, df_bad], ignore_index=True)
        csv_path = tmp_path / "test.csv"
        df.to_csv(csv_path, index=False)

        result = select_reference_events(csv_path)

        assert "None_of_the_Above" not in result["ml_label"].values
        assert len(result) == 5

    def test_filters_snr(self, tmp_path: Path) -> None:
        """Only rows with snr >= 7.5 are returned."""
        from src.indomain_reference_builder import select_reference_events

        df_low = _make_df(n=3, snr=5.0)
        df_high = _make_df(n=3, snr=10.0, base_gps=1250100000.0)
        df = pd.concat([df_low, df_high], ignore_index=True)
        csv_path = tmp_path / "test.csv"
        df.to_csv(csv_path, index=False)

        result = select_reference_events(csv_path)

        assert len(result) == 3
        assert (result["snr"] >= 7.5).all()


# ---------------------------------------------------------------------------
# Tests — build_indomain_reference
# ---------------------------------------------------------------------------


class TestBuildIndomainReference:
    """Tests for the end-to-end reference build (all I/O mocked)."""

    @patch("src.indomain_reference_builder.DINOv2Encoder")
    @patch("src.indomain_reference_builder.generate_qtransform")
    @patch("src.indomain_reference_builder.bandpass")
    @patch("src.indomain_reference_builder.whiten")
    @patch("src.indomain_reference_builder.fetch_strain_data")
    def test_skips_failed_fetch(
        self,
        mock_fetch: MagicMock,
        mock_whiten: MagicMock,
        mock_bandpass: MagicMock,
        mock_qt: MagicMock,
        mock_encoder_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Failed fetch_strain_data calls are skipped (warning logged, no crash)."""
        from src.indomain_reference_builder import build_indomain_reference

        # 5 events — 2 will fail
        df = _make_df(n=5, label="Blip")

        # First two fetches fail, rest succeed
        mock_ts = MagicMock()
        mock_fetch.side_effect = [
            RuntimeError("GWOSC timeout"),
            RuntimeError("No data"),
            mock_ts,
            mock_ts,
            mock_ts,
        ]
        mock_whiten.return_value = mock_ts
        mock_bandpass.return_value = mock_ts
        mock_qt.return_value = np.zeros((256, 256))

        # Mock encoder — returns (N, 384) embeddings
        mock_encoder = MagicMock()
        mock_encoder.extract_batch.return_value = np.random.randn(3, 384).astype(
            np.float32
        )
        mock_encoder_cls.return_value = mock_encoder

        output_path = tmp_path / "ref.npz"
        meta = build_indomain_reference(df, output_path)

        # Only 3 succeeded
        assert meta["n_samples"] == 3
        assert mock_fetch.call_count == 5
        # No crash — the function returned normally

    @patch("src.indomain_reference_builder.DINOv2Encoder")
    @patch("src.indomain_reference_builder.generate_qtransform")
    @patch("src.indomain_reference_builder.bandpass")
    @patch("src.indomain_reference_builder.whiten")
    @patch("src.indomain_reference_builder.fetch_strain_data")
    def test_npz_and_json_format(
        self,
        mock_fetch: MagicMock,
        mock_whiten: MagicMock,
        mock_bandpass: MagicMock,
        mock_qt: MagicMock,
        mock_encoder_cls: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Saved .npz has required keys; companion .json has class_distribution."""
        from src.indomain_reference_builder import build_indomain_reference

        # 4 events: 2 Blip + 2 Koi_Fish
        df_a = _make_df(n=2, label="Blip")
        df_b = _make_df(n=2, label="Koi_Fish", base_gps=1250100000.0)
        df = pd.concat([df_a, df_b], ignore_index=True)

        mock_ts = MagicMock()
        mock_fetch.return_value = mock_ts
        mock_whiten.return_value = mock_ts
        mock_bandpass.return_value = mock_ts
        mock_qt.return_value = np.zeros((256, 256))

        mock_encoder = MagicMock()
        mock_encoder.extract_batch.return_value = np.random.randn(4, 384).astype(
            np.float32
        )
        mock_encoder_cls.return_value = mock_encoder

        output_path = tmp_path / "ref.npz"
        meta = build_indomain_reference(df, output_path)

        # Check .npz keys
        data = np.load(output_path, allow_pickle=True)
        assert "embeddings" in data
        assert "labels" in data
        assert "gps_times" in data
        assert "image_paths" in data
        assert data["embeddings"].shape == (4, 384)

        # Check companion .json
        json_path = output_path.with_suffix(".json")
        assert json_path.exists()
        with open(json_path) as f:
            jmeta = json.load(f)
        assert "class_distribution" in jmeta
        assert jmeta["n_samples"] == 4
        assert jmeta["n_classes"] == 2
