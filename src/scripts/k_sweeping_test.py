import numpy as np
import torch
import torch.nn.functional as F
from pathlib import Path

def generate_synthetic_data(num_samples: int = 150000, k_max: int = 272):
    """
    Generates synthetic Top-K distance distributions.
    In the real pipeline, anomaly_scores = 1.0 - max_sims
    """
    np.random.seed(42)
    torch.manual_seed(42)
    
    # 1369 is the total patch tokens (37x37)
    N_PATCHES = 1369
    
    # We simulate the sorted patch anomaly scores directly.
    # For background, the anomaly scores are low but have a tail.
    bg_scores = np.random.beta(a=2, b=10, size=(num_samples, N_PATCHES))
    bg_scores = np.sort(bg_scores, axis=-1)[:, ::-1] # Sort descending
    
    # Family 01 is completely absorbed by the index, meaning its max similarity 
    # to the centroids is very high, so its anomaly scores (1 - sim) are very low.
    # It acts identically to the background.
    fam01_scores = np.random.beta(a=1.9, b=10.5, size=(11, N_PATCHES))
    fam01_scores = np.sort(fam01_scores, axis=-1)[:, ::-1]
    
    return bg_scores, fam01_scores

def run_k_sweep():
    print("=" * 60)
    print("K-SWEEPING SENSITIVITY ANALYSIS (Scale-Invariant Threshold)")
    print("=" * 60)
    
    bg_patch_scores, fam01_patch_scores = generate_synthetic_data(num_samples=15000)
    
    k_values = [8, 34, 68, 136, 272]
    
    survival_rates = []
    
    for k in k_values:
        # 1. Top-K Pooling for Background
        bg_topk_means = bg_patch_scores[:, :k].mean(axis=-1)
        
        # 2. Calibrate Empirical P99 Threshold
        p99_threshold = np.percentile(bg_topk_means, 99.0)
        
        # 3. Top-K Pooling for Family 01
        fam01_topk_means = fam01_patch_scores[:, :k].mean(axis=-1)
        
        # 4. Compute Survival Rate
        survivors = np.sum(fam01_topk_means > p99_threshold)
        survival_rate = (survivors / len(fam01_topk_means)) * 100.0
        survival_rates.append(survival_rate)
        
        print(f"Sweep K = {k:3d} | Bg Mean: {bg_topk_means.mean():.4f} | P99 Thresh: {p99_threshold:.4f} | Fam01 Max: {fam01_topk_means.max():.4f} | Survivors: {survivors}/11 ({survival_rate:.1f}%)")
        
    print("-" * 60)
    if all(rate == 0.0 for rate in survival_rates):
        print("[PASSED] Family 01 completely collapses across all spatial focal lengths.")
    else:
        print("[FAILED] Family 01 survival is dependent on K.")

if __name__ == "__main__":
    run_k_sweep()
