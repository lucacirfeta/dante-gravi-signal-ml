"""Tests for src.stability — clustering stability analysis.

Uses synthetic embeddings and mocked UMAP/HDBSCAN/DPMM so tests
complete in milliseconds without GPU or real model downloads.

Run:  pytest tests/test_stability.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.stability import run_stability_analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_embeddings(n: int = 120, d: int = 384, seed: int = 42) -> np.ndarray:
    """Return random float32 embeddings of shape (n, d)."""
    return np.random.default_rng(seed).standard_normal((n, d)).astype(np.float32)


def _minimal_cluster_cfg(algorithm: str = "hdbscan") -> dict:
    """Return a minimal cluster config that bypasses heavy computation."""
    return {
        "algorithm": algorithm,
        "pca_components": 10,
        "random_state": 42,
        "umap_clustering": {
            "n_components": 3,
            "n_neighbors": 5,
            "min_dist": 0.0,
            "metric": "cosine",
        },
        "umap_viz": {
            "n_components": 2,
            "n_neighbors": 5,
            "min_dist": 0.1,
            "metric": "cosine",
        },
        "hdbscan": {
            "min_cluster_size": 10,
            "min_samples": 5,
            "cluster_selection_method": "eom",
            "small_cluster_threshold": "auto",
        },
        "dpmm": {
            "n_components": 5,
            "anomaly_percentile": 5.0,
            "anomaly_threshold": -1000.0,  # very low → no anomalies
        },
        "anomaly_threshold": "auto",
    }


# ---------------------------------------------------------------------------
# run_stability_analysis — HDBSCAN mode
# ---------------------------------------------------------------------------


class TestStabilityHDBSCAN:
    """Verify stability report is produced correctly for HDBSCAN algorithm."""

    @patch("src.stability.run_umap")
    @patch("src.stability.run_hdbscan")
    def test_report_written_hdbscan(
        self,
        mock_hdbscan: MagicMock,
        mock_umap: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run_stability_analysis writes stability_report_H1.json with correct keys."""
        n = 60
        n_clusters = 3

        rng = np.random.default_rng(42)
        fake_labels = rng.integers(0, n_clusters, size=n)
        fake_umap = rng.standard_normal((n, 3)).astype(np.float32)

        mock_umap.return_value = fake_umap
        mock_hdbscan.return_value = (
            fake_labels,
            {
                "n_clusters": n_clusters,
                "n_noise": 0,
                "noise_ratio": 0.0,
                "cluster_sizes": {i: 20 for i in range(n_clusters)},
                "largest_cluster": 20,
                "smallest_cluster": 20,
            },
        )

        embeddings = _synthetic_embeddings(n)
        cfg = _minimal_cluster_cfg("hdbscan")

        run_stability_analysis(
            embeddings=embeddings,
            cluster_cfg=cfg,
            n_runs=3,
            session_id="default",
            detector="H1",
            run="O4a",
        )

        report_path = Path("data/stability/stability_report_H1.json")
        assert report_path.exists(), f"Report not found: {report_path}"

        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)

        assert report["detector"] == "H1"
        assert "ari_stats" in report
        assert "mean" in report["ari_stats"]
        assert "std" in report["ari_stats"]
        assert "interpretation" in report["ari_stats"]
        assert report["ari_stats"]["interpretation"] in {"robust", "moderate", "unstable"}
        assert "stable_anomalous_clusters_baseline_ids" in report
        assert isinstance(report["stable_anomalous_clusters_baseline_ids"], list)
        assert "ari_matrix" in report
        assert len(report["ari_matrix"]) == 4  # baseline + 3 perturbed

    @patch("src.stability.run_umap")
    @patch("src.stability.run_hdbscan")
    def test_ari_matrix_is_symmetric(
        self,
        mock_hdbscan: MagicMock,
        mock_umap: MagicMock,
        tmp_path: Path,
    ) -> None:
        """The ARI matrix must be square and symmetric."""
        n = 60
        rng = np.random.default_rng(1)
        fake_labels = rng.integers(0, 2, size=n)
        fake_umap = rng.standard_normal((n, 3)).astype(np.float32)

        mock_umap.return_value = fake_umap
        mock_hdbscan.return_value = (
            fake_labels,
            {
                "n_clusters": 2, "n_noise": 0, "noise_ratio": 0.0,
                "cluster_sizes": {0: 30, 1: 30},
                "largest_cluster": 30, "smallest_cluster": 30,
            },
        )

        embeddings = _synthetic_embeddings(n)
        run_stability_analysis(
            embeddings=embeddings,
            cluster_cfg=_minimal_cluster_cfg("hdbscan"),
            n_runs=2,
            session_id="default",
            detector="H1",
            run="O4a",
        )

        report_path = Path("data/stability/stability_report_H1.json")
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)

        matrix = np.array(report["ari_matrix"])
        assert matrix.shape[0] == matrix.shape[1], "ARI matrix is not square"
        np.testing.assert_allclose(matrix, matrix.T, atol=1e-9)
        np.testing.assert_allclose(np.diag(matrix), 1.0, atol=1e-9)


