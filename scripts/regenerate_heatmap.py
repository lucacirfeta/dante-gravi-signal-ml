import pandas as pd
import numpy as np
import h5py
from pathlib import Path
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize
from scipy.cluster import hierarchy
import matplotlib.pyplot as plt

def regenerate():
    production_dir = Path("data/production")
    output_dir = production_dir / "aggregated"
    master_csv = output_dir / "Master_Taxonomy_O4a.csv"

    print("Loading Master_Taxonomy_O4a.csv...")
    if not master_csv.exists():
        print(f"Error: {master_csv} not found.")
        return

    df = pd.read_csv(master_csv)
    mil_vectors = []
    candidate_metadata = []

    print(f"Reading vectors for {len(df)} candidates...")
    for idx, row in df.iterrows():
        gps = row["gps_start"]
        session = row["session_id"]
        det = row["detector"]
        
        h5_path = production_dir / str(session) / f"novelties_{session}_{det}.h5"
        if not h5_path.exists():
            continue
            
        try:
            with h5py.File(h5_path, "r") as f:
                if "novelties/gps_times" not in f or "novelties/mil_vectors" not in f:
                    continue
                    
                gps_times = f["novelties/gps_times"][:]
                vectors = f["novelties/mil_vectors"][:]
                
                idx_match = np.where(gps_times == gps)[0]
                if len(idx_match) == 0:
                    continue
                    
                vec = vectors[idx_match[0]]
                mil_vectors.append(vec)
                candidate_metadata.append({
                    "gps": float(gps),
                    "detector": det
                })
        except Exception as e:
            pass

    print(f"Found {len(mil_vectors)} valid vectors. Computing similarity matrix...")
    if len(mil_vectors) > 1:
        X = np.vstack(mil_vectors)
        X_norm = normalize(X, norm='l2', axis=1)
        sim_matrix = cosine_similarity(X_norm)
        
        dist_matrix = 1.0 - sim_matrix
        dist_matrix = np.clip((dist_matrix + dist_matrix.T) / 2, 0, None)
        np.fill_diagonal(dist_matrix, 0)
        
        from scipy.spatial.distance import squareform
        condensed_dist = squareform(dist_matrix)
        
        print("Clustering...")
        linkage_mat = hierarchy.linkage(condensed_dist, method='single')
        order = hierarchy.leaves_list(linkage_mat)
        sim_matrix_ordered = sim_matrix[order, :][:, order]
        
        n_valid = len(mil_vectors)
        print(f"Plotting heatmap for n={n_valid}...")
        plt.figure(figsize=(12, 10))
        if n_valid <= 500:
            import seaborn as sns
            labels = [f"{candidate_metadata[i]['gps']}_{candidate_metadata[i]['detector']}" for i in order]
            ax = sns.heatmap(
                sim_matrix_ordered, 
                cmap="viridis", 
                xticklabels=labels, 
                yticklabels=labels,
                cbar_kws={'label': 'Cosine Similarity'}
            )
            ax.set_xticklabels(ax.get_xticklabels(), rotation=90, fontsize=4)
            ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=4)
        else:
            plt.imshow(sim_matrix_ordered, cmap="viridis", aspect="auto", interpolation="none")
            plt.colorbar(label='Cosine Similarity')
            plt.xticks([])
            plt.yticks([])
            
        plt.title(f"Cross-Session Morphological Similarity (n={n_valid})")
        plt.tight_layout()
        out_path = output_dir / "candidate_similarity_heatmap.png"
        plt.savefig(out_path, dpi=300)
        plt.close()
        print(f"Success! Heatmap saved to {out_path}")
    else:
        print("Not enough vectors found.")

if __name__ == "__main__":
    regenerate()
