import numpy as np
from sklearn.decomposition import PCA
import torch
import torch.nn.functional as F

def run_pca_distortion_test(n_samples=140, d_original=384, seed=42):
    np.random.seed(seed)
    torch.manual_seed(seed)
    
    # Generate synthetic embeddings on the hypersphere
    # We use a mix of clusters to simulate the 140 candidates
    X_raw = np.random.randn(n_samples, d_original)
    # Add some cluster structure
    X_raw[:50] += np.random.randn(1, d_original) * 2.0
    X_raw[50:100] += np.random.randn(1, d_original) * 2.0
    
    X_tensor = torch.tensor(X_raw, dtype=torch.float32)
    X_norm = F.normalize(X_tensor, p=2, dim=1) # (140, 384)
    
    # Original Cosine Similarity Matrix
    sim_original = torch.mm(X_norm, X_norm.T).numpy()
    
    # Dynamic PCA as implemented in the pipeline: d_90% or min(20, n-1)
    pca_full = PCA()
    pca_full.fit(X_norm.numpy())
    cumulative_variance = np.cumsum(pca_full.explained_variance_ratio_)
    d_90 = np.argmax(cumulative_variance >= 0.90) + 1
    
    d_pca = max(d_90, min(20, n_samples - 1))
    print(f"Original D: {d_original} | Reduced D: {d_pca} (Retained Variance: {cumulative_variance[d_pca-1]*100:.2f}%)")
    
    # Apply PCA
    pca = PCA(n_components=d_pca)
    X_pca = pca.fit_transform(X_norm.numpy())
    
    # Re-normalize on the reduced hypersphere (because DPMM uses cosine/Euclidean on normalized)
    # Actually, DPMM in our code uses Euclidean, but on PCA projected vectors.
    # We measure distortion in Cosine Space since we talk about hypersphere distortion.
    X_pca_tensor = torch.tensor(X_pca, dtype=torch.float32)
    X_pca_norm = F.normalize(X_pca_tensor, p=2, dim=1)
    
    # Projected Cosine Similarity Matrix
    sim_projected = torch.mm(X_pca_norm, X_pca_norm.T).numpy()
    
    # Calculate Error (excluding diagonal)
    mask = ~np.eye(n_samples, dtype=bool)
    diff = np.abs(sim_original[mask] - sim_projected[mask])
    
    mae = np.mean(diff)
    max_err = np.max(diff)
    p99_err = np.percentile(diff, 99)
    
    print("-" * 50)
    print("GEOMETRIC DISTORTION METRICS (Cosine Similarity)")
    print(f"Mean Absolute Error: {mae:.5f}")
    print(f"99th Percentile Err: {p99_err:.5f}")
    print(f"Maximum Error:       {max_err:.5f}")
    print("-" * 50)

if __name__ == "__main__":
    run_pca_distortion_test()
