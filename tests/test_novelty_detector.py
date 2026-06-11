import os
import pytest
import numpy as np
import torch
from pathlib import Path
from PIL import Image

from src.pipeline_v1_legacy.novelty_detector import PatchLevelNoveltyDetector

@pytest.fixture
def dummy_detector():
    # Create a dummy reference index (100 samples, 384 dim)
    ref_emb = np.random.randn(100, 384).astype(np.float32)
    # L2 normalize
    norms = np.linalg.norm(ref_emb, axis=1, keepdims=True)
    ref_emb = ref_emb / norms
    
    detector = PatchLevelNoveltyDetector(
        reference_embeddings=ref_emb,
        device='cuda' if torch.cuda.is_available() else 'cpu'
    )
    return detector

@pytest.fixture
def dummy_spectrogram(tmp_path):
    img = Image.fromarray(np.random.randint(0, 255, (256, 256), dtype=np.uint8), 'L')
    path = tmp_path / "dummy_spec.png"
    img.save(path)
    return path

def test_patch_normalization(dummy_detector, dummy_spectrogram):
    patch_tokens = dummy_detector.extract_patch_tokens(dummy_spectrogram)
    
    # Check shape
    assert patch_tokens.shape == (1369, 384)
    
    # Check normalization: L2 norm of each patch should be 1.0
    norms = torch.norm(patch_tokens, p=2, dim=-1)
    assert torch.allclose(norms, torch.ones_like(norms), atol=1e-5)

def test_anomaly_score_range(dummy_detector):
    # Dummy normalized patch tokens
    patch_tokens = torch.randn(1369, 384, device=dummy_detector.device)
    patch_tokens = torch.nn.functional.normalize(patch_tokens, p=2, dim=-1)
    
    scores = dummy_detector.compute_patch_anomaly_scores(patch_tokens)
    
    # Scores = 1 - max_sim, sim is in [-1, 1], so scores in [0, 2]
    # But usually sim > 0, so scores typically [0, 1]. Range is strictly [0, 2].
    assert scores.shape == (1369,)
    assert np.all(scores >= -1e-6)
    assert np.all(scores <= 2.0 + 1e-6)

def test_topk_selection(dummy_detector):
    # Create deterministic scores
    scores = np.linspace(0.0, 1.0, 1369) # sorted ascending
    
    # Condense with top-k
    k = 37
    novelty = dummy_detector.compute_novelty_score(scores, k=k)
    
    # The top-k are the last k elements (highest scores)
    expected_top_k = scores[-k:]
    expected_novelty = np.mean(np.log(expected_top_k + 1e-8))
    
    assert np.isclose(novelty, expected_novelty)

def test_log_score_no_divergence(dummy_detector):
    # Test with perfectly matching patches (score = 0.0)
    scores = np.zeros(1369)
    novelty = dummy_detector.compute_novelty_score(scores, k=37)
    
    # Should be log(1e-8) = -18.4206...
    assert not np.isnan(novelty)
    assert not np.isinf(novelty)
    assert np.isclose(novelty, np.log(1e-8))

def test_gpu_memory(dummy_detector, dummy_spectrogram):
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available")
        
    torch.cuda.empty_cache()
    start_mem = torch.cuda.memory_allocated()
    
    # Run full classify
    _ = dummy_detector.classify(dummy_spectrogram, k=37, threshold=-10.0)
    
    end_mem = torch.cuda.memory_allocated()
    
    # Difference should be negligible (just the model footprint, which is persistent)
    assert abs(end_mem - start_mem) < 10 * 1024 * 1024 # less than 10MB leak
