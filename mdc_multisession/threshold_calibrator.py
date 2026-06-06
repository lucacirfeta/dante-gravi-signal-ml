"""Calibrates the operational threshold using Generalized Extreme Value (GEV) distribution."""

import logging
import numpy as np
from scipy.stats import genextreme

logger = logging.getLogger(__name__)

def calibrate_tau_op(s_max: np.ndarray, fpr: float = 0.0001, block_size: int = 100) -> float:
    """Fit a GEV distribution to the anomaly scores and compute the operational threshold.
    
    Since s_max is bounded by 1, we compute the distance (1 - s_max) which represents
    the anomaly score. The Fisher-Tippett-Gnedenko theorem dictates that the block maxima
    of these scores converge to a GEV distribution.
    
    Args:
        s_max: 1D array of top-1 cosine similarities.
        fpr: Target False Positive Rate per sample (e.g., 0.0001 for 0.01%).
        block_size: Number of samples per block for computing maxima.
        
    Returns:
        float: The calibrated tau_op threshold.
    """
    logger.info(f"Calibrating tau_op using GEV fit on {len(s_max)} samples (block_size={block_size}) with FPR={fpr}")
    
    # Distance metric (anomaly score)
    distances = 1.0 - s_max
    
    # Create block maxima
    n_blocks = len(distances) // block_size
    if n_blocks == 0:
        logger.warning("Not enough samples for even one block. Falling back to non-parametric threshold.")
        return float(np.percentile(s_max, fpr * 100))
        
    d_blocks = distances[:n_blocks*block_size].reshape(n_blocks, block_size)
    d_maxima = np.max(d_blocks, axis=1)
    
    # Fit GEV to the block maxima
    c, loc, scale = genextreme.fit(d_maxima)
    logger.info(f"GEV fit parameters: c={c:.4f}, loc={loc:.4f}, scale={scale:.4f}")
    
    # For a target sample-level FPR:
    # P(Sample > tau) = FPR
    # P(max(N samples) < tau) = (1 - FPR)^N
    q_block = (1.0 - fpr) ** block_size
    
    tau_dist = genextreme.ppf(q_block, c, loc=loc, scale=scale)
    
    # Convert back to similarity threshold
    tau_op = 1.0 - tau_dist
    
    logger.info(f"Calibrated tau_op: {tau_op:.4f} (at distance {tau_dist:.4f})")
    
    return float(tau_op)