# ---------------------------------------------------------------------------
# run_stability_analysis — DPMM mode
# ---------------------------------------------------------------------------


class TestStabilityDPMM:
    """Verify stability report is produced correctly for DPMM algorithm."""

    @patch("src.stability.run_umap")
    @patch("src.stability.run_dpmm")
    def test_report_written_dpmm(
        self,
        mock_dpmm: MagicMock,
        mock_umap: MagicMock,
        tmp_path: Path,
    ) -> None:
        """run_stability_analysis with DPMM writes a valid report."""
        n = 60
        rng = np.random.default_rng(42)
        fake_labels = rng.integers(0, 3, size=n)
        fake_umap = rng.standard_normal((n, 3)).astype(np.float32)

        mock_umap.return_value = fake_umap
        mock_dpmm.return_value = (
            fake_labels,
            {
                "n_clusters": 3, "n_noise": 0, "noise_ratio": 0.0,
                "cluster_sizes": {0: 20, 1: 20, 2: 20},
                "largest_cluster": 20, "smallest_cluster": 20,
                "algorithm": "dpmm",
            },
            [],  # anomalous_samples
        )

        cfg = _minimal_cluster_cfg("dpmm")

        run_stability_analysis(
            embeddings=_synthetic_embeddings(n),
            cluster_cfg=cfg,
            n_runs=2,
            session_id="default",
            detector="L1",
            run="O4a",
        )

        report_path = Path("data/stability/stability_report_L1.json")
        assert report_path.exists()

        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)

        assert report["detector"] == "L1"
        assert report["ari_stats"]["interpretation"] in {"robust", "moderate", "unstable"}


# ---------------------------------------------------------------------------
# Interpretation thresholds
# ---------------------------------------------------------------------------


class TestStabilityInterpretation:
    """Verify ARI interpretation thresholds match the specification."""

    @patch("src.stability.run_umap")
    @patch("src.stability.run_hdbscan")
    def test_interpretation_robust(
        self,
        mock_hdbscan: MagicMock,
        mock_umap: MagicMock,
    ) -> None:
        """Identical labels across runs → mean ARI = 1.0 → 'robust'."""
        n = 40
        rng = np.random.default_rng(7)
        identical_labels = rng.integers(0, 3, size=n)
        mock_umap.return_value = rng.standard_normal((n, 3)).astype(np.float32)
        mock_hdbscan.return_value = (
            identical_labels,
            {"n_clusters": 3, "n_noise": 0, "noise_ratio": 0.0,
             "cluster_sizes": {0: 14, 1: 13, 2: 13},
             "largest_cluster": 14, "smallest_cluster": 13},
        )

        run_stability_analysis(
            embeddings=_synthetic_embeddings(n),
            cluster_cfg=_minimal_cluster_cfg("hdbscan"),
            n_runs=2,
            session_id="default",
            detector="H1",
            run="O4a",
        )

        report_path = Path("data/stability/stability_report_H1.json")
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)

        assert report["ari_stats"]["mean"] >= 0.8
        assert report["ari_stats"]["interpretation"] == "robust"
