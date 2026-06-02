"""Tests for src.reporter — cluster report generation.

Uses synthetic data; no real embeddings or spectrogram files needed.
All filesystem writes go to pytest's tmp_path fixture.

Run:  pytest tests/test_reporter.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — required for headless test environments

import numpy as np
import pytest
from PIL import Image

from src.reporter import (
    _make_contact_sheet,
    _save_json_report,
    _save_umap_plot,
    print_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_result(n: int = 40, n_clusters: int = 3, seed: int = 0) -> dict:
    """Return a minimal result dict suitable for reporter functions."""
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, n_clusters, size=n)
    cluster_sizes = {i: int(np.sum(labels == i)) for i in range(n_clusters)}
    return {
        "labels": labels,
        "umap_2d": rng.standard_normal((n, 2)).astype(np.float32),
        "umap_10d": rng.standard_normal((n, 10)).astype(np.float32),
        "pca_variance": 0.987,
        "cluster_stats": {
            "n_clusters": n_clusters,
            "n_noise": 0,
            "noise_ratio": 0.0,
            "cluster_sizes": cluster_sizes,
            "largest_cluster": max(cluster_sizes.values()),
            "smallest_cluster": min(cluster_sizes.values()),
            "algorithm": "dpmm",
        },
        "hdbscan_stats": {
            "n_clusters": n_clusters,
            "n_noise": 0,
            "noise_ratio": 0.0,
            "cluster_sizes": cluster_sizes,
            "algorithm": "dpmm",
        },
        "anomalous_clusters": [],
        "anomalous_samples": [],
        "silhouette_umap": 0.42,
        "silhouette_pca": 0.35,
        "davies_bouldin_umap": 0.68,
        "davies_bouldin_pca": 1.12,
    }


def _fake_metadata(n: int = 40) -> dict:
    """Return a minimal metadata dict with fake file paths."""
    return {
        "model": "dinov2_vits14_reg",
        "files": [f"H1_{1000000 + i * 32}_{1000032 + i * 32}.png" for i in range(n)],
    }


# ---------------------------------------------------------------------------
# _save_json_report
# ---------------------------------------------------------------------------


class TestSaveJsonReport:
    """Validate the JSON report structure and content."""

    def test_report_written(self, tmp_path: Path) -> None:
        """cluster_report.json must be created and parseable."""
        result = _fake_result()
        metadata = _fake_metadata()
        stats = result["cluster_stats"]
        labels = result["labels"]

        _save_json_report(result, metadata, stats, [], [], labels, tmp_path, detector="H1")

        report_path = tmp_path / "cluster_report.json"
        assert report_path.exists()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert "timestamp" in report
        assert report["detector"] == "H1"
        assert "pipeline" in report
        assert "results" in report

    def test_pipeline_params_read_from_config(self, tmp_path: Path) -> None:
        """Pipeline section must contain pca_components from config (not hardcoded)."""
        result = _fake_result()
        metadata = _fake_metadata()
        stats = result["cluster_stats"]
        labels = result["labels"]

        _save_json_report(result, metadata, stats, [], [], labels, tmp_path, detector="H1")

        report = json.loads((tmp_path / "cluster_report.json").read_text(encoding="utf-8"))
        pipeline = report["pipeline"]

        # Verify config keys are present (values come from actual config.yaml)
        assert "pca_components" in pipeline
        assert "pca_variance_explained" in pipeline
        assert "umap_clustering" in pipeline
        assert "umap_viz" in pipeline
        assert isinstance(pipeline["pca_components"], int)

    def test_anomalous_clusters_stored(self, tmp_path: Path) -> None:
        """Anomalous cluster IDs must be stored in results."""
        result = _fake_result()
        metadata = _fake_metadata()
        stats = result["cluster_stats"]
        labels = result["labels"]

        _save_json_report(result, metadata, stats, [1], [], labels, tmp_path, detector="L1")

        report = json.loads((tmp_path / "cluster_report.json").read_text(encoding="utf-8"))
        assert report["results"]["anomalous_clusters"] == [1]

    def test_n_samples_correct(self, tmp_path: Path) -> None:
        """n_samples must match the number of labels."""
        n = 55
        result = _fake_result(n=n)
        metadata = _fake_metadata(n=n)
        stats = result["cluster_stats"]
        labels = result["labels"]

        _save_json_report(result, metadata, stats, [], [], labels, tmp_path, detector="H1")

        report = json.loads((tmp_path / "cluster_report.json").read_text(encoding="utf-8"))
        assert report["n_samples"] == n


# ---------------------------------------------------------------------------
# _save_umap_plot
# ---------------------------------------------------------------------------


class TestSaveUmapPlot:
    """Validate UMAP scatter plot creation."""

    def test_umap_png_created(self, tmp_path: Path) -> None:
        """umap_visualization.png must be written to output_dir."""
        result = _fake_result()
        stats = result["cluster_stats"]
        labels = result["labels"]

        _save_umap_plot(result["umap_2d"], labels, stats, [], [], tmp_path, detector="H1")

        assert (tmp_path / "umap_visualization.png").exists()

    def test_umap_png_with_anomalous_clusters(self, tmp_path: Path) -> None:
        """UMAP plot with anomalous clusters (star markers) must still complete."""
        result = _fake_result(n_clusters=3)
        stats = result["cluster_stats"]
        labels = result["labels"]

        _save_umap_plot(
            result["umap_2d"], labels, stats,
            anomalous_clusters=[0],
            anomalous_samples=[0, 1, 2],
            output_dir=tmp_path,
            detector="L1",
        )

        assert (tmp_path / "umap_visualization.png").exists()


# ---------------------------------------------------------------------------
# _make_contact_sheet
# ---------------------------------------------------------------------------


class TestMakeContactSheet:
    """Validate contact sheet generation."""

    def _write_pngs(self, directory: Path, n: int = 9, size: int = 64) -> list[Path]:
        """Write n tiny PNG files to directory and return their paths."""
        directory.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(n):
            rng = np.random.default_rng(i)
            arr = rng.integers(0, 256, (size, size, 3), dtype=np.uint8)
            img = Image.fromarray(arr, mode="RGB")
            p = directory / f"img_{i:03d}.png"
            img.save(p)
            paths.append(p)
        return paths

    def test_contact_sheet_created(self, tmp_path: Path) -> None:
        """contact_sheet.png must be written after calling _make_contact_sheet."""
        cluster_dir = tmp_path / "cluster_0"
        image_paths = self._write_pngs(cluster_dir)

        _make_contact_sheet(image_paths, cluster_dir, cluster_id=0, cluster_size=9, is_anomalous=False)

        assert (cluster_dir / "contact_sheet.png").exists()

    def test_contact_sheet_with_fewer_than_9_images(self, tmp_path: Path) -> None:
        """Works correctly when fewer than 9 images are provided."""
        cluster_dir = tmp_path / "cluster_1"
        image_paths = self._write_pngs(cluster_dir, n=4)

        _make_contact_sheet(image_paths, cluster_dir, cluster_id=1, cluster_size=4, is_anomalous=False)

        assert (cluster_dir / "contact_sheet.png").exists()

    def test_contact_sheet_anomalous_title(self, tmp_path: Path) -> None:
        """Anomalous clusters use a different title — smoke test only."""
        cluster_dir = tmp_path / "cluster_anom"
        image_paths = self._write_pngs(cluster_dir, n=3)

        _make_contact_sheet(image_paths, cluster_dir, cluster_id=2, cluster_size=3, is_anomalous=True)

        assert (cluster_dir / "contact_sheet.png").exists()

    def test_contact_sheet_dpmm_anomaly_dir(self, tmp_path: Path) -> None:
        """cluster_id=-1 (DPMM anomaly samples) produces contact_sheet.png."""
        anomaly_dir = tmp_path / "anomalies"
        image_paths = self._write_pngs(anomaly_dir, n=5)

        _make_contact_sheet(image_paths, anomaly_dir, cluster_id=-1, cluster_size=5, is_anomalous=True)

        assert (anomaly_dir / "contact_sheet.png").exists()


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    """Validate that print_summary runs without errors."""

    def test_print_summary_h1(self, capsys: pytest.CaptureFixture) -> None:
        result = _fake_result(n_clusters=3)
        print_summary(result, detector="H1")
        captured = capsys.readouterr()
        assert "CLUSTERING SUMMARY" in captured.out
        assert "H1" in captured.out

    def test_print_summary_l1_with_anomalous(self, capsys: pytest.CaptureFixture) -> None:
        result = _fake_result(n_clusters=3)
        result["anomalous_clusters"] = [0]
        result["anomalous_samples"] = [1, 2, 3]
        print_summary(result, detector="L1")
        captured = capsys.readouterr()
        assert "ANOMALOUS" in captured.out

    def test_print_summary_no_detector(self, capsys: pytest.CaptureFixture) -> None:
        result = _fake_result()
        print_summary(result)  # should not raise
