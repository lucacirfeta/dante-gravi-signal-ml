import hashlib
import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from src.core.encoder import build_dinov2_transform
from src.core.artifact_manifest import resolve_reference_index
from src.core.index_contract import sha256_file
from src.core.model_loader import load_dinov2_model
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
        k_ablations: list[int] | None = None,
        fpr: float = 0.01,
        n_background: int = 500,
        seed: int = 42,
        verify_md5: bool = True,
        expected_sha256: str | None = None,
        artifact_manifest_path: str | Path | None = None,
        model: torch.nn.Module | None = None,
    ):
        self.device = torch.device(device) if device else get_device()
        self.k = k
        self.k_ablations = k_ablations or []
        self.fpr = fpr
        self.n_background = n_background
        self.seed = seed
        self.reference_index_path = Path(reference_index_path)
        self.expected_sha256 = expected_sha256
        self.artifact_manifest_path = artifact_manifest_path
        
        # 1. Immutable index verification. ``verify_md5`` is retained as a
        # backward-compatible argument name; verification is SHA-256 based.
        if verify_md5:
            self._verify_md5()
        else:
            self.reference_sha256 = sha256_file(self.reference_index_path)
            self.reference_md5 = self._legacy_md5()
            self.index_integrity_verified = False
            self.index_artifact_id = None
            logger.warning(
                "Reference index integrity verification explicitly disabled: %s",
                self.reference_index_path,
            )
        
        # 2. Load Centroids
        with np.load(self.reference_index_path, allow_pickle=False) as data:
            centroids_np = np.asarray(data["embeddings"], dtype=np.float32)
        
        # Expected shape constraint (N_centroids, 384)
        if centroids_np.ndim != 2 or centroids_np.shape[1] != 384:
            raise RuntimeError(f"Expected reference index shape (N, 384), got {centroids_np.shape}")
        if verify_md5 and self.reference_index_spec.n_centroids >= 0:
            expected_shape = (
                self.reference_index_spec.n_centroids,
                self.reference_index_spec.embedding_dim,
            )
            if centroids_np.shape != expected_shape:
                raise RuntimeError(
                    f"Reference index shape {centroids_np.shape} violates "
                    f"manifest contract {expected_shape}"
                )
            
        self.centroids = torch.tensor(centroids_np, device=self.device, dtype=torch.float32)
        # Explicit L2 normalization
        self.centroids = F.normalize(self.centroids, p=2, dim=-1)
        
        # 3. Load DINOv2
        self.model = model
        if self.model is None:
            self.model = load_dinov2_model(self.device)
        self.model.eval()
        for param in self.model.parameters():
            param.requires_grad = False
        self.model.to(self.device)
        
        # 4. Transform
        self.transform = build_dinov2_transform()
        
        logger.info(f"PatchScorer initialized on {self.device}. k={self.k}, FPR={self.fpr}")
        
    def _legacy_md5(self) -> str:
        hash_md5 = hashlib.md5()
        with open(self.reference_index_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _verify_md5(self):
        """Verify the per-index SHA-256 contract (legacy method name)."""
        self.reference_index_spec = resolve_reference_index(
            self.reference_index_path,
            manifest_path=self.artifact_manifest_path,
        )
        manifest_sha256 = self.reference_index_spec.sha256
        if (
            self.expected_sha256 is not None
            and self.expected_sha256.lower() != manifest_sha256
        ):
            raise RuntimeError(
                "Caller SHA-256 and artifact manifest disagree for "
                f"{self.reference_index_path}: {self.expected_sha256} != "
                f"{manifest_sha256}"
            )
        actual_sha256 = sha256_file(self.reference_index_path)
        if actual_sha256 != manifest_sha256:
            raise RuntimeError(
                "SHA-256 mismatch for reference index! Expected "
                f"{manifest_sha256}, got {actual_sha256}"
            )
        self.reference_sha256 = actual_sha256
        self.reference_md5 = self._legacy_md5()
        self.index_integrity_verified = True
        self.index_artifact_id = self.reference_index_spec.artifact_id
        logger.info(
            "Reference SHA-256 verified: %s (%s)",
            self.reference_sha256,
            self.index_artifact_id,
        )

    @torch.no_grad()
    def calibrate_threshold(self, background_spectrograms: list[np.ndarray], batch_size: int = 32) -> tuple[float, np.ndarray, dict]:
        """Calibrates threshold empirically (p99) on background samples."""
        if len(background_spectrograms) < self.n_background:
            logger.warning(f"Calibration expected {self.n_background} samples, got {len(background_spectrograms)}")
            
        all_novelty_scores = []
        import gc
        for i in range(0, len(background_spectrograms), batch_size):
            batch = background_spectrograms[i:i+batch_size]
            results = self.score_spectrogram(batch, threshold=1.0) # threshold 1.0 ensures is_novel=False
            for res in results:
                all_novelty_scores.append(res["novelty_score"])
                
            # Explicit garbage collection to prevent DINOv2 VRAM fragmentation
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            
        scores_np = np.array(all_novelty_scores, dtype=np.float32)
        
        # Empirical percentile direct computation (Correction #3 implies no GEV)
        percentile_target = (1.0 - self.fpr) * 100.0
        threshold = float(np.percentile(scores_np, percentile_target))
        
        # GEV fitting on bulk population is a mathematical fallacy according to EVT.
        # We strictly avoid it and set parameters to None to prevent downstream reporting of invalid metrics.
        gev_params = {"mu": None, "sigma": None, "xi": None}
        
        logger.info("[CALIBRATION] n_background: %d", len(background_spectrograms))
        logger.info("[CALIBRATION] novelty_score mean: %.4f", scores_np.mean())
        logger.info("[CALIBRATION] novelty_score std:  %.4f", scores_np.std())
        logger.info("[CALIBRATION] threshold (p%d):    %.4f", int(percentile_target), threshold)
        logger.info("[CALIBRATION] method: empirical_percentile only (GEV strictly rejected)")
        
        return threshold, scores_np, gev_params

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
            
            # Compute ablation scores for different k values seamlessly
            ablation_k_scores = {}
            if hasattr(self, 'k_ablations') and self.k_ablations:
                for ab_k in self.k_ablations:
                    ab_k = min(ab_k, anomaly_scores.shape[-1])
                    ab_score = anomaly_scores[i].topk(ab_k)[0].mean().item()
                    ablation_k_scores[f"k_{ab_k}"] = ab_score
            
            results.append({
                "novelty_score": n_score,
                "ablation_k_scores": ablation_k_scores,
                "is_novel": n_score > threshold,
                "top_k_indices": k_idx.cpu().numpy().astype(np.int32),
                "mil_vector": mil_vector.cpu().numpy().astype(np.float32),
                "patch_anomaly_scores": anomaly_scores[i].cpu().numpy().astype(np.float32)
            })
            
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        return results
