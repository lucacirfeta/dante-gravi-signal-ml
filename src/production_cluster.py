import json
import logging
from pathlib import Path
from typing import Dict, Any

import h5py
import numpy as np
import torch
import torch.nn.functional as F
from sklearn.mixture import BayesianGaussianMixture
import matplotlib.pyplot as plt
import seaborn as sns

logger = logging.getLogger(__name__)

class H5Clusterer:
    def __init__(self, h5_path: Path, output_dir: Path):
        self.h5_path = Path(h5_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def run_clustering(self) -> Dict[str, Any]:
        """Runs DPMM and UMAP on the extracted novelties, returning a report dictionary."""
        logger.info(f"Loading data from HDF5: {self.h5_path}")
        
        with h5py.File(self.h5_path, 'r') as f:
            if "novelties" not in f:
                raise ValueError(f"No 'novelties' group found in {self.h5_path}")
                
            nov_grp = f["novelties"]
            gps_times = nov_grp["gps_times"][:]
            mil_vectors = nov_grp["mil_vectors"][:]
            nov_scores = nov_grp["nov_scores"][:]
            
        n_samples = len(gps_times)
        logger.info(f"Loaded {n_samples} novel segments for clustering.")
        
        if n_samples == 0:
            logger.warning("No anomalies found. Skipping clustering.")
            return {}
            
        # 1. Enforce strict L2 normalization mathematically (shape is 768D)
        # Note: PyTorch tensor conversion is used for speed, then back to numpy
        vectors_t = torch.from_numpy(mil_vectors)
        vectors_norm = F.normalize(vectors_t, p=2, dim=-1).numpy()
        
        # 2. DPMM Clustering on full 768D space
        # We set n_components high, DPMM will prune unused clusters
        max_components = min(30, n_samples)
        logger.info(f"Running BayesianGaussianMixture on full {vectors_norm.shape[1]}D vectors...")
        
        dpmm = BayesianGaussianMixture(
            n_components=max_components,
            covariance_type='full',
            weight_concentration_prior_type='dirichlet_process',
            weight_concentration_prior=0.01, # Encourage sparsity
            max_iter=500,
            n_init=3,
            random_state=42
        )
        
        # Fit and predict labels
        labels = dpmm.fit_predict(vectors_norm)
        
        # 3. UMAP for 2D Visualization only
        logger.info("Running UMAP for 2D visualization projection...")
        import umap
        reducer = umap.UMAP(
            n_components=2,
            metric='cosine',
            n_neighbors=min(15, n_samples - 1) if n_samples > 15 else n_samples - 1,
            min_dist=0.1,
            random_state=42
        )
        coords_2d = reducer.fit_transform(vectors_norm)
        
        # 4. Generate JSON Report
        report = {
            "h5_source": str(self.h5_path),
            "n_samples": int(n_samples),
            "n_active_clusters": int(len(np.unique(labels))),
            "clusters": {}
        }
        
        unique_labels = np.unique(labels)
        for lbl in unique_labels:
            mask = (labels == lbl)
            lbl_gps = gps_times[mask].tolist()
            lbl_scores = nov_scores[mask].tolist()
            
            report["clusters"][str(lbl)] = {
                "size": int(np.sum(mask)),
                "mean_score": float(np.mean(lbl_scores)),
                "gps_times": lbl_gps
            }
            
        report_path = self.output_dir / f"cluster_report_{self.h5_path.stem}.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=4)
        logger.info(f"Saved cluster report to {report_path}")
        
        # 5. Generate 2D Scatter Plot
        self._plot_umap(coords_2d, labels, nov_scores)
        
        return report

    def _plot_umap(self, coords: np.ndarray, labels: np.ndarray, scores: np.ndarray):
        """Generates and saves a 2D UMAP scatter plot."""
        plt.figure(figsize=(12, 10))
        sns.set_theme(style="darkgrid")
        
        # Normalize scores for point sizes (min size 20, max 200)
        norm_scores = (scores - scores.min()) / (scores.max() - scores.min() + 1e-9)
        sizes = 20 + 180 * norm_scores
        
        # Convert labels to strings so they are treated strictly as categorical
        str_labels = [f"C{lbl}" for lbl in labels]
        
        # Determine number of clusters for palette
        n_clusters = len(np.unique(labels))
        palette_name = "tab20" if n_clusters <= 20 else "husl"
        
        scatter = sns.scatterplot(
            x=coords[:, 0], 
            y=coords[:, 1],
            hue=str_labels,
            palette=palette_name,
            size=sizes,
            sizes=(20, 200),
            alpha=0.8
        )
        
        plt.title(f"UMAP 2D Projection of Novelties (n={len(labels)}, clusters={n_clusters})", fontsize=16)
        plt.xlabel("UMAP 1")
        plt.ylabel("UMAP 2")
        
        # Fix the legend: remove the 'size' numeric values and use multiple columns if too long
        handles, leg_labels = scatter.get_legend_handles_labels()
        
        # Filter out the size markers (which are just floats) and keep only "C..." labels
        clean_handles = []
        clean_labels = []
        for h, l in zip(handles, leg_labels):
            if str(l).startswith("C"):
                clean_handles.append(h)
                clean_labels.append(l)
                
        # Split into 2 columns if there are more than 15 clusters
        ncol = 2 if len(clean_labels) > 15 else 1
        
        plt.legend(clean_handles, clean_labels, bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0, ncol=ncol, title="Clusters")
        
        plot_path = self.output_dir / f"umap_{self.h5_path.stem}.png"
        plt.tight_layout()
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved UMAP plot to {plot_path}")
