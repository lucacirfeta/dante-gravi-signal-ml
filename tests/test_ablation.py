"""Tests for src.ablation — image perturbations and ablation study.

All tests use synthetic data and mocked DINOv2 encoder — no GPU or
real spectrogram files needed.

Run:  pytest tests/test_ablation.py -v
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from src.pipeline_v1_legacy.ablation import apply_perturbation, run_ablation_study


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rgb_image(w: int = 64, h: int = 64, seed: int = 0) -> Image.Image:
    """Return a reproducible RGB PIL image."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    return Image.fromarray(arr, mode="RGB")


# ---------------------------------------------------------------------------
# apply_perturbation
# ---------------------------------------------------------------------------


class TestApplyPerturbation:
    """Validate each perturbation mode individually."""

    def test_grayscale_returns_rgb_image(self) -> None:
        """Grayscale mode should return an RGB image (not L mode)."""
        img = _make_rgb_image()
        out = apply_perturbation(img, "grayscale")
        assert out.mode == "RGB"

    def test_grayscale_reduces_channel_variance(self) -> None:
        """Grayscale image R==G==B for every pixel."""
        img = _make_rgb_image()
        out = apply_perturbation(img, "grayscale")
        arr = np.array(out)
        np.testing.assert_array_equal(arr[:, :, 0], arr[:, :, 1])
        np.testing.assert_array_equal(arr[:, :, 1], arr[:, :, 2])

    def test_inverted_pixel_values(self) -> None:
        """Inverted pixel values should satisfy original + inverted == 255."""
        img = _make_rgb_image(seed=7)
        orig = np.array(img.convert("RGB"), dtype=np.int32)
        out = apply_perturbation(img, "inverted")
        inv = np.array(out, dtype=np.int32)
        np.testing.assert_array_equal(orig + inv, np.full_like(orig, 255))

    def test_shuffled_intensity_same_shape(self) -> None:
        """Shuffled-intensity output must have same shape as input."""
        img = _make_rgb_image()
        out = apply_perturbation(img, "shuffled-intensity")
        assert np.array(out).shape == np.array(img.convert("RGB")).shape

    def test_shuffled_intensity_pixels_clipped(self) -> None:
        """Shuffled-intensity pixels must remain in [0, 255]."""
        img = _make_rgb_image()
        out = apply_perturbation(img, "shuffled-intensity")
        arr = np.array(out)
        assert arr.min() >= 0
        assert arr.max() <= 255

    def test_unknown_method_raises(self) -> None:
        """Unknown perturbation method must raise ValueError."""
        img = _make_rgb_image()
        with pytest.raises(ValueError, match="Unknown perturbation method"):
            apply_perturbation(img, "nonexistent-method")


# ---------------------------------------------------------------------------
# run_ablation_study
# ---------------------------------------------------------------------------


