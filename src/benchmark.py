"""Benchmark the unsupervised clustering pipeline against Ground Truth labels.

This module loads the in-domain reference index (which contains DINOv2 embeddings
and Gravity Spy Ground Truth labels) and runs the unsupervised clustering pipeline
on it. It then calculates cluster-alignment metrics (Adjusted Rand Index and 
Adjusted Mutual Information) to quantify the pipeline's ability to recover
known glitch morphologies without supervision.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score

from src.clustering import run_full_pipeline
from src.utils import load_config, setup_logger

logger: logging.Logger = setup_logger(__name__)


def run_benchmark(
        reference_path: str | Path = "data/reference/indomain_index.npz",
        min_samples_per_class: int = 10,
        output_path: str | Path | None = "data/reference/benchmark_report.json",
        algorithm: str = "hdbscan",
) -> dict:
    """Run benchmark of clustering pipeline using Ground Truth labels.

    Args:
        reference_path: Path to the .npz reference index.
        min_samples_per_class: Exclude classes with fewer than this many samples.
        output_path: Path to save the JSON report. If None, it will not save.
        
    Returns:
        Dictionary containing benchmark metrics and contingency matrix.
    """
    ref_path = Path(reference_path)
    if not ref_path.exists():
        raise FileNotFoundError(f"Reference index not found: {ref_path}")

    logger.info("Loading reference index from %s", ref_path)
    data = np.load(ref_path)
    embeddings = data["embeddings"]
    labels = data["labels"]

    # Filter out classes with too few samples
    unique_labels, counts = np.unique(labels, return_counts=True)
    valid_classes = unique_labels[counts >= min_samples_per_class]

    logger.info(
        "Filtering classes with >= %d samples (kept %d/%d classes)",
        min_samples_per_class, len(valid_classes), len(unique_labels)
    )

    mask = np.isin(labels, valid_classes)
    filtered_embeddings = embeddings[mask]
    filtered_labels = labels[mask]

    n_samples = len(filtered_labels)
    logger.info("Proceeding with %d samples after filtering.", n_samples)

    if n_samples == 0:
        raise ValueError("No samples left after filtering.")

    # Run clustering pipeline
    logger.info("Running unsupervised clustering pipeline...")
    cfg = load_config()
    clustering_cfg = cfg.get("clustering", {})
    clustering_cfg["algorithm"] = algorithm

    results = run_full_pipeline(filtered_embeddings, clustering_cfg)
    pred_labels = results["labels"]

    # Calculate metrics
    # Note: HDBSCAN labels noise points as -1. We exclude them from ARI/AMI
    # calculations because noise points do not form a coherent semantic cluster.
    # DPMM does not use -1, so valid_mask will be all True for DPMM.
    if algorithm == "hdbscan":
        valid_mask = pred_labels != -1
    else:
        valid_mask = np.ones(len(pred_labels), dtype=bool)

    clean_true_labels = filtered_labels[valid_mask]
    clean_pred_labels = pred_labels[valid_mask]

    n_noise = int(np.sum(~valid_mask))
    noise_ratio = n_noise / n_samples if n_samples > 0 else 0.0

    if n_noise > 0:
        logger.info(
            "Excluding %d noise points (%.1f%%) for metric calculations.",
            n_noise, noise_ratio * 100
        )

    if len(clean_true_labels) > 0:
        ari = float(adjusted_rand_score(clean_true_labels, clean_pred_labels))
        ami = float(adjusted_mutual_info_score(clean_true_labels, clean_pred_labels))
    else:
        logger.warning("No points were clustered (all noise). Metrics are undefined.")
        ari = 0.0
        ami = 0.0

    # Generate contingency matrix
    # We use pandas crosstab for a nice DataFrame representation
    # Include noise points (-1) in the contingency matrix for completeness
    crosstab_df = pd.crosstab(
        pd.Series(filtered_labels, name="True Class"),
        pd.Series(pred_labels, name="Predicted Cluster")
    )

    # Convert column names to int/str for JSON serialization
    crosstab_df.columns = [str(c) for c in crosstab_df.columns]
    contingency_dict = crosstab_df.to_dict(orient="index")

    report = {
        "metrics": {
            "adjusted_rand_index": ari,
            "adjusted_mutual_info": ami,
        },
        "clustering_stats": {
            "total_samples": int(n_samples),
            "clustered_samples": int(np.sum(valid_mask)),
            "noise_samples": n_noise,
            "noise_ratio": float(noise_ratio),
            "n_clusters_found": len(np.unique(clean_pred_labels)) if len(clean_pred_labels) > 0 else 0,
            "n_true_classes": len(valid_classes),
        },
        "contingency_matrix": contingency_dict,
        "config": {
            "min_samples_per_class": min_samples_per_class,
            "reference_file": str(ref_path),
        }
    }

    # Save report
    if output_path:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4)
        logger.info("Benchmark report saved to %s", out_path)

    # Print formatted summary to terminal
    print("\n" + "=" * 60)
    print(" CLUSTERING BENCHMARK RESULTS".center(60))
    print("=" * 60)
    print(f" Reference Data : {ref_path.name}")
    print(f" Algorithm      : {algorithm.upper()}")
    print(f" True Classes   : {report['clustering_stats']['n_true_classes']}")
    print(f" Clusters Found : {report['clustering_stats']['n_clusters_found']}")
    print(f" Total Samples  : {n_samples}")
    if algorithm == "hdbscan":
        print(f" Noise Points   : {n_noise} ({noise_ratio * 100:.1f}%)")
    print("-" * 60)
    print(f" Adjusted Rand Index (ARI)       : {ari:.4f}")
    print(f" Adjusted Mutual Info (AMI)      : {ami:.4f}")
    print("=" * 60 + "\n")
    print("Note: Noise points (HDBSCAN label -1) were excluded from ARI/AMI calculation.")
    if output_path:
        print(f"A detailed contingency matrix has been saved to {output_path}")

    return report
