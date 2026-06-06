import logging
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from src.encoder import DINOv2Encoder

logger = logging.getLogger(__name__)

class PatchLevelNoveltyDetector:
    """Detects anomalies using Patch-Level Multiple Instance Learning on DINOv2 tokens."""
    
    def __init__(self, reference_embeddings: np.ndarray, reference_labels: np.ndarray = None, device='cuda'):
        if device == 'cuda' and not torch.cuda.is_available():
            logger.warning("CUDA not available, falling back to CPU")
            device = 'cpu'
        self.device = device
        # Initialize the underlying encoder to get transforms and model
        self.encoder = DINOv2Encoder(device=device)
        
        # Load reference CLS embeddings onto GPU for fast similarity search
        self.reference_embeddings = torch.tensor(
            reference_embeddings, dtype=torch.float32, device=self.device
        )
        self.reference_labels = reference_labels

    def extract_patch_tokens(self, spectrogram_path) -> torch.Tensor:
        """Extracts and normalizes the 1369 patch tokens from a spectrogram.
        
        Args:
            spectrogram_path: Path to the image file
            
        Returns:
            torch.Tensor: (1369, 384) L2-normalized tensor on GPU
        """
        img = Image.open(spectrogram_path)
        # Apply standard DINOv2 transform
        tensor = self.encoder.transform(img).unsqueeze(0).to(self.device)
        
        with torch.inference_mode():
            # forward_features returns a dict, we want 'x_norm_patchtokens'
            features = self.encoder.model.forward_features(tensor)
            patch_tokens = features['x_norm_patchtokens'].squeeze(0) # Shape: (1369, 384)
            
        # Explicit L2 normalization on the embedding dimension
        patch_tokens = F.normalize(patch_tokens, p=2, dim=-1)
        return patch_tokens

    def compute_patch_anomaly_scores(self, patch_tokens: torch.Tensor) -> np.ndarray:
        """Computes anomaly score (1 - max cosine similarity) for each patch.
        
        Args:
            patch_tokens: (1369, 384) tensor of normalized patch embeddings
            
        Returns:
            np.ndarray: (1369,) array of anomaly scores on CPU
        """
        batch_size = 256
        n_ref = self.reference_embeddings.shape[0]
        max_sims = torch.full((patch_tokens.shape[0],), -float('inf'), device=self.device)
        
        # Batch over the reference embeddings to prevent GPU OOM
        for start in range(0, n_ref, batch_size):
            end = min(start + batch_size, n_ref)
            ref_batch = self.reference_embeddings[start:end] # (B, 384)
            
            # Cosine similarity matrix: (1369, B)
            # Both matrices are L2 normalized, so dot product is cosine similarity
            sims = torch.matmul(patch_tokens, ref_batch.T) 
            
            # Max over this batch
            batch_max_sims, _ = torch.max(sims, dim=1) # (1369,)
            max_sims = torch.maximum(max_sims, batch_max_sims)
            
        # Anomaly score = 1.0 - max_sim (higher is more anomalous)
        anomaly_scores = 1.0 - max_sims
        return anomaly_scores.cpu().numpy()

    def compute_novelty_score(self, patch_anomaly_scores: np.ndarray, k: int = 37) -> float:
        """Condenses the spatial anomaly map into a single global score.
        
        Uses the mean of the log of the top-k highest anomaly scores.
        
        Args:
            patch_anomaly_scores: (1369,) array of patch-level anomaly scores
            k: Number of top patches to consider
            
        Returns:
            float: Global novelty score
        """
        # Sort and select the top-k highest anomaly scores
        top_k_scores = np.sort(patch_anomaly_scores)[-k:]
        
        # Mean of the top-k highest anomaly scores
        novelty_score = np.mean(top_k_scores)
        
        return float(novelty_score)

    def classify(self, spectrogram_path, k: int = 37, threshold: float = None) -> dict:
        """Executes full patch-level pipeline and returns classification dictionary.
        
        Args:
            spectrogram_path: Path to the image
            k: Number of patches for MIL scoring
            threshold: Dynamic novelty threshold. If score > threshold, status is NOVEL.
            
        Returns:
            dict: Classification results and patch metadata
        """
        patch_tokens = self.extract_patch_tokens(spectrogram_path)
        anomaly_scores = self.compute_patch_anomaly_scores(patch_tokens)
        novelty_score = self.compute_novelty_score(anomaly_scores, k=k)
        
        # Indices of the top k patches (descending order of anomaly)
        top_k_indices = np.argsort(anomaly_scores)[-k:][::-1].tolist()
        
        status = "UNKNOWN"
        if threshold is None:
            logger.warning("No threshold provided to classify(), returning UNKNOWN status.")
        else:
            # Because novelty_score is less negative for anomalies, NOVEL is > threshold
            if novelty_score > threshold:
                status = "NOVEL"
            else:
                status = "KNOWN"
                
        return {
            "novelty_score": novelty_score,
            "patch_anomaly_scores": anomaly_scores.tolist(),
            "top_k_indices": top_k_indices,
            "novelty_status": status,
            "k_used": k
        }
