import argparse
from pathlib import Path
import pytest
from unittest.mock import patch

from main import cmd_patch_analysis, cmd_aggregate_report

@pytest.mark.parametrize("obs_run", ["O4a", "O3b"])
def test_pipeline_end_to_end(temp_workspace, obs_run, monkeypatch):
    """
    Test the full patch-analysis and aggregate-report pipeline for multiple runs.
    Uses temp_workspace fixture which provides mock HDF5 and NPZ indices.
    """
    raw_dir = temp_workspace / "raw" / obs_run.lower()
    prod_dir = temp_workspace / "production"
    # Keep the integration test scoped to the discovery/aggregation contract;
    # expensive scientific experiments have their own tests and must never
    # fetch full-run data from an integration fixture.
    monkeypatch.setenv("DANTE_EPS_COH_TRIALS", "0")
    monkeypatch.setenv("DANTE_COHESION_SEGMENTS", "0")
    
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
    args.n_background = 4
    args.seed = 42
    args.workers = 1
    args.batch_size = 1
    
    # Override global data directories to point to our temp workspace for background sampling
    from src.core import data_loader
    monkeypatch.setattr(data_loader, "_DATA_DIRECTORIES", [raw_dir])
    
    # We must patch sys.exit so validate_reports doesn't kill the test suite
    def mock_fetch_strain_data(*args, **kwargs):
        from gwpy.timeseries import TimeSeries
        import numpy as np
        start = float(args[1])
        end = float(args[2])
        n_samples = int(round((end - start) * 4096))
        rng = np.random.default_rng(int(start) % (2**32))
        return TimeSeries(
            rng.standard_normal(n_samples),
            sample_rate=4096,
            t0=start,
        )

    def mock_aggregate_scorer_init(self, *args, **kwargs):
        """Keep aggregation focused on orchestration, not DINOv2 latency."""

    def mock_aggregate_score(self, images, threshold=0.0):
        import numpy as np

        vector = np.full(384, 1.0 / np.sqrt(384), dtype=np.float32)
        return [
            {
                "novelty_score": 0.5,
                "mil_vector": vector.copy(),
            }
            for _image in images
        ]
        
    with patch("sys.exit") as mock_exit, \
         patch(
             "src.pipeline_v2_production.production_report.fetch_strain_data",
             mock_fetch_strain_data,
         ), \
         patch("gwosc.datasets.find_datasets", return_value=[]), \
         patch("gwosc.timeline.get_segments", return_value=[]):
        cmd_patch_analysis(args)
        
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
    agg_args.dsd_background_n = 2
    agg_args.candidate_window_offset = 0.0
    
    # Keep the monkeypatched data directories through aggregation: DSD
    # background extraction must remain hermetic and must never scan configured
    # real-data drives.
    # Synthetic GPS values intentionally do not belong to the named observing
    # runs; patch the run contract to the fixture interval only.
    with patch("subprocess.run") as mock_subprocess, \
         patch(
             "src.core.patch_scorer.PatchScorer.__init__",
             mock_aggregate_scorer_init,
         ), \
         patch(
             "src.core.patch_scorer.PatchScorer.score_spectrogram",
             mock_aggregate_score,
         ), \
         patch(
             "src.core.data_loader.fetch_local_or_remote_strain",
             mock_fetch_strain_data,
         ), \
         patch(
             "src.pipeline_v2_production.cross_detector_veto."
             "fetch_local_or_remote_strain",
             mock_fetch_strain_data,
         ), \
         patch(
             "src.pipeline_v2_production.background_calibration.resolve_run_bounds",
             return_value=(1234567800.0, 1234570300.0),
         ):
        cmd_aggregate_report(agg_args)
        
    # Verify outputs of aggregate report
    agg_dir = prod_dir / "aggregated"
    assert (agg_dir / f"background_scores_H1_{obs_run}.npy").exists(), "Master background not aggregated"
    assert (agg_dir / "aggregate_summary.json").exists(), "Aggregate summary missing"
    
    # 3. Teardown Cache
    from src.core.data_loader import clear_astropy_cache
    clear_astropy_cache()
