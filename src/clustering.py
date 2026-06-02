"""Unsupervised clustering pipeline — Phase 3.

Implements PCA → UMAP → HDBSCAN/DPMM for discovering novel glitch classes in
O4a gravitational-wave data.

Pipeline:
    1. PCA(50) — reduce 384-dim DINOv2 embeddings to 50 principal components
    2. UMAP (Pass A) — 50D → 10D clustering-optimized (min_dist=0.0, cosine)
    3. Clustering — HDBSCAN (density-based) or DPMM (probabilistic)
    4. Anomaly identification:
       - HDBSCAN: flag small clusters (≤ threshold) as novel candidates
       - DPMM: compute per-sample log-likelihood; clusters where >50%
         of members fall below the 5th percentile are anomalous
    5. UMAP (Pass B) — 50D → 2D visualization-only (min_dist=0.1, cosine)

Two UMAP passes are required because min_dist=0.0 packs points tightly
for optimal density detection, but produces poor visualizations.
Pass B with min_dist=0.1 generates a readable 2D scatter plot.
"""

from __future__ import annotations

import logging

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.decomposition import PCA

from src.dpmm_clustering import run_dpmm
import torch
from src.utils import get_device, setup_logger

logger: logging.Logger = setup_logger(__name__)


def _gpu_l2_normalize(embeddings: np.ndarray) -> np.ndarray:
    """L2-normalize embeddings on GPU when available, else NumPy fallback.

    Args:
        embeddings: Array of shape ``(N, D)``.

    Returns:
        L2-normalized array of the same shape (float32).
    """
    device = get_device(verbose=False)
    if device.type in ("cuda", "mps"):
        with torch.no_grad():
            t = torch.from_numpy(embeddings).to(device).float()
            t = torch.nn.functional.normalize(t, p=2, dim=1)
            result = t.cpu().numpy()
        logger.info("L2 normalization executed on %s", device)
        return result
    # CPU fallback
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (embeddings / norms).astype(np.float32)


# ---------------------------------------------------------------------------
# PCA
# ---------------------------------------------------------------------------


def run_pca(
        embeddings: np.ndarray,
        n_components: int = 50,
        random_state: int = 42,
) -> tuple[np.ndarray, float]:
    """Reduce embedding dimensionality via Principal Component Analysis.

    Args:
        embeddings: Input array of shape ``(N, D)`` — typically (344, 384).
        n_components: Number of principal components to keep (default 50).
        random_state: Random seed for reproducibility.

    Returns:
        Tuple of (reduced_embeddings, explained_variance_ratio_sum):
        - reduced_embeddings: array of shape ``(N, n_components)``
        - explained_variance_ratio_sum: cumulative variance explained (0–1)
    """
    in_dim = embeddings.shape[1]
    pca = PCA(n_components=n_components, random_state=random_state)
    reduced = pca.fit_transform(embeddings)
    variance_sum = float(np.sum(pca.explained_variance_ratio_))

    logger.info(
        "PCA: %dD → %dD | variance explained: %.1f%%",
        in_dim,
        n_components,
        variance_sum * 100,
    )
    return reduced, variance_sum


# ---------------------------------------------------------------------------
# UMAP
# ---------------------------------------------------------------------------


def run_umap(
        embeddings: np.ndarray,
        n_components: int = 10,
        n_neighbors: int = 30,
        min_dist: float = 0.0,
        random_state: int = 42,
) -> np.ndarray:
    """Reduce dimensionality via Uniform Manifold Approximation and Projection.

    Args:
        embeddings: Input array of shape ``(N, D)``.
        n_components: Output dimensionality (10 for clustering, 2 for viz).
        n_neighbors: Size of the local neighborhood (default 30).
        min_dist: Minimum distance between output points (default 0.0).
        random_state: Random seed for reproducibility.

    Returns:
        Array of shape ``(N, n_components)`` with the reduced coordinates.
    """
    import umap

    in_dim = embeddings.shape[1]
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric="cosine",  # Enforce cosine for pre-normalized DINOv2 embeddings
        random_state=random_state,
    )
    reduced = reducer.fit_transform(embeddings)

    logger.info(
        "UMAP: %dD → %dD | neighbors=%d",
        in_dim,
        n_components,
        n_neighbors,
    )
    return reduced


# ---------------------------------------------------------------------------
# HDBSCAN
# ---------------------------------------------------------------------------


