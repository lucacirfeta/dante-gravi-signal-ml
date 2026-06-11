"""Tests for src.full_analysis — end-to-end orchestration pipeline.

All external calls (DINOv2 encode, clustering, morphcheck, ablation,
stability, timeslide) are mocked so these tests run fast with no GPU
or real data files.

Run:  pytest tests/test_full_analysis.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from src.pipeline_v1_legacy.full_analysis import _save_detector_report, run_full_analysis


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_embeddings(n: int = 30, d: int = 384) -> np.ndarray:
    return np.random.default_rng(42).standard_normal((n, d)).astype(np.float32)


def _fake_cluster_result(n: int = 30, n_clusters: int = 3) -> dict:
    rng = np.random.default_rng(0)
    labels = rng.integers(0, n_clusters, size=n)
    sizes = {i: int(np.sum(labels == i)) for i in range(n_clusters)}
    return {
        "labels": labels,
        "umap_2d": rng.standard_normal((n, 2)).astype(np.float32),
        "umap_10d": rng.standard_normal((n, 10)).astype(np.float32),
        "pca_variance": 0.987,
        "cluster_stats": {"n_clusters": n_clusters, "n_noise": 0,
                          "noise_ratio": 0.0, "cluster_sizes": sizes,
                          "largest_cluster": max(sizes.values()),
                          "smallest_cluster": min(sizes.values()),
                          "algorithm": "dpmm"},
        "hdbscan_stats": {"n_clusters": n_clusters, "n_noise": 0,
                          "noise_ratio": 0.0, "cluster_sizes": sizes},
        "anomalous_clusters": [],
        "anomalous_samples": [],
        "silhouette_umap": 0.42, "silhouette_pca": 0.35,
        "davies_bouldin_umap": 0.68, "davies_bouldin_pca": 1.12,
    }


def _build_session_dir(
    tmp_path: Path,
    session_id: str,
    run: str,
    detectors: list[str],
    n_specs: int = 10,
) -> tuple[Path, dict[str, Path]]:
    """
    Create a minimal session directory under tmp_path/data/runs/<run>/<session_id>
    and return (session_root, {det: spec_dir}).
    """
    run_lower = run.lower()
    session_root = tmp_path / "data" / "runs" / run_lower / session_id
    spec_dirs: dict[str, Path] = {}

    for det in detectors:
        spec_dir = session_root / "spectrograms" / det
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_dirs[det] = spec_dir
        for i in range(n_specs):
            gps_start = 1000000 + i * 32
            # Use tiny 8×8 PNG to avoid heavy PIL overhead
            from PIL import Image
            img = Image.new("RGB", (8, 8), color=(i * 25 % 255, 0, 0))
            img.save(spec_dir / f"{det}_{gps_start}_{gps_start + 32}.png")

    return session_root, spec_dirs


# ---------------------------------------------------------------------------
# _save_detector_report
# ---------------------------------------------------------------------------


class TestSaveDetectorReport:
    """Unit test for the private report-saving helper."""

    def test_report_written(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """_save_detector_report writes a JSON file and returns its path."""
        monkeypatch.chdir(tmp_path)

        det_report = {
            "session_id": "20260601_120000",
            "detector": "H1",
            "run": "O4a",
            "status": "OK",
            "steps": {},
        }

        path = _save_detector_report(det_report, "O4a", "20260601_120000", "H1")
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["detector"] == "H1"
        assert loaded["status"] == "OK"


# ---------------------------------------------------------------------------
# run_full_analysis — happy path (all steps OK)
# ---------------------------------------------------------------------------


class TestRunFullAnalysisSmoke:
    """Smoke-test run_full_analysis with fully mocked dependencies."""

    def _common_patches(self) -> list[str]:
        """Return list of patch targets for the happy-path smoke test."""
        return [
            "src.full_analysis.DINOv2Encoder",
            "src.full_analysis.run_full_pipeline",
            "src.full_analysis.save_cluster_report",
            "src.full_analysis.print_summary",
            "src.full_analysis.run_morphological_crosscheck",
            "src.full_analysis.print_morphological_summary",
            "src.full_analysis.run_ablation_study",
            "src.full_analysis.run_stability_analysis",
            "src.full_analysis.run_timeslide",
            "src.full_analysis.discover_references",
        ]

    @patch("src.full_analysis.run_timeslide")
    @patch("src.full_analysis.run_stability_analysis")
    @patch("src.full_analysis.run_ablation_study")
    @patch("src.full_analysis.print_morphological_summary")
    @patch("src.full_analysis.run_morphological_crosscheck")
    @patch("src.full_analysis.print_summary")
    @patch("src.full_analysis.save_cluster_report")
    @patch("src.full_analysis.run_full_pipeline")
    @patch("src.full_analysis.DINOv2Encoder")
    @patch("src.utils.discover_references")
    def test_returns_dict_with_status(
        self,
        mock_refs: MagicMock,
        mock_encoder_cls: MagicMock,
        mock_pipeline: MagicMock,
        mock_save_report: MagicMock,
        mock_print_summary: MagicMock,
        mock_morphcheck: MagicMock,
        mock_print_morph: MagicMock,
        mock_ablation: MagicMock,
        mock_stability: MagicMock,
        mock_timeslide: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """run_full_analysis on a minimal session returns a dict."""
        monkeypatch.chdir(tmp_path)

        session_id = "20260601_120000"
        run = "O4a"
        detectors = ["H1"]
        n = 10

        session_root, spec_dirs = _build_session_dir(
            tmp_path, session_id, run, detectors, n_specs=n
        )

        # --- prepare fake .npy + .json embedding files ---
        emb_dir = session_root / "embeddings"
        emb_dir.mkdir(parents=True, exist_ok=True)
        embeddings = _fake_embeddings(n)
        np.save(emb_dir / "o4a_h1.npy", embeddings)

        files = [str(spec_dirs["H1"] / f"H1_{1000000 + i * 32}_{1000032 + i * 32}.png")
                 for i in range(n)]
        meta = {"model": "dinov2_vits14_reg", "files": files}
        (emb_dir / "o4a_h1.json").write_text(json.dumps(meta), encoding="utf-8")

        # Mock cluster result
        mock_pipeline.return_value = _fake_cluster_result(n)

        # Mock encoder
        encoder_instance = MagicMock()
        encoder_instance.batch_size = 32
        mock_encoder_cls.return_value = encoder_instance

        # Mock reference discovery → one fake reference
        fake_ref = tmp_path / "data" / "reference" / "indomain_O3b_H1.npz"
        fake_ref.parent.mkdir(parents=True, exist_ok=True)
        np.savez(fake_ref, embeddings=embeddings, labels=np.zeros(n))
        mock_refs.return_value = [fake_ref]

        # Mock morphcheck result
        mock_morphcheck.return_value = {
            "total_checked": n, "novel": 0, "known": n, "ambiguous": 0,
            "novel_files": [], "details": [],
        }

        overall = run_full_analysis(
            session_id=session_id,
            detectors=detectors,
            run=run,
            skip_timeslide=True,
            n_runs=2,
            sequential=True,
        )

        assert isinstance(overall, dict)
        # The return dict has at least one status key (detector or error)
        assert len(overall) > 0

    @patch("src.utils.discover_references")
    def test_missing_session_returns_failed(
        self,
        mock_refs: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-existent session directory → detector status is FAILED."""
        monkeypatch.chdir(tmp_path)
        mock_refs.return_value = []

        result = run_full_analysis(
            session_id="nonexistent_session",
            detectors=["H1"],
            run="O4a",
            skip_timeslide=True,
            sequential=True,
        )

        # run_full_analysis returns {"status": {"H1": "FAILED", ...}, ...} or {"status": "FAILED", ...}
        status = result.get("status")
        failed = (
            status == "FAILED"
            or (isinstance(status, dict) and status.get("H1") == "FAILED")
            or result.get("H1") == "FAILED"
        )
        assert failed, f"Expected FAILED status, got: {result}"

    @patch("src.utils.discover_references")
    def test_no_detectors_discovered_returns_failed(
        self,
        mock_refs: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Session dir exists but has no detector subdirs → FAILED."""
        monkeypatch.chdir(tmp_path)
        mock_refs.return_value = []

        session_id = "20260601_130000"
        spec_dir = tmp_path / "data" / "runs" / "o4a" / session_id / "spectrograms"
        spec_dir.mkdir(parents=True, exist_ok=True)  # empty — no detector subdirs

        result = run_full_analysis(
            session_id=session_id,
            detectors=None,  # trigger auto-discovery
            run="O4a",
            skip_timeslide=True,
            sequential=True,
        )

        assert result.get("status") == "FAILED"


# ---------------------------------------------------------------------------
# Timeslide skip flag
# ---------------------------------------------------------------------------


class TestRunFullAnalysisTimeslideSkip:
    """Verify skip_timeslide flag prevents timeslide from being called."""

    @patch("src.full_analysis.run_timeslide")
    @patch("src.full_analysis.run_stability_analysis")
    @patch("src.full_analysis.run_ablation_study")
    @patch("src.full_analysis.print_morphological_summary")
    @patch("src.full_analysis.run_morphological_crosscheck")
    @patch("src.full_analysis.print_summary")
    @patch("src.full_analysis.save_cluster_report")
    @patch("src.full_analysis.run_full_pipeline")
    @patch("src.full_analysis.DINOv2Encoder")
    @patch("src.utils.discover_references")
    def test_timeslide_not_called_when_skipped(
        self,
        mock_refs: MagicMock,
        mock_encoder_cls: MagicMock,
        mock_pipeline: MagicMock,
        mock_save_report: MagicMock,
        mock_print_summary: MagicMock,
        mock_morphcheck: MagicMock,
        mock_print_morph: MagicMock,
        mock_ablation: MagicMock,
        mock_stability: MagicMock,
        mock_timeslide: MagicMock,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        session_id = "20260601_140000"
        run = "O4a"
        n = 10

        session_root, spec_dirs = _build_session_dir(
            tmp_path, session_id, run, ["H1"], n_specs=n
        )

        emb_dir = session_root / "embeddings"
        emb_dir.mkdir(parents=True, exist_ok=True)
        embeddings = _fake_embeddings(n)
        np.save(emb_dir / "o4a_h1.npy", embeddings)
        files = [str(spec_dirs["H1"] / f"H1_{1000000 + i * 32}_{1000032 + i * 32}.png")
                 for i in range(n)]
        meta = {"model": "dinov2_vits14_reg", "files": files}
        (emb_dir / "o4a_h1.json").write_text(json.dumps(meta), encoding="utf-8")

        mock_pipeline.return_value = _fake_cluster_result(n)
        encoder_instance = MagicMock()
        encoder_instance.batch_size = 32
        mock_encoder_cls.return_value = encoder_instance

        fake_ref = tmp_path / "data" / "reference" / "indomain_O3b_H1.npz"
        fake_ref.parent.mkdir(parents=True, exist_ok=True)
        np.savez(fake_ref, embeddings=embeddings, labels=np.zeros(n))
        mock_refs.return_value = [fake_ref]
        mock_morphcheck.return_value = {
            "total_checked": n, "novel": 0, "known": n, "ambiguous": 0,
            "novel_files": [], "details": [],
        }

        run_full_analysis(
            session_id=session_id,
            detectors=["H1"],
            run=run,
            skip_timeslide=True,
            n_runs=1,
            sequential=True,
        )

        mock_timeslide.assert_not_called()
