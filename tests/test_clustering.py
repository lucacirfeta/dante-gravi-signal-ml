"""Tests for src.clustering — PCA → UMAP → HDBSCAN clustering pipeline.

All tests use synthetic data — no real embeddings or model downloads needed.

Run:  pytest tests/test_clustering.py -v
"""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.datasets import make_blobs

from src.pipeline_v1_legacy.clustering import (
    identify_anomalous_clusters,
    run_full_pipeline,
    run_hdbscan,
    run_pca,
    run_umap,
)


# =====================================================================
# PCA
# =====================================================================


class TestRunPCA:
    """Validate PCA dimensionality reduction."""

    def test_run_pca_shape(self) -> None:
        """PCA(50) on (100, 384) → output shape (100, 50)."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal((100, 384)).astype(np.float32)

        reduced, variance = run_pca(data, n_components=50)

        assert reduced.shape == (100, 50)
        assert 0.0 < variance < 1.0


# =====================================================================
# UMAP
# =====================================================================


class TestRunUMAP:
    """Validate UMAP dimensionality reduction."""

    def test_run_umap_10d_shape(self) -> None:
        """UMAP to 10D: (100, 50) → (100, 10)."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal((100, 50)).astype(np.float32)

        result = run_umap(data, n_components=10, n_neighbors=15)
        assert result.shape == (100, 10)

    def test_run_umap_2d_shape(self) -> None:
        """UMAP to 2D: (100, 50) → (100, 2)."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal((100, 50)).astype(np.float32)

        result = run_umap(data, n_components=2, n_neighbors=15)
        assert result.shape == (100, 2)


# =====================================================================
# HDBSCAN
# =====================================================================


class TestRunHDBSCAN:
    """Validate HDBSCAN clustering."""

    def test_run_hdbscan_returns_labels(self) -> None:
        """HDBSCAN on make_blobs(100, 10, centers=5) finds >= 1 cluster."""
        data, _ = make_blobs(
            n_samples=200, n_features=10, centers=5, random_state=42
        )

        labels, stats = run_hdbscan(
            data.astype(np.float32),
            min_cluster_size=15,
            min_samples=10,
        )

        assert labels.shape == (200,)
        assert stats["n_clusters"] >= 1
        assert stats["n_noise"] >= 0
        assert 0.0 <= stats["noise_ratio"] <= 1.0
        assert isinstance(stats["cluster_sizes"], dict)


# =====================================================================
# Anomaly identification
# =====================================================================


class TestIdentifyAnomalousClusters:
    """Validate anomalous cluster detection."""

    def test_identify_anomalous_clusters(self) -> None:
        """Clusters with size <= threshold are flagged as anomalous."""
        labels = np.array([0] * 50 + [1] * 8 + [2] * 3)
        stats = {
            "cluster_sizes": {0: 50, 1: 8, 2: 3},
        }

        anomalous = identify_anomalous_clusters(
            labels, stats, small_cluster_threshold=10
        )

        assert anomalous == [1, 2]

    def test_no_anomalous_clusters(self) -> None:
        """No clusters flagged when all exceed threshold."""
        labels = np.array([0] * 50 + [1] * 30)
        stats = {
            "cluster_sizes": {0: 50, 1: 30},
        }

        anomalous = identify_anomalous_clusters(
            labels, stats, small_cluster_threshold=10
        )

        assert anomalous == []


# =====================================================================
# Full pipeline smoke test
# =====================================================================


class TestFullPipelineSmoke:
    """Smoke test: full pipeline completes on small synthetic data."""

    def test_full_pipeline_smoke(self) -> None:
        """run_full_pipeline on (80, 384) completes and returns all keys."""
        rng = np.random.default_rng(42)
        data = rng.standard_normal((80, 384)).astype(np.float32)

        config = {
            "pca_components": 30,
            "umap_clustering": {
                "n_components": 5,
                "n_neighbors": 10,
                "min_dist": 0.0,
                "metric": "cosine",
            },
            "umap_viz": {
                "n_components": 2,
                "n_neighbors": 10,
                "min_dist": 0.1,
                "metric": "cosine",
            },
            "hdbscan": {
                "min_cluster_size": 15,
                "min_samples": 10,
                "cluster_selection_method": "eom",
            },
            "anomaly_threshold": 10,
        }

        result = run_full_pipeline(data, config)

        assert "labels" in result
        assert "umap_2d" in result
        assert "umap_10d" in result
        assert "pca_variance" in result
        assert "hdbscan_stats" in result
        assert "anomalous_clusters" in result

        assert result["labels"].shape == (80,)
        assert result["umap_2d"].shape == (80, 2)
        assert result["umap_10d"].shape == (80, 5)
        assert 0.0 < result["pca_variance"] < 1.0