def run_hdbscan(
        embeddings: np.ndarray,
        min_cluster_size: int = 15,
        min_samples: int = 10,
        cluster_selection_method: str = "eom",
) -> tuple[np.ndarray, dict]:
    """Cluster embeddings using HDBSCAN (sklearn implementation).

    Uses ``sklearn.cluster.HDBSCAN`` (scikit-learn ≥ 1.3) — NOT the
    standalone ``hdbscan`` pip package.

    Args:
        embeddings: Input array of shape ``(N, D)`` from UMAP Pass A.
        min_cluster_size: Minimum points to form a cluster (default 15).
        min_samples: Core point neighborhood size (default 10).
        cluster_selection_method: Cluster extraction method — ``'eom'``
            (Excess of Mass) or ``'leaf'`` (default ``'eom'``).

    Returns:
        Tuple of (labels, stats):
        - labels: int array of shape ``(N,)``, where ``-1`` = noise
        - stats: dict with clustering statistics
    """
    clusterer = HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        cluster_selection_method=cluster_selection_method,
        metric="euclidean",
    )
    labels = clusterer.fit_predict(embeddings)

    unique_labels = set(labels)
    unique_labels.discard(-1)
    n_clusters = len(unique_labels)
    n_noise = int(np.sum(labels == -1))
    total = len(labels)
    noise_ratio = n_noise / total if total > 0 else 0.0

    cluster_sizes = {}
    for cid in sorted(unique_labels):
        cluster_sizes[int(cid)] = int(np.sum(labels == cid))

    stats = {
        "n_clusters": n_clusters,
        "n_noise": n_noise,
        "noise_ratio": noise_ratio,
        "cluster_sizes": cluster_sizes,
        "largest_cluster": max(cluster_sizes.values()) if cluster_sizes else 0,
        "smallest_cluster": min(cluster_sizes.values()) if cluster_sizes else 0,
    }

    logger.info(
        "HDBSCAN: %d clusters | %d noise pts (%.1f%%)",
        n_clusters,
        n_noise,
        noise_ratio * 100,
    )
    return labels, stats


# ---------------------------------------------------------------------------
# Anomaly identification
# ---------------------------------------------------------------------------


def identify_anomalous_clusters(
        labels: np.ndarray,
        stats: dict,
        small_cluster_threshold: int = 10,
) -> list[int]:
    """Identify anomalous (small) clusters as novel glitch candidates.

    Clusters with size ≤ ``small_cluster_threshold`` are flagged as
    potential novel / unknown glitch classes worth investigating.

    Args:
        labels: HDBSCAN cluster labels — unused but kept for API symmetry.
        stats: Statistics dict from :func:`run_hdbscan`.
        small_cluster_threshold: Maximum size for a cluster to be
            considered anomalous (default 10).

    Returns:
        Sorted list of anomalous cluster IDs.
    """
    anomalous = [
        cid
        for cid, size in stats["cluster_sizes"].items()
        if size <= small_cluster_threshold
    ]
    anomalous.sort()

    if anomalous:
        sizes = [stats["cluster_sizes"][cid] for cid in anomalous]
        logger.info(
            "Anomalous cluster candidates: %s (%s pts each)",
            anomalous,
            sizes,
        )
    else:
        logger.info("No anomalous clusters found (threshold=%d)", small_cluster_threshold)

    return anomalous


# ---------------------------------------------------------------------------
# Full pipeline orchestrator
# ---------------------------------------------------------------------------