class TestRunAblationStudy:
    """Smoke-test run_ablation_study with mocked encoder and clustering."""

    @pytest.fixture()
    def tmp_png_dir(self, tmp_path: Path) -> Path:
        """Create 10 tiny PNG files in a temp directory."""
        png_dir = tmp_path / "spectrograms"
        png_dir.mkdir()
        for i in range(10):
            img = _make_rgb_image(seed=i)
            img.save(png_dir / f"H1_{1000000 + i * 32}_{1000032 + i * 32}.png")
        return png_dir

    def _make_mock_encoder(self, n: int) -> MagicMock:
        """Return a mock DINOv2Encoder that yields random 384-dim embeddings."""
        encoder = MagicMock()
        encoder.device = MagicMock(type="cpu")
        encoder.batch_size = 32
        # transform() returns a (1, 3, H, W) tensor-like; encode_batch returns (n, 384)
        import torch
        encoder.transform.side_effect = lambda img: torch.zeros(3, 224, 224)
        # model() returns (n, 384)
        encoder.model.side_effect = lambda x: torch.from_numpy(
            np.random.default_rng(42).standard_normal((x.shape[0], 384)).astype(np.float32)
        )
        return encoder

    @patch("src.ablation.DINOv2Encoder")
    @patch("src.ablation.extract_perturbed_embeddings")
    @patch("src.ablation.run_full_pipeline")
    def test_ablation_creates_report(
        self,
        mock_pipeline: MagicMock,
        mock_extract: MagicMock,
        mock_encoder_cls: MagicMock,
        tmp_png_dir: Path,
        tmp_path: Path,
    ) -> None:
        """run_ablation_study must write ablation_report_H1.json with correct keys."""
        n = 10

        # Mock pipeline always returns a stable cluster label array
        rng = np.random.default_rng(42)
        fake_labels = rng.integers(0, 3, size=n)
        mock_pipeline.return_value = {
            "labels": fake_labels,
            "hdbscan_stats": {"n_clusters": 3, "cluster_sizes": {0: 4, 1: 3, 2: 3}},
            "cluster_stats": {"n_clusters": 3, "cluster_sizes": {0: 4, 1: 3, 2: 3},
                              "n_noise": 0, "noise_ratio": 0.0,
                              "largest_cluster": 4, "smallest_cluster": 3},
            "anomalous_clusters": [],
            "anomalous_samples": [],
            "umap_2d": rng.standard_normal((n, 2)).astype(np.float32),
            "umap_10d": rng.standard_normal((n, 10)).astype(np.float32),
            "pca_variance": 0.95,
            "silhouette_umap": None, "silhouette_pca": None,
            "davies_bouldin_umap": None, "davies_bouldin_pca": None,
        }

        # Mock extract_perturbed_embeddings to return random embeddings
        mock_extract.return_value = rng.standard_normal((n, 384)).astype(np.float32)

        # Mock encoder instance (used only for batch_size)
        encoder_instance = MagicMock()
        encoder_instance.batch_size = 32
        mock_encoder_cls.return_value = encoder_instance

        image_paths = list(sorted(tmp_png_dir.glob("H1_*.png")))
        original_labels = fake_labels

        output_dir = tmp_path / "ablation"
        cluster_cfg = {
            "algorithm": "dpmm",
            "pca_components": 10,
            "random_state": 42,
            "dpmm": {"n_components": 5, "anomaly_percentile": 5.0, "anomaly_threshold": -100.0},
            "umap_clustering": {"n_components": 3, "n_neighbors": 5, "min_dist": 0.0, "metric": "cosine"},
            "umap_viz": {"n_components": 2, "n_neighbors": 5, "min_dist": 0.1, "metric": "cosine"},
        }

        run_ablation_study(
            original_labels=original_labels,
            image_paths=image_paths,
            cluster_cfg=cluster_cfg,
            output_dir=output_dir,
            session_id="test_session",
            detector="H1",
            gpu_lock=threading.Lock(),
            batch_size=32,
        )

        report_path = output_dir / "ablation_report_H1.json"
        assert report_path.exists(), "ablation_report_H1.json was not created"

        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)

        assert report["session_id"] == "test_session"
        assert report["detector"] == "H1"
        assert "results" in report
        expected_conditions = {"grayscale", "inverted", "shuffled-intensity", "random-baseline"}
        assert set(report["results"].keys()) == expected_conditions
        for cond, data in report["results"].items():
            assert "ari" in data, f"Missing 'ari' for condition {cond}"
            assert isinstance(data["ari"], float)
        assert "interpretation" in report

    @patch("src.ablation.DINOv2Encoder")
    @patch("src.ablation.extract_perturbed_embeddings")
    @patch("src.ablation.run_full_pipeline")
    def test_ablation_random_baseline_uses_random_embeddings(
        self,
        mock_pipeline: MagicMock,
        mock_extract: MagicMock,
        mock_encoder_cls: MagicMock,
        tmp_png_dir: Path,
        tmp_path: Path,
    ) -> None:
        """random-baseline condition should not call extract_perturbed_embeddings."""
        n = 10
        rng = np.random.default_rng(0)
        fake_labels = rng.integers(0, 2, size=n)
        mock_pipeline.return_value = {
            "labels": fake_labels,
            "hdbscan_stats": {"n_clusters": 2, "cluster_sizes": {0: 5, 1: 5}},
            "cluster_stats": {"n_clusters": 2, "cluster_sizes": {0: 5, 1: 5},
                              "n_noise": 0, "noise_ratio": 0.0,
                              "largest_cluster": 5, "smallest_cluster": 5},
            "anomalous_clusters": [], "anomalous_samples": [],
            "umap_2d": rng.standard_normal((n, 2)).astype(np.float32),
            "umap_10d": rng.standard_normal((n, 5)).astype(np.float32),
            "pca_variance": 0.90,
            "silhouette_umap": None, "silhouette_pca": None,
            "davies_bouldin_umap": None, "davies_bouldin_pca": None,
        }
        mock_extract.return_value = rng.standard_normal((n, 384)).astype(np.float32)

        encoder_instance = MagicMock()
        encoder_instance.batch_size = 32
        mock_encoder_cls.return_value = encoder_instance

        image_paths = list(sorted(tmp_png_dir.glob("H1_*.png")))
        cluster_cfg = {
            "algorithm": "dpmm",
            "pca_components": 5,
            "random_state": 42,
            "dpmm": {"n_components": 3, "anomaly_percentile": 5.0, "anomaly_threshold": -100.0},
            "umap_clustering": {"n_components": 2, "n_neighbors": 3, "min_dist": 0.0},
            "umap_viz": {"n_components": 2, "n_neighbors": 3, "min_dist": 0.1},
        }

        output_dir = tmp_path / "ablation2"
        run_ablation_study(
            original_labels=fake_labels,
            image_paths=image_paths,
            cluster_cfg=cluster_cfg,
            output_dir=output_dir,
            session_id="test2",
            detector="H1",
        )

        report_path = output_dir / "ablation_report_H1.json"
        assert report_path.exists()
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
        # random-baseline should always appear in results
        assert "random-baseline" in report["results"]
        # extract_perturbed_embeddings should be called for non-random conditions only
        assert mock_extract.call_count == 3  # grayscale, inverted, shuffled-intensity
