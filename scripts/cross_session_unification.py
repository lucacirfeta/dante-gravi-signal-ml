import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
import os

def main():
    print("Loading data...")
    data_dir = 'data/production/aggregated'
    sim_file = os.path.join(data_dir, 'candidate_similarity.json')
    t3a_file = os.path.join(data_dir, 'Table_3a_Confirmed_Local_Glitches.csv')
    t3b_file = os.path.join(data_dir, 'Table_3b_Unverifiable_Unilateral_Detections.csv')
    
    with open(sim_file, 'r') as f:
        data = json.load(f)
    
    metadata = data['candidates_metadata']
    S = np.array(data['similarity_matrix'])
    N = len(metadata)
    
    print(f"Loaded similarity matrix of shape {S.shape}")
    
    # Clip similarities and compute distance
    S = np.clip(S, -1.0, 1.0)
    # Fill diagonal with 1.0 just in case
    np.fill_diagonal(S, 1.0)
    
    # Distance matrix (using 1 - S as mentioned in the paper)
    # Ward linkage expects condensed distance matrix or observation vectors, 
    # but scipy's linkage can take a condensed distance matrix.
    from scipy.spatial.distance import squareform
    # Symmetrize just in case
    S = (S + S.T) / 2
    D = np.clip(1.0 - S, 0.0, 2.0)
    # Ensure diagonal is exactly 0
    np.fill_diagonal(D, 0.0)
    condensed_D = squareform(D)
    
    print("Computing Single linkage...")
    # We use single linkage to find connected components where any edge is < 0.25 (sim > 0.75)
    Z = linkage(condensed_D, method='single')
    
    # Extract clusters using distance threshold 0.25 (which corresponds to sim=0.75)
    families = fcluster(Z, t=0.25, criterion='distance')
    
    # Print cluster sizes
    unique_fams, counts = np.unique(families, return_counts=True)
    print(f"Found {len(unique_fams)} Global Families at sim >= 0.75.")
    print("Cluster sizes:", dict(zip(unique_fams, counts)))
    
    # Append Global_Family_ID to metadata
    for i, meta in enumerate(metadata):
        meta['Global_Family_ID'] = f"GF_{families[i]}"
        meta['idx'] = i

    # Transitivity resolution for Table 3b
    # A Table 3b candidate is resolved if S > 0.75 with ANY Table 3a candidate.
    t3a_indices = [i for i, m in enumerate(metadata) if m['table'] == '3a']
    t3b_indices = [i for i, m in enumerate(metadata) if m['table'] == '3b']
    
    for i in t3b_indices:
        # Find max similarity with any 3a candidate
        if len(t3a_indices) > 0:
            sims_with_3a = S[i, t3a_indices]
            max_idx = np.argmax(sims_with_3a)
            max_sim = sims_with_3a[max_idx]
            best_3a_meta = metadata[t3a_indices[max_idx]]
            if max_sim > 0.75:
                metadata[i]['Resolution_State'] = f"RESOLVED via {best_3a_meta['Global_Family_ID']} (sim={max_sim:.2f})"
            else:
                metadata[i]['Resolution_State'] = "UNRESOLVED"
        else:
            metadata[i]['Resolution_State'] = "UNRESOLVED"
            
    # For 3a candidates, they are the truth, so state is CONFIRMED
    for i in t3a_indices:
        metadata[i]['Resolution_State'] = "CONFIRMED (Table 3a)"
        
    # Reorder the matrix according to linkage
    from scipy.cluster.hierarchy import leaves_list
    order = leaves_list(Z)
    S_ordered = S[order, :][:, order]
    
    # Plot grouped heatmap
    print("Generating block heatmap...")
    plt.figure(figsize=(10, 8))
    sns.heatmap(S_ordered, cmap='cividis', vmin=0, vmax=1, xticklabels=False, yticklabels=False)
    plt.title("Cross-Session Morphological Transitivity (Reordered by Ward Linkage)")
    # Draw block boundaries (approximation using cluster sizes)
    # Let's find where the cluster ID changes in the ordered list
    ordered_fams = families[order]
    boundaries = np.where(ordered_fams[:-1] != ordered_fams[1:])[0] + 1
    for b in boundaries:
        plt.axhline(b, color='red', lw=0.5, ls='--')
        plt.axvline(b, color='red', lw=0.5, ls='--')
        
    plt.tight_layout()
    # Save both locally and directly to the paper img folder
    plt.savefig('data/production/aggregated/grouped_heatmap.png', dpi=300)
    plt.savefig('paper_draft/springer/img/fig_heatmap_transitivity.png', dpi=300)
    plt.close()
    print("Saved fig_heatmap_transitivity.png")
    
    # Update CSV files
    print("Updating CSV files...")
    df_3a = pd.read_csv(t3a_file)
    df_3b = pd.read_csv(t3b_file)
    
    # Create lookup dicts using GPS and detector
    meta_dict = {(m['gps'], m['detector']): m for m in metadata}
    
    def get_family(row):
        return meta_dict.get((row['gps_start'], row['detector']), {}).get('Global_Family_ID', 'UNKNOWN')
        
    def get_resolution(row):
        return meta_dict.get((row['gps_start'], row['detector']), {}).get('Resolution_State', 'UNKNOWN')
        
    df_3a['Global_Family_ID'] = df_3a.apply(get_family, axis=1)
    df_3a['Resolution_State'] = df_3a.apply(get_resolution, axis=1)
    
    df_3b['Global_Family_ID'] = df_3b.apply(get_family, axis=1)
    df_3b['Resolution_State'] = df_3b.apply(get_resolution, axis=1)
    
    df_3a.to_csv(t3a_file.replace('.csv', '_unified.csv'), index=False)
    df_3b.to_csv(t3b_file.replace('.csv', '_unified.csv'), index=False)
    print("Saved updated CSVs as _unified.csv")
    
    # Print stats
    resolved = sum(1 for m in metadata if m['table'] == '3b' and 'RESOLVED' in m.get('Resolution_State', ''))
    unresolved = sum(1 for m in metadata if m['table'] == '3b' and 'UNRESOLVED' in m.get('Resolution_State', ''))
    singletons = sum(1 for c in counts if c == 1)
    main_clusters = sum(1 for c in counts if c > 1)
    
    print("\n--- STATS FOR PAPER ---")
    print(f"Total candidates: {N}")
    print(f"Global Families identified: {len(unique_fams)}")
    print(f"Main clusters (size >= 2): {main_clusters}")
    print(f"Singletons (isolated transients): {singletons}")
    print(f"Table 3a Local Glitches: {len(t3a_indices)}")
    print(f"Table 3b Unverifiable Detections: {len(t3b_indices)}")
    print(f"Table 3b RESOLVED via Transitivity: {resolved}")
    print(f"Table 3b UNRESOLVED: {unresolved}")
    
if __name__ == '__main__':
    main()
