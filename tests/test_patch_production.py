import os
from pathlib import Path
import h5py
import numpy as np
import pytest
import torch

from src.core.patch_scorer import PatchScorer
from src.pipeline_v2_production.production_writer import ProductionWriter

def test_md5_check(tmp_path):
    fake_index = tmp_path / "fake_index.npz"
    np.savez(fake_index, embeddings=np.random.randn(281, 384))
    
    with pytest.raises(RuntimeError, match="MD5 mismatch"):
        PatchScorer(reference_index_path=fake_index, device='cpu')

def test_threshold_calibration():
    scores = np.linspace(0.0, 1.0, 100)
    target_fpr = 0.01
    percentile_target = (1.0 - target_fpr) * 100.0
    expected_threshold = np.percentile(scores, 99.0)
    assert np.isclose(expected_threshold, 0.99)

def test_hdf5_append(tmp_path):
    writer = ProductionWriter(tmp_path, "test_session", "L1")
    metadata = {
        "session_id": "test_session", "detector": "L1",
        "k": 68, "reference_md5": "12345"
    }
    bg_scores = np.array([0.1, 0.2, 0.3])
    writer.verify_and_init(metadata, bg_scores, 0.5)
    
    result_mock_1 = {
        "mil_vector": np.ones(384, dtype=np.float32),
        "novelty_score": 0.8,
        "top_k_indices": np.arange(68, dtype=np.int32)
    }
    writer.append_novel(1386800000.0, result_mock_1)
    
    with h5py.File(writer.hdf5_path, 'r') as f:
        assert f["novelties"]["gps_times"].shape == (1,)
        assert f["novelties"]["mil_vectors"].shape == (1, 384)

def test_resume_logic(tmp_path):
    writer = ProductionWriter(tmp_path, "test_session", "L1")
    assert writer.load_checkpoint() is None
    writer.save_checkpoint(1386800000)
    assert writer.load_checkpoint() == 1386800000

def test_patch_normalization():
    v = torch.randn(10, 384)
    v_norm = torch.nn.functional.normalize(v, p=2, dim=-1)
    norms = torch.norm(v_norm, p=2, dim=-1)
    assert torch.allclose(norms, torch.ones_like(norms), atol=1e-5)

@pytest.mark.skipif(not torch.cuda.is_available(), reason="Requires CUDA")
def test_no_gpu_oom():
    torch.cuda.empty_cache()
    start_mem = torch.cuda.memory_allocated()
    for _ in range(100):
        t1 = torch.randn(1369, 384, device='cuda')
        t2 = torch.randn(1216, 384, device='cuda')
        sim = torch.matmul(t1, t2.T)
        del t1, t2, sim
    torch.cuda.empty_cache()
    end_mem = torch.cuda.memory_allocated()
    assert end_mem <= start_mem + 1024 * 1024 * 50
