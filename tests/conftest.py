import os
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

@pytest.fixture(scope="session", autouse=True)
def test_env_vars():
    """Set environment variables for testing."""
    os.environ["PYTHONPATH"] = os.path.abspath(".")

@pytest.fixture
def temp_workspace(tmp_path):
    """
    Creates a temporary workspace mirroring the 'data' structure
    but entirely isolated.
    """
    workspace = tmp_path / "data_test"
    workspace.mkdir()
    
    raw_dir_o4a = workspace / "raw" / "o4a" / "1234567890"
    raw_dir_o4a.mkdir(parents=True)
    
    raw_dir_o3b = workspace / "raw" / "o3b" / "1234567890"
    raw_dir_o3b.mkdir(parents=True)
    
    ref_dir = workspace / "reference"
    ref_dir.mkdir(parents=True)
    
    prod_dir = workspace / "production"
    prod_dir.mkdir(parents=True)
    
    # 1. Create dummy HDF5 raw files (64 seconds of data, 4096 Hz)
    from gwpy.timeseries import TimeSeries
    ts = TimeSeries(np.random.randn(4096 * 64), sample_rate=4096, t0=1234567890, name="H1:GWOSC-4KHZ_R1_STRAIN")
    ts.write(raw_dir_o4a / "H1_1234567890.hdf5", format="hdf5", overwrite=True)
    ts.write(raw_dir_o3b / "H1_1234567890.hdf5", format="hdf5", overwrite=True)
        
    # 2. Create dummy npz reference indices
    # Primary index
    primary_index = ref_dir / "patch_compressed_index_o3b.npz"
    np.savez(
        primary_index, 
        embeddings=np.random.randn(10, 384).astype(np.float32),
        labels=np.array(["Blip"] * 5 + ["Tomte"] * 5)
    )
    
    # Native index for domain shift
    for run in ["o4a", "o3b"]:
        native_index = ref_dir / f"patch_compressed_index_{run}_ex.npz"
        np.savez(
            native_index, 
            embeddings=np.random.randn(10, 384).astype(np.float32),
            labels=np.array(["Blip"] * 5 + ["Tomte"] * 5)
        )
    
    yield workspace
    
    # Teardown
    shutil.rmtree(workspace, ignore_errors=True)
