import hashlib
import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from src.encoder import build_dinov2_transform
from src.utils import get_device, setup_logger

logger = setup_logger(__name__)

class PatchScorer:
    """GPU-bound scorer for the Patch-Level production pipeline.
    
    Loads frozen DINOv2 and the reference background index.
    Calculates empirical thresholds and scores segments via Patch-Level MIL.
    """
    def __init__(
        self,
        reference_index_path: str | Path,
        device: str | torch.device | None = None,
        k: int = 68,
        fpr: float = 0.01,
        n_background: int = 500,
        seed: int = 42
    ):
        self.device = torch.device(device) if device else get_device()
        self.k = k
        self.fpr = fpr
        self.n_background = n_background
        self.seed = seed
        self.reference_index_path = Path(reference_index_path)
        
        # 1. MD5 Verification
        self._verify_md5()
        
        # 2. Load Centroids
        data = np.load(self.reference_index_path)
        centroids_np = data["embeddings"]
        
        # Expected shape constraint (Correction #1)
        if centroids_np.shape != (1216, 384):
            raise RuntimeError(f"Expected reference index shape (1216, 384), got {centroids_np.shape}")
            
        self.centroids = torch.tensor(centroids_np, device=self.device, dtype=torch.float32)
        # Explicit L2 normalization
        self.centroids = F.normalize(self.centroids, p=2, dim=-1)
        
        # 3. Load DINOv2
        self.model = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14_reg")
        self.model.eval()
        for param in self.model.parameters():
            param.requires_grad = False
        self.model.to(self.device)
        
        # 4. Transform
        self.transform = build_dinov2_transform()
        
        logger.info(f"PatchScorer initialized on {self.device}. k={self.k}, FPR={self.fpr}")
        
    def _verify_md5(self):
        """Strict MD5 verification to prevent silent corruptions."""
        EXPECTED_MD5 = "1080afa809964011e398c44fb24b73c6"
        hash_md5 = hashlib.md5()
        with open(self.reference_index_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        actual_md5 = hash_md5.hexdigest()
        
        if actual_md5 != EXPECTED_MD5:
            raise RuntimeError(f"MD5 mismatch for reference index! Expected {EXPECTED_MD5}, got {actual_md5}")
        self.reference_md5 = actual_md5
        logger.info(f"Reference MD5 verified: {self.reference_md5}")

    @torch.no_grad()
    def calibrate_threshold(self, background_spectrograms: list[np.ndarray]) -> float:
        """Calibrates threshold empirically (p99) on background samples."""
        if len(background_spectrograms) != self.n_background:
            logger.warning(f"Calibration expected {self.n_background} samples, got {len(background_spectrograms)}")
            
        all_novelty_scores = []
        for spec in background_spectrograms:
            result = self.score_spectrogram(spec, threshold=1.0) # threshold 1.0 ensures is_novel=False
            all_novelty_scores.append(result["novelty_score"])
            
        scores_np = np.array(all_novelty_scores)
        
        # Empirical percentile direct computation (Correction #3 implies no GEV)
        percentile_target = (1.0 - self.fpr) * 100.0
        threshold = float(np.percentile(scores_np, percentile_target))
        
        logger.info("[CALIBRATION] n_background: %d", len(background_spectrograms))
        logger.info("[CALIBRATION] novelty_score mean: %.4f", scores_np.mean())
        logger.info("[CALIBRATION] novelty_score std:  %.4f", scores_np.std())
        logger.info("[CALIBRATION] threshold (p%d):    %.4f", int(percentile_target), threshold)
        logger.info("[CALIBRATION] method: empirical_percentile")
        
        return threshold

    @torch.no_grad()
    def score_spectrogram(self, spectrogram_array: np.ndarray, threshold: float) -> dict:
        """Runs the entire MIL patch-level scoring pipeline on a single image.
        
        spectrogram_array: (256, 256, 3) uint8 numpy array.
        """
        # Convert to PIL Image (needed by transform)
        img = Image.fromarray(spectrogram_array)
        tensor = self.transform(img).unsqueeze(0).to(self.device)
        
        # 1. Forward Features
        features = self.model.forward_features(tensor)
        patch_tokens = features["x_norm_patchtokens"].squeeze(0) # (1369, 384)
        
        # 2. L2 Normalize explicitly
        patch_tokens = F.normalize(patch_tokens, p=2, dim=-1)
        
        # 3. Cosine Similarity vs Background
        # similarities = (1369, 1216)
        similarities = torch.matmul(patch_tokens, self.centroids.T)
        max_sims, _ = torch.max(similarities, dim=-1) # (1369,)
        
        # 4. Anomaly Scores (1 - sim)
        anomaly_scores = 1.0 - max_sims
        
        # 5. Top-K Pooling
        top_k_scores, top_k_indices = torch.topk(anomaly_scores, self.k)
        novelty_score = float(top_k_scores.mean().cpu().item())
        
        # 6. MIL Vector Extraction
        top_k_patches = patch_tokens[top_k_indices] # (K, 384)
        mil_vector = top_k_patches.mean(dim=0)
        mil_vector = F.normalize(mil_vector, p=2, dim=-1)
        
        return {
            "novelty_score": novelty_score,
            "is_novel": novelty_score > threshold,
            "top_k_indices": top_k_indices.cpu().numpy().astype(np.int32),
            "mil_vector": mil_vector.cpu().numpy().astype(np.float32),
            "patch_anomaly_scores": anomaly_scores.cpu().numpy().astype(np.float32)
        }
