import numpy as np
from sklearn.decomposition import PCA
import torch
import torch.nn.functional as F

def run_real_pca_test():
    # Load actual centroids to get realistic ViT manifold geometry
    data = np.load('temp_index_1.npz')
    X_raw = data['embeddings'] # (1216, 384)
    
    n_samples = X_raw.shape[0]
    d_original = X_raw.shape[1]
    
    X_tensor = torch.tensor(X_raw, dtype=torch.float32)
    X_norm = F.normalize(X_tensor, p=2, dim=1)
    
    sim_original = torch.mm(X_norm, X_norm.T).numpy()
    
    # Run PCA to 90% variance
    pca_full = PCA()
    pca_full.fit(X_norm.numpy())
    cumulative_variance = np.cumsum(pca_full.explained_variance_ratio_)
    d_90 = np.argmax(cumulative_variance >= 0.90) + 1
    
    d_pca = max(d_90, min(20, n_samples - 1))
    
    pca = PCA(n_components=d_pca)
    X_pca = pca.fit_transform(X_norm.numpy())
    
    X_pca_tensor = torch.tensor(X_pca, dtype=torch.float32)
    X_pca_norm = F.normalize(X_pca_tensor, p=2, dim=1)
    
    sim_projected = torch.mm(X_pca_norm, X_pca_norm.T).numpy()
    
    mask = ~np.eye(n_samples, dtype=bool)
    diff = np.abs(sim_original[mask] - sim_projected[mask])
    
    mae = np.mean(diff)
    max_err = np.max(diff)
    p99_err = np.percentile(diff, 99)
    p90_err = np.percentile(diff, 90)
    
    print("-" * 50)
    print("REAL DINOv2 CENTROIDS PCA DISTORTION")
    print(f"Original D: {d_original} | Reduced D: {d_pca} (Retained Var: {cumulative_variance[d_pca-1]*100:.2f}%)")
    print(f"Mean Absolute Error: {mae:.5f}")
    print(f"90th Percentile Err: {p90_err:.5f}")
    print(f"99th Percentile Err: {p99_err:.5f}")
    print(f"Maximum Error:       {max_err:.5f}")
    print("-" * 50)

if __name__ == "__main__":
    run_real_pca_test()