def run_full_pipeline(
        embeddings: np.ndarray,
        config: dict,

        logger: logging.Logger | logging.LoggerAdapter | None = None, ) -> dict:
    """Orchestrate the full clustering pipeline.

    Sequence: PCA → UMAP(clustering) → HDBSCAN → anomaly ID → UMAP(viz)

    Args:
        embeddings: Raw embeddings of shape ``(N, 384)``.
        config: Clustering config dict from ``config.yaml['clustering']``.

    Returns:
        Result dict with keys:
        - ``labels``: HDBSCAN cluster labels per sample
        - ``umap_2d``: 2D coordinates for visualization
        - ``umap_10d``: 10D clustering space
        - ``pca_variance``: explained variance ratio from PCA
        - ``hdbscan_stats``: statistics dict from HDBSCAN
        - ``anomalous_clusters``: list of anomalous cluster IDs
    """

    logger = logger or logging.getLogger(__name__)
    # --- Step 0: Ensure L2-normalized embeddings (GPU-accelerated) ---
    embeddings = _gpu_l2_normalize(embeddings)

    # Read global random seed — single source of truth from config
    random_state: int = int(config.get("random_state", 42))

    # --- Step 1: PCA ---
    pca_reduced, pca_variance = run_pca(
        embeddings,
        n_components=config.get("pca_components", 50),
        random_state=random_state,
    )

    # --- Step 2: UMAP Pass A — clustering (10D, min_dist=0.0) ---
    umap_clust_cfg = config.get("umap_clustering", {})
    umap_10d = run_umap(
        pca_reduced,
        n_components=umap_clust_cfg.get("n_components", 10),
        n_neighbors=umap_clust_cfg.get("n_neighbors", 30),
        min_dist=umap_clust_cfg.get("min_dist", 0.0),
        random_state=random_state,
    )

    algorithm = config.get("algorithm", "dpmm")

    if algorithm == "dpmm":
        # --- Step 3: DPMM ---
        dpmm_cfg = config.get("dpmm", {})

        # Resolve anomaly threshold: 'auto' or missing → auto-calibrate if possible
        raw_at = dpmm_cfg.get("anomaly_threshold", "auto")
        if raw_at == "auto":
            logger.warning("DPMM anomaly_threshold non disponibile (impostato su 'auto').")
            logger.warning("Avvio calibrazione automatica dal riferimento in-domain...")
            try:
                from src.loglikelihood_calibrator import calibrate_loglikelihood_threshold
                calib_res = calibrate_loglikelihood_threshold()
                dpmm_anomaly_threshold: float | None = calib_res["threshold"]
            except Exception as e:
                logger.error("Calibrazione fallita: %s. Fallback su soglia 'auto' (percentile on run).", e)
                dpmm_anomaly_threshold = None
        else:
            dpmm_anomaly_threshold = float(raw_at)

        labels, cluster_stats, anomalous_samples = run_dpmm(
            umap_10d,
            n_components=dpmm_cfg.get("n_components", 25),
            anomaly_percentile=dpmm_cfg.get("anomaly_percentile", 5.0),
            anomaly_threshold=dpmm_anomaly_threshold,
            random_state=random_state,
        )

        # --- Step 4: Aggregate per-sample anomalies to cluster level ---
        # A cluster is anomalous if >50% of its members have log-likelihood
        # below the 5th percentile (matching the criterion in stability.py).
        anomalous_set = set(anomalous_samples)
        anomalous_clusters = []
        for cid in sorted(cluster_stats["cluster_sizes"].keys()):
            members = np.where(labels == cid)[0]
            if len(members) == 0:
                continue
            below_thresh = sum(1 for m in members if m in anomalous_set)
            if below_thresh / len(members) > 0.5:
                anomalous_clusters.append(int(cid))

        if anomalous_clusters:
            logger.info(
                "DPMM anomalous clusters (>50%% low-likelihood members): %s",
                anomalous_clusters,
            )
    else:
        # --- Step 3: HDBSCAN ---
        hdbscan_cfg = config.get("hdbscan", {})
        n = len(embeddings)

        min_cluster_size = hdbscan_cfg.get("min_cluster_size", 15)

        raw_anomaly = hdbscan_cfg.get("small_cluster_threshold", "auto")
        small_cluster_threshold = (
            max(10, int(n * 0.01))
            if raw_anomaly == "auto"
            else raw_anomaly
        )

        logger.info(
            f"HDBSCAN params (N={n}): "
            f"min_cluster_size={min_cluster_size}, "
            f"small_cluster_threshold={small_cluster_threshold}"
        )

        labels, cluster_stats = run_hdbscan(
            umap_10d,
            min_cluster_size=min_cluster_size,
            min_samples=hdbscan_cfg.get("min_samples", 10),
            cluster_selection_method=hdbscan_cfg.get("cluster_selection_method", "eom"),
        )

        # --- Step 4: Identify anomalous clusters ---
        anomalous_clusters = identify_anomalous_clusters(
            labels,
            cluster_stats,
            small_cluster_threshold=small_cluster_threshold,
        )
        anomalous_samples = []

    # --- Step 5: UMAP Pass B — visualization (2D, min_dist=0.1) ---
    umap_viz_cfg = config.get("umap_viz", {})
    umap_2d = run_umap(
        pca_reduced,
        n_components=umap_viz_cfg.get("n_components", 2),
        n_neighbors=umap_viz_cfg.get("n_neighbors", 30),
        min_dist=umap_viz_cfg.get("min_dist", 0.1),
        random_state=random_state,
    )

    # --- Step 6: Clustering Quality Metrics ---
    from sklearn.metrics import davies_bouldin_score, silhouette_score

    valid_mask = labels != -1
    valid_labels = labels[valid_mask]

    if len(set(valid_labels)) > 1:
        sil_umap = float(silhouette_score(umap_10d[valid_mask], valid_labels))
        db_umap = float(davies_bouldin_score(umap_10d[valid_mask], valid_labels))
        sil_pca = float(silhouette_score(pca_reduced[valid_mask], valid_labels))
        db_pca = float(davies_bouldin_score(pca_reduced[valid_mask], valid_labels))
    else:
        sil_umap, db_umap, sil_pca, db_pca = None, None, None, None

    return {
        "labels": labels,
        "umap_2d": umap_2d,
        "umap_10d": umap_10d,
        "pca_variance": pca_variance,
        "hdbscan_stats": cluster_stats,
        "cluster_stats": cluster_stats,  # alias for agnostic reporting
        "anomalous_clusters": anomalous_clusters,
        "anomalous_samples": anomalous_samples,
        "silhouette_umap": sil_umap,
        "silhouette_pca": sil_pca,
        "davies_bouldin_umap": db_umap,
        "davies_bouldin_pca": db_pca,
    }
