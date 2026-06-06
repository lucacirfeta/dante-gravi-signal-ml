"""Loads session embeddings and computes background s_max distribution."""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

def load_session_smax(run: str, session_id: str, detector: str, reference_path: str = "data/reference/indomain_o3b_h1.npz") -> np.ndarray:
    """Load session embeddings and compute the top-1 cosine similarity (s_max) against the reference index.
    
    Args:
        run: The run name (e.g., 'o4a')
        session_id: The session identifier
        detector: The detector (e.g., 'l1' or 'h1')
        reference_path: Path to the reference index
        
    Returns:
        np.ndarray: 1D array of s_max values for the session.
    """
    emb_path = Path(f"data/runs/{run.lower()}/{session_id}/embeddings/{run.lower()}_{detector.lower()}.npy")
    if not emb_path.exists():
        raise FileNotFoundError(f"Embeddings not found for {session_id} {detector}: {emb_path}")
        
    logger.info(f"Loading embeddings from {emb_path}")
    emb = np.load(emb_path)
    
    logger.info(f"Loading reference index from {reference_path}")
    ref_data = np.load(reference_path)
    ref_emb = ref_data['embeddings']
    
    logger.info(f"Computing cosine similarity for {emb.shape[0]} queries against {ref_emb.shape[0]} references")
    # Both are expected to be L2-normalized.
    # We can compute in chunks if memory is an issue, but for ~30k x 500 it's fine.
    
    chunk_size = 5000
    n_samples = emb.shape[0]
    s_max = np.zeros(n_samples, dtype=np.float32)
    
    for i in range(0, n_samples, chunk_size):
        end = min(i + chunk_size, n_samples)
        sims = emb[i:end] @ ref_emb.T
        s_max[i:end] = np.max(sims, axis=1)
        
    return s_max
