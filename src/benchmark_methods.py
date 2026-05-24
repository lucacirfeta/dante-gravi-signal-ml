"""Benchmark comparative analysis of clustering methods.

This module provides a comparative benchmark of different clustering approaches
on a labeled reference dataset (e.g., indomain_index.npz), computing ARI and AMI
for each method.
"""

import json
import logging
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score

from src.clustering import run_full_pipeline
from src.utils import setup_logger

logger = setup_logger(__name__)


def run_method_benchmark(
    reference_path: str = "data/reference/indomain_index.npz",
    output_path: str = "data/reference/benchmark_methods.json",
) -> None:
    """Compare clustering methods against ground truth labels.

    Methods evaluated:
    1. DINOv2 + DPMM
    2. DINOv2 + HDBSCAN
    3. PCA(50) + t-SNE(2D) + HDBSCAN

    Args:
        reference_path: Path to the .npz reference dataset.
        output_path: Path where the JSON report will be saved.
    """
    ref_file = Path(reference_path)
    if not ref_file.exists():
        logger.error(f"Reference file not found: {reference_path}")
        return

    data = np.load(ref_file)
    embeddings = data["embeddings"]
    true_labels = data["labels"]

    logger.info("Loaded reference data: %d samples.", embeddings.shape[0])

    results = {}

    # 1. DINOv2 + DPMM
    logger.info("Running DINOv2 + DPMM...")
    cfg_dpmm = {
        "algorithm": "dpmm",
        "pca_components": 50,
        "umap_clustering": {"n_components": 10, "n_neighbors": 30, "min_dist": 0.0},
        "dpmm": {
            "n_components": 25,
            "anomaly_percentile": 5.0,
            "anomaly_threshold": "auto",
        },
    }
    try:
        res_dpmm = run_full_pipeline(embeddings, cfg_dpmm)
        labels_dpmm = res_dpmm["labels"]
        ari_dpmm = adjusted_rand_score(true_labels, labels_dpmm)
        ami_dpmm = adjusted_mutual_info_score(true_labels, labels_dpmm)
        results["DINOv2 + DPMM"] = {"ARI": ari_dpmm, "AMI": ami_dpmm}
    except Exception as e:
        logger.error("Failed DINOv2 + DPMM: %s", e)
        results["DINOv2 + DPMM"] = {"error": str(e)}

    # 2. DINOv2 + HDBSCAN
    logger.info("Running DINOv2 + HDBSCAN...")
    cfg_hdbscan = {
        "algorithm": "hdbscan",
        "pca_components": 50,
        "umap_clustering": {"n_components": 10, "n_neighbors": 30, "min_dist": 0.0},
        "hdbscan": {
            "min_cluster_size": 15,
            "min_samples": 10,
            "cluster_selection_method": "eom",
            "small_cluster_threshold": "auto",
        },
    }
    try:
        res_hdbscan = run_full_pipeline(embeddings, cfg_hdbscan)
        labels_hdbscan = res_hdbscan["labels"]
        ari_hdbscan = adjusted_rand_score(true_labels, labels_hdbscan)
        ami_hdbscan = adjusted_mutual_info_score(true_labels, labels_hdbscan)
        results["DINOv2 + HDBSCAN"] = {"ARI": ari_hdbscan, "AMI": ami_hdbscan}
    except Exception as e:
        logger.error("Failed DINOv2 + HDBSCAN: %s", e)
        results["DINOv2 + HDBSCAN"] = {"error": str(e)}

    # 3. PCA(50) + t-SNE(2D) + HDBSCAN
    logger.info("Running PCA(50) + t-SNE(2D) + HDBSCAN...")
    try:
        pca_50 = PCA(n_components=50, random_state=42).fit_transform(embeddings)
        tsne_2d = TSNE(n_components=2, random_state=42).fit_transform(pca_50)
        labels_tsne = HDBSCAN(min_cluster_size=15, min_samples=10).fit_predict(tsne_2d)

        ari_tsne = adjusted_rand_score(true_labels, labels_tsne)
        ami_tsne = adjusted_mutual_info_score(true_labels, labels_tsne)
        results["PCA(50) + t-SNE(2D) + HDBSCAN"] = {"ARI": ari_tsne, "AMI": ami_tsne}
    except Exception as e:
        logger.error("Failed PCA + t-SNE + HDBSCAN: %s", e)
        results["PCA(50) + t-SNE(2D) + HDBSCAN"] = {"error": str(e)}

    # Save report
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    logger.info("Benchmark report saved to %s", out_file)
    for method, metrics in results.items():
        if "error" in metrics:
            logger.info("%s: ERROR", method)
        else:
            logger.info("%s: ARI=%.4f, AMI=%.4f", method, metrics["ARI"], metrics["AMI"])
