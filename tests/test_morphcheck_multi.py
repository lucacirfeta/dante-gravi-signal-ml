"""Tests for morphcheck iterating over multiple references."""

import sys
from unittest.mock import MagicMock

sys.modules['astropy'] = MagicMock()
sys.modules['astropy.time'] = MagicMock()
sys.modules['gwpy'] = MagicMock()
sys.modules['gwpy.timeseries'] = MagicMock()
sys.modules['PIL'] = MagicMock()
sys.modules['torchvision'] = MagicMock()
sys.modules['torchvision.transforms'] = MagicMock()
sys.modules['torchaudio'] = MagicMock()
sys.modules['tqdm'] = MagicMock()
sys.modules['hdbscan'] = MagicMock()
sys.modules['sklearn'] = MagicMock()
sys.modules['sklearn.mixture'] = MagicMock()
sys.modules['sklearn.metrics'] = MagicMock()
sys.modules['umap'] = MagicMock()
sys.modules['matplotlib'] = MagicMock()
sys.modules['matplotlib.pyplot'] = MagicMock()
sys.modules['matplotlib.colors'] = MagicMock()
sys.modules['matplotlib.cm'] = MagicMock()
sys.modules['scipy'] = MagicMock()
sys.modules['scipy.spatial'] = MagicMock()
sys.modules['scipy.spatial.distance'] = MagicMock()

import pytest
import argparse
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from main import cmd_morphcheck


FAKE_CONFIG = {
    "similarity": {
        "k_neighbors": 5,
        "novelty_threshold": 0.85,
        "consensus_threshold": 0.60,
    }
}


def _make_summary(novel=1, known=0, ambiguous=0, files=None):
    """Build a minimal morphcheck summary dict."""
    if files is None:
        files = [f"file_{i}.png" for i in range(novel + known + ambiguous)]
    details = []
    idx = 0
    for _ in range(novel):
        details.append({"file": files[idx], "novelty_status": "NOVEL"})
        idx += 1
    for _ in range(known):
        details.append({"file": files[idx], "novelty_status": "KNOWN"})
        idx += 1
    for _ in range(ambiguous):
        details.append({"file": files[idx], "novelty_status": "AMBIGUOUS"})
        idx += 1
    return {"novel": novel, "known": known, "ambiguous": ambiguous, "details": details}


def _setup_embeddings_and_report(tmp_path, n_samples=10, emb_dim=128):
    """Create fake embeddings, metadata, and cluster report on disk."""
    emb_path = tmp_path / "embeddings.npy"
    np.save(emb_path, np.random.rand(n_samples, emb_dim))

    meta_path = tmp_path / "embeddings.json"
    with open(meta_path, "w") as f:
        json.dump({"files": [f"file_{i}.png" for i in range(n_samples)]}, f)

    report_path = tmp_path / "cluster_report.json"
    with open(report_path, "w") as f:
        json.dump(
            {
                "results": {
                    "clusters": {
                        "0": {"sample_files": [f"file_{i}.png" for i in range(3)]},
                        "-1": {"sample_files": ["file_9.png"]},
                    }
                }
            },
            f,
        )

    return emb_path, report_path


class TestMorphcheckMultipleRefs:
    @patch("main.load_config", return_value=FAKE_CONFIG)
    @patch("src.similarity_checker.print_morphological_summary")
    @patch("src.similarity_checker.run_morphological_crosscheck")
    def test_morphcheck_iterates_multiple_refs(
        self, mock_run, mock_print, mock_cfg, tmp_path
    ):
        """With 3 auto-discovered references, run_morphological_crosscheck
        should be called exactly 3 times."""
        emb_path, report_path = _setup_embeddings_and_report(tmp_path)

        out_dir = tmp_path / "data" / "runs" / "O4a" / "session_1" / "clusters" / "h1"
        out_dir.mkdir(parents=True)
        out_path = out_dir / "morphcheck_report.json"

        ref_dir = tmp_path / "reference"
        ref_dir.mkdir()
        ref_paths = []
        for name in ["indomain_o3b_h1.npz", "indomain_o4a_h1.npz", "indomain_o4a_l1.npz"]:
            p = ref_dir / name
            p.touch()
            ref_paths.append(p)

        sample_files = ["file_0.png", "file_1.png", "file_2.png"]
        mock_run.side_effect = [
            _make_summary(novel=2, known=1, files=sample_files),
            _make_summary(novel=1, known=2, files=sample_files),
            _make_summary(novel=0, known=3, files=sample_files),
        ]

        args = argparse.Namespace(
            embeddings=str(emb_path),
            report=str(report_path),
            reference=None,
            output=str(out_path),
        )

        with patch("src.utils.discover_references", return_value=ref_paths):
            cmd_morphcheck(args)

        assert mock_run.call_count == 3

    @patch("main.load_config", return_value=FAKE_CONFIG)
    @patch("src.similarity_checker.print_morphological_summary")
    @patch("src.similarity_checker.run_morphological_crosscheck")
    def test_morphcheck_single_explicit(
        self, mock_run, mock_print, mock_cfg, tmp_path
    ):
        """With --reference pointing to a single file,
        run_morphological_crosscheck should be called once and
        discover_references should NOT be invoked."""
        emb_path, report_path = _setup_embeddings_and_report(tmp_path)

        out_dir = tmp_path / "data" / "runs" / "O4a" / "session_1" / "clusters" / "h1"
        out_dir.mkdir(parents=True)
        out_path = out_dir / "morphcheck_report.json"

        ref_file = tmp_path / "reference" / "indomain_o4a_h1.npz"
        ref_file.parent.mkdir()
        ref_file.touch()

        mock_run.return_value = _make_summary(novel=1, known=2,
                                              files=["file_0.png", "file_1.png", "file_2.png"])

        args = argparse.Namespace(
            embeddings=str(emb_path),
            report=str(report_path),
            reference=str(ref_file),
            output=str(out_path),
        )

        with patch("src.utils.discover_references") as mock_discover:
            cmd_morphcheck(args)

        mock_discover.assert_not_called()
        assert mock_run.call_count == 1

    @patch("main.load_config", return_value=FAKE_CONFIG)
    @patch("src.similarity_checker.print_morphological_summary")
    @patch("src.similarity_checker.run_morphological_crosscheck")
    def test_morphcheck_no_refs_found(
        self, mock_run, mock_print, mock_cfg, tmp_path
    ):
        """When discover_references returns [], cmd_morphcheck should return
        early and never call run_morphological_crosscheck."""
        emb_path, report_path = _setup_embeddings_and_report(tmp_path)

        out_path = tmp_path / "morphcheck_report.json"

        args = argparse.Namespace(
            embeddings=str(emb_path),
            report=str(report_path),
            reference=None,
            output=str(out_path),
        )

        with patch("src.utils.discover_references", return_value=[]):
            cmd_morphcheck(args)

        mock_run.assert_not_called()
