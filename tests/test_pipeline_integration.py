import argparse
from pathlib import Path
import pytest
from unittest.mock import patch

from main import cmd_patch_analysis, cmd_aggregate_report

@pytest.mark.parametrize("obs_run", ["O4a", "O3b"])
def test_pipeline_end_to_end(temp_workspace, obs_run):
    """
    Test the full patch-analysis and aggregate-report pipeline for multiple runs.
    Uses temp_workspace fixture which provides mock HDF5 and NPZ indices.
    """
    raw_dir = temp_workspace / "raw" / obs_run.lower()
    prod_dir = temp_workspace / "production"
    
    # 1. Run Patch Analysis (Phase 4 & 5)
    class Args:
        pass
        
    args = Args()
    args.detector = "H1"
    args.data_dir = str(raw_dir)
    args.sessions = ["1234567890"]
    args.output_dir = str(prod_dir)
    args.resume = False
    args.run = obs_run
    args.reference_run = "O3b"
    args.k = 68
    args.fpr = 0.01
    args.n_background = 10
    args.seed = 42
    args.workers = 1
    args.batch_size = 1
    
    # Override global data directories to point to our temp workspace for background sampling
    from src.core import data_loader
    original_dirs = data_loader._DATA_DIRECTORIES.copy()
    data_loader._DATA_DIRECTORIES = [raw_dir]
    
    # We must patch sys.exit so validate_reports doesn't kill the test suite
    def mock_verify_md5(self):
        self.reference_md5 = "dummy_md5"
        
    def mock_fetch_strain_data(*args, **kwargs):
        from gwpy.timeseries import TimeSeries
        import numpy as np
        return TimeSeries(np.random.randn(4096 * 32), sample_rate=4096, t0=1234567890)
        
    with patch("sys.exit") as mock_exit, \
         patch("src.core.patch_scorer.PatchScorer._verify_md5", mock_verify_md5), \
         patch("src.pipeline_v2_production.production_report.fetch_strain_data", mock_fetch_strain_data):
        cmd_patch_analysis(args)
        
    # Restore global data directories
    data_loader._DATA_DIRECTORIES = original_dirs
        
    # Verify outputs of patch analysis
    session_prod = prod_dir / "1234567890"
    assert (session_prod / "novelties_1234567890_H1.h5").exists(), "HDF5 novelties not created"
    assert (session_prod / f"{obs_run}_1234567890_H1_native_scores.npy").exists(), "Native scores not extracted"
    assert (session_prod / "cluster_report_novelties_1234567890_H1.json").exists(), "Clustering report missing"
    assert (session_prod / "report" / "full_discovery_report_1234567890_H1.md").exists(), "Markdown report missing"
    
    # 2. Run Aggregate Report (Phase 6)
    agg_args = Args()
    agg_args.production_dir = str(prod_dir)
    agg_args.run = obs_run
    agg_args.nds_host = None # Skip PEM for unit tests
    
    with patch("subprocess.run") as mock_subprocess: # Mock offline validation scripts
        cmd_aggregate_report(agg_args)
        
    # Verify outputs of aggregate report
    agg_dir = prod_dir / "aggregated"
    assert (agg_dir / f"background_scores_H1_{obs_run}.npy").exists(), "Master background not aggregated"
    assert (agg_dir / "aggregate_summary.json").exists(), "Aggregate summary missing"
    
    # 3. Teardown Cache
    from src.core.data_loader import clear_astropy_cache
    clear_astropy_cache()
