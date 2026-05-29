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
from pathlib import Path
from unittest.mock import patch, MagicMock
import numpy as np
import argparse
import json

from src.utils import discover_references
from main import cmd_morphcheck


def test_discover_references_with_files(tmp_path):
    # Create fake npz files
    (tmp_path / "indomain_index.npz").touch()
    (tmp_path / "indomain_o4a_v2.npz").touch()
    (tmp_path / "other_file.txt").touch()

    refs = discover_references(reference_dir=tmp_path)
    assert len(refs) == 2
    assert refs[0].name == "indomain_index.npz"
    assert refs[1].name == "indomain_o4a_v2.npz"


def test_discover_references_empty(tmp_path):
    refs = discover_references(reference_dir=tmp_path)
    assert len(refs) == 0


@patch("src.similarity_checker.run_morphological_crosscheck")
@patch("src.similarity_checker.print_morphological_summary")
def test_cmd_morphcheck_autodiscovery(mock_print, mock_run, tmp_path):
    # Setup fake embeddings and reports
    emb_path = tmp_path / "embeddings.npy"
    np.save(emb_path, np.random.rand(10, 128))
    
    meta_path = tmp_path / "embeddings.json"
    with open(meta_path, "w") as f:
        json.dump({"files": [f"file_{i}.png" for i in range(10)]}, f)
        
    report_path = tmp_path / "cluster_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "results": {
                "clusters": {
                    "0": {"sample_files": ["file_0.png", "file_1.png"]},
                    "-1": {"sample_files": ["file_2.png"]}
                }
            }
        }, f)
        
    out_dir = tmp_path / "data" / "runs" / "O4a" / "session_123" / "clusters" / "h1"
    out_dir.mkdir(parents=True)
    out_path = out_dir / "morphcheck_report.json"
    
    # Fake references
    ref_dir = tmp_path / "reference"
    ref_dir.mkdir()
    ref1 = ref_dir / "indomain_index.npz"
    ref2 = ref_dir / "indomain_o4a_v2.npz"
    ref1.touch()
    ref2.touch()
    
    # Setup mock return values for crosscheck
    mock_run.side_effect = [
        {
            "novel": 2, "known": 0, "ambiguous": 0,
            "details": [
                {"file": "file_0.png", "novelty_status": "NOVEL"},
                {"file": "file_1.png", "novelty_status": "NOVEL"}
            ]
        },
        {
            "novel": 1, "known": 1, "ambiguous": 0,
            "details": [
                {"file": "file_0.png", "novelty_status": "KNOWN"},
                {"file": "file_1.png", "novelty_status": "NOVEL"}
            ]
        }
    ]

    args = argparse.Namespace(
        embeddings=str(emb_path),
        report=str(report_path),
        reference=None,
        output=str(out_path)
    )

    with patch("src.utils.discover_references", return_value=[ref1, ref2]):
        cmd_morphcheck(args)
        
    assert mock_run.call_count == 2
    
    summary_path = out_dir / "morphcheck_summary_H1.json"
    assert summary_path.exists()
    
    with open(summary_path, "r") as f:
        summary = json.load(f)
        
    assert summary["detector"] == "H1"
    assert summary["session_id"] == "session_123"
    assert summary["references_used"] == ["indomain_index.npz", "indomain_o4a_v2.npz"]
    assert summary["comparison"]["newly_resolved"] == 1
    assert summary["comparison"]["still_novel"] == 1


@patch("src.similarity_checker.run_morphological_crosscheck")
@patch("src.similarity_checker.print_morphological_summary")
def test_cmd_morphcheck_explicit_reference(mock_print, mock_run, tmp_path):
    # Should work as before (Zero regression)
    emb_path = tmp_path / "embeddings.npy"
    np.save(emb_path, np.random.rand(10, 128))
    
    meta_path = tmp_path / "embeddings.json"
    with open(meta_path, "w") as f:
        json.dump({"files": [f"file_{i}.png" for i in range(10)]}, f)
        
    report_path = tmp_path / "cluster_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "results": {
                "clusters": {
                    "0": {"sample_files": ["file_0.png"]}
                }
            }
        }, f)
        
    out_dir = tmp_path / "data" / "runs" / "O4a" / "session_123" / "clusters" / "h1"
    out_dir.mkdir(parents=True)
    out_path = out_dir / "morphcheck_report.json"
    
    ref1 = tmp_path / "reference" / "indomain_index.npz"
    ref1.parent.mkdir()
    ref1.touch()

    mock_run.return_value = {
        "novel": 1, "known": 0, "ambiguous": 0,
        "details": [{"file": "file_0.png", "novelty_status": "NOVEL"}]
    }

    args = argparse.Namespace(
        embeddings=str(emb_path),
        report=str(report_path),
        reference=str(ref1),
        output=str(out_path)
    )

    cmd_morphcheck(args)
        
    assert mock_run.call_count == 1
    
    # In explicit mode, no morphcheck_summary.json is created. Output goes directly to out_path.
    assert not (out_dir / "morphcheck_summary.json").exists()
    assert not (out_dir / "morphcheck_summary_H1.json").exists()
