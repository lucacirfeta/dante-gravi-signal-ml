"""DPMM (Dirichlet Process Mixture Model) clustering module.

Provides a probabilistic alternative to HDBSCAN using BayesianGaussianMixture
for novelty detection and clustering on the UMAP latent space.
"""

from __future__ import annotations

import logging

import numpy as np
from sklearn.mixture import BayesianGaussianMixture

from src.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)


def run_dpmm(
        embeddings: np.ndarray,
        n_components: int = 25,
        anomaly_percentile: float = 5.0,
        random_state: int = 42,
        anomaly_threshold: float | None = None,
) -> tuple[np.ndarray, dict, list[int]]:
    """Cluster embeddings using a Dirichlet Process Mixture Model.

    Args:
        embeddings: Input array of shape ``(N, D)`` from UMAP Pass A.
        n_components: Maximum number of clusters (default 25). The DPMM
            will zero out weights for unneeded components.
        anomaly_percentile: The percentile of lowest log-likelihood scores
            to flag as anomalies (default 5.0).  Ignored when
            *anomaly_threshold* is provided.
        random_state: Random seed for reproducibility.
        anomaly_threshold: If a ``float``, use this fixed log-likelihood
            value as the anomaly threshold instead of computing the
            *anomaly_percentile* on the current run.  ``None`` (default)
            preserves the legacy per-run percentile behaviour.

    Returns:
        Tuple of (labels, stats, anomalous_samples):
        - labels: int array of shape ``(N,)``
        - stats: dict with clustering statistics
        - anomalous_samples: list of indices of the most anomalous samples
    """
    logger.info("Initializing DPMM with max %d components...", n_components)

    bgm = BayesianGaussianMixture(
        n_components=n_components,
        weight_concentration_prior_type="dirichlet_process",
        weight_concentration_prior=1.0 / n_components,
        random_state=random_state,
        n_init=5,  # Can be increased for better stability if needed
    )

    labels = bgm.fit_predict(embeddings)

    # Calculate log-likelihood for each sample
    log_likelihoods = bgm.score_samples(embeddings)

    # Identify active clusters (components with non-zero samples assigned)
    unique_labels, counts = np.unique(labels, return_counts=True)
    n_clusters = len(unique_labels)

    cluster_sizes = {int(lbl): int(cnt) for lbl, cnt in zip(unique_labels, counts)}

    stats = {
        "n_clusters": n_clusters,
        "n_noise": 0,  # DPMM doesn't natively classify points as absolute noise
        "noise_ratio": 0.0,
        "cluster_sizes": cluster_sizes,
        "largest_cluster": max(cluster_sizes.values()) if cluster_sizes else 0,
        "smallest_cluster": min(cluster_sizes.values()) if cluster_sizes else 0,
        "algorithm": "dpmm",
    }

    # Identify anomalies based on lowest log-likelihood
    if anomaly_threshold is not None:
        threshold = anomaly_threshold
        logger.info(
            "DPMM: using calibrated anomaly threshold: %.2f", threshold
        )
    else:
        threshold = np.percentile(log_likelihoods, anomaly_percentile)
    anomalous_indices = np.where(log_likelihoods <= threshold)[0]
    anomalous_samples = sorted(anomalous_indices.tolist())

    logger.info(
        "DPMM: %d active clusters found. Flagged %d anomalous samples "
        "(threshold=%.2f%s).",
        n_clusters,
        len(anomalous_samples),
        threshold,
        "" if anomaly_threshold is not None else f", p{anomaly_percentile}",
    )

    return labels, stats, anomalous_samples
