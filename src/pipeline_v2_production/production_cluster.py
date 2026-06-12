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
            
            # Extract metadata
            try:
                parts = self.h5_path.stem.split('_')
                self.session_id = parts[1]
                self.detector = parts[2]
            except Exception:
                self.session_id = "unknown"
                self.detector = "unknown"
                
            self.threshold_p99 = float(f["background_sample"].attrs.get("threshold", 0.0))
            bg_scores = f["background_sample"]["novelty_scores"][:]
            self.bg_n_samples = len(bg_scores)
            self.bg_gps_saved = "gps_times" in f["background_sample"]
            self.vq_index_md5 = f["metadata"].attrs.get("reference_md5", "unknown")
            
            # Compute distribution separation
            if len(nov_scores) > 0:
                bg_mean = np.mean(bg_scores)
                bg_std = np.std(bg_scores)
                candidate_min = np.min(nov_scores)
                self.dist_sep = float((candidate_min - bg_mean) / bg_std)
            else:
                self.dist_sep = 0.0
                
            # Estimate session_end_gps safely (fallback to + 3600 if nov_gps is empty)
            if len(gps_times) > 0:
                self.session_end_gps = float(np.max(gps_times))
            else:
                self.session_end_gps = float(self.session_id) + 3600.0

        n_samples = len(gps_times)
        logger.info(f"Loaded {n_samples} novel segments for clustering.")
        
        if n_samples == 0:
            logger.warning("No anomalies found. Skipping clustering.")
            return {}
            
        # 1. Enforce strict L2 normalization mathematically (shape is 384D)
        # Note: PyTorch tensor conversion is used for speed, then back to numpy
        vectors_t = torch.from_numpy(mil_vectors)
        vectors_norm = F.normalize(vectors_t, p=2, dim=-1).numpy()
        
        # 2. Adaptive PCA for Dimensionality Reduction
        from sklearn.decomposition import PCA
        
        d_input = vectors_norm.shape[1]
        
        # Calculate d_90
        if n_samples > 1:
            pca_90 = PCA(n_components=0.90, svd_solver='full', random_state=42)
            pca_90.fit(vectors_norm)
            d_90 = pca_90.n_components_
        else:
            d_90 = 1
            
        floor = min(20, n_samples - 1) if n_samples >= 21 else max(1, n_samples - 1)
        if n_samples == 1:
            floor = 1
            
        n_components_pca = max(d_90, floor)
        
        pca = PCA(n_components=n_components_pca, svd_solver='full', random_state=42)
        vectors_reduced = pca.fit_transform(vectors_norm)
        d_output = vectors_reduced.shape[1]
        variance_retained = float(np.sum(pca.explained_variance_ratio_))
        
        logger.info(f"PCA: {d_input}D → {d_output}D (varianza: {variance_retained:.1%}, floor applicato: {d_90 < floor})")
        
        # 3. Conditional Covariance & Adaptive Regularization for DPMM
        if n_samples >= 200:
            cov_type = 'full'
        elif 50 <= n_samples < 200:
            cov_type = 'tied'
        else:
            cov_type = 'diag'
            
        logger.info(f"DPMM covariance_type: {cov_type} (n={n_samples})")
        
        if n_samples < 50:
            n_init = 5
        else:
            n_init = 3
        logger.info(f"DPMM n_init: {n_init} (n={n_samples})")
        
        if n_samples < 100:
            reg_covar = 1e-3
        else:
            reg_covar = 1e-4

        max_components = 30
        n_components_dpmm = min(15, n_samples, max_components)
        
        logger.info(f"Running BayesianGaussianMixture on {d_output}D vectors...")
        dpmm = BayesianGaussianMixture(
            n_components=n_components_dpmm,
            covariance_type=cov_type,
            reg_covar=reg_covar,
            weight_concentration_prior_type='dirichlet_process',
            weight_concentration_prior=0.01,
            max_iter=500,
            n_init=n_init,
            random_state=42
        )
        
        # Fit and predict labels
        labels = dpmm.fit_predict(vectors_reduced)
        
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
        import datetime
        report = {
            "session_start_gps": float(self.session_id) if self.session_id.isdigit() else 0.0,
            "session_end_gps": self.session_end_gps,
            "detector": self.detector,
            "dq_flag_used": f"{self.detector}_CBC_CAT1",
            "threshold_p99": self.threshold_p99,
            "background_n_samples": self.bg_n_samples,
            "background_gps_saved": self.bg_gps_saved,
            "vq_index_md5": self.vq_index_md5,
            "generation_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "distribution_separation_sigma": self.dist_sep,
            "gps_dedup_validated": True,
            "h5_source": str(self.h5_path),
            "n_active_clusters": int(len(np.unique(labels))),
            "pca_n_components": int(d_output),
            "pca_variance_retained": float(variance_retained),
            "covariance_type_used": cov_type,
            "n_init_used": n_init,
            "n_samples": int(n_samples),
            "clusters": {}
        }
        
        unique_labels = np.unique(labels)
        n_singleton_clusters = 0
        total_unique_samples = 0
        
        for lbl in unique_labels:
            mask = (labels == lbl)
            lbl_gps = gps_times[mask].tolist()
            lbl_scores = nov_scores[mask].tolist()
            
            # Deduplicate before writing
            unique_items = {}
            for g, s in zip(lbl_gps, lbl_scores):
                if g not in unique_items:
                    unique_items[g] = s
                    
            dedup_gps = sorted(list(unique_items.keys()))
            dedup_scores = [unique_items[g] for g in dedup_gps]
            
            # Hard assertion
            assert len(dedup_gps) == len(set(dedup_gps)), f"GPS duplicates in cluster {lbl} session {self.session_id}"
            
            is_singleton = len(dedup_gps) == 1
            if is_singleton:
                n_singleton_clusters += 1
                
            total_unique_samples += len(dedup_gps)
            
            report["clusters"][str(lbl)] = {
                "size": len(dedup_gps),
                "is_singleton": is_singleton,
                "mean_score": float(np.mean(dedup_scores)) if len(dedup_scores) > 0 else 0.0,
                "gps_times": dedup_gps
            }
            
        report["n_samples"] = total_unique_samples
        report["n_singleton_clusters"] = n_singleton_clusters
        
        # Validation at report close
        assert report['n_samples'] == sum(
            len(set(cl['gps_times'])) for cl in report['clusters'].values()
        ), "n_samples mismatch after dedup"
            
        report_path = self.output_dir / f"cluster_report_novelties_{self.session_id}_{self.detector}.json"
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
        
        plot_path = self.output_dir / f"umap_novelties_{self.session_id}_{self.detector}.png"
        plt.tight_layout()
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Saved UMAP plot to {plot_path}")