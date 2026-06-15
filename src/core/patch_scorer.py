import hashlib
import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from src.core.encoder import build_dinov2_transform
from src.core.utils import get_device, setup_logger

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
        seed: int = 42,
        verify_md5: bool = True
    ):
        self.device = torch.device(device) if device else get_device()
        self.k = k
        self.fpr = fpr
        self.n_background = n_background
        self.seed = seed
        self.reference_index_path = Path(reference_index_path)
        
        # 1. MD5 Verification
        if verify_md5:
            self._verify_md5()
        else:
            logger.info("Skipping MD5 verification for custom reference index.")
        
        # 2. Load Centroids
        data = np.load(self.reference_index_path)
        centroids_np = data["embeddings"]
        
        # Expected shape constraint (N_centroids, 384)
        if centroids_np.ndim != 2 or centroids_np.shape[1] != 384:
            raise RuntimeError(f"Expected reference index shape (N, 384), got {centroids_np.shape}")
            
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
    def calibrate_threshold(self, background_spectrograms: list[np.ndarray], batch_size: int = 32) -> tuple[float, np.ndarray]:
        """Calibrates threshold empirically (p99) on background samples."""
        if len(background_spectrograms) < self.n_background:
            logger.warning(f"Calibration expected {self.n_background} samples, got {len(background_spectrograms)}")
            
        all_novelty_scores = []
        for i in range(0, len(background_spectrograms), batch_size):
            batch = background_spectrograms[i:i+batch_size]
            results = self.score_spectrogram(batch, threshold=1.0) # threshold 1.0 ensures is_novel=False
            for res in results:
                all_novelty_scores.append(res["novelty_score"])
            
        scores_np = np.array(all_novelty_scores, dtype=np.float32)
        
        # Empirical percentile direct computation (Correction #3 implies no GEV)
        percentile_target = (1.0 - self.fpr) * 100.0
        threshold = float(np.percentile(scores_np, percentile_target))
        
        logger.info("[CALIBRATION] n_background: %d", len(background_spectrograms))
        logger.info("[CALIBRATION] novelty_score mean: %.4f", scores_np.mean())
        logger.info("[CALIBRATION] novelty_score std:  %.4f", scores_np.std())
        logger.info("[CALIBRATION] threshold (p%d):    %.4f", int(percentile_target), threshold)
        logger.info("[CALIBRATION] method: empirical_percentile")
        
        return threshold, scores_np

    @torch.no_grad()
    def score_spectrogram(self, spectrogram_arrays: list[np.ndarray], threshold: float) -> list[dict]:
        """Runs the entire MIL patch-level scoring pipeline on a batch of images.
        
        spectrogram_arrays: list of (256, 256, 3) uint8 numpy arrays.
        """
        # Convert to PIL Images and apply transforms
        tensors = []
        for arr in spectrogram_arrays:
            img = Image.fromarray(arr)
            tensors.append(self.transform(img))
            
        # Stack into (B, 3, 256, 256)
        batch_tensor = torch.stack(tensors).to(self.device)
        
        # 1. Forward Features
        features = self.model.forward_features(batch_tensor)
        patch_tokens = features["x_norm_patchtokens"] # (B, 1369, 384)
        
        # 2. L2 Normalize explicitly
        patch_tokens = F.normalize(patch_tokens, p=2, dim=-1)
        
        # 3. Cosine Similarity vs Background
        # similarities = (B, 1369, 281)
        similarities = torch.matmul(patch_tokens, self.centroids.T)
        max_sims, _ = torch.max(similarities, dim=-1) # (B, 1369)
        
        # 4. Anomaly Scores (1 - sim)
        anomaly_scores = 1.0 - max_sims # (B, 1369)
        
        # 5. Top-K Pooling
        top_k_scores, top_k_indices = torch.topk(anomaly_scores, self.k, dim=-1) # (B, K)
        novelty_scores = top_k_scores.mean(dim=-1) # (B,)
        
        # 6. MIL Vector Extraction
        results = []
        for i in range(len(spectrogram_arrays)):
            k_idx = top_k_indices[i] # (K,)
            top_k_patches = patch_tokens[i][k_idx] # (K, 384)
            mil_vector = top_k_patches.mean(dim=0)
            mil_vector = F.normalize(mil_vector, p=2, dim=-1)
            
            n_score = float(novelty_scores[i].cpu().item())
            
            results.append({
                "novelty_score": n_score,
                "is_novel": n_score > threshold,
                "top_k_indices": k_idx.cpu().numpy().astype(np.int32),
                "mil_vector": mil_vector.cpu().numpy().astype(np.float32),
                "patch_anomaly_scores": anomaly_scores[i].cpu().numpy().astype(np.float32)
            })
            
        return results
