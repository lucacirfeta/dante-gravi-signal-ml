"""Unsupervised clustering pipeline — Phase 3 scaffold.

This module will implement UMAP dimensionality reduction followed by
HDBSCAN density-based clustering on the embedding vectors produced by
the :mod:`src.encoder` module.  The goal is to discover novel glitch
classes in O4a data that are not yet catalogued by Gravity Spy.

Pipeline:
    1. Load 128-dim embeddings from ``data/embeddings/``
    2. Reduce to 2-D via UMAP (for visualization and clustering)
    3. Cluster with HDBSCAN (no need to pre-specify *k*)
    4. Report candidate novel classes with representative spectrograms

NOTE: This is a Phase 3 scaffold.  Functions have full signatures and
docstrings but raise ``NotImplementedError`` until Phase 3.
"""

from __future__ import annotations

import logging

import numpy as np

from src.utils import load_config, setup_logger

logger: logging.Logger = setup_logger(__name__)

_CFG = load_config()
_CLUSTER_CFG = _CFG["clustering"]


def run_umap(
    embeddings: np.ndarray,
    n_components: int = _CLUSTER_CFG["umap_components"],
    n_neighbors: int = _CLUSTER_CFG["umap_n_neighbors"],
    min_dist: float = _CLUSTER_CFG["umap_min_dist"],
) -> np.ndarray:
    """Reduce high-dimensional embeddings to a low-dimensional manifold.

    Uses Uniform Manifold Approximation and Projection (UMAP) to produce
    a 2-D representation suitable for visualization and downstream
    density-based clustering.

    Args:
        embeddings: Input array of shape ``(N, D)`` where *D* is the
            embedding dimensionality (typically 128).
        n_components: Number of output dimensions (default 2).
        n_neighbors: Size of the local neighborhood for UMAP
            (default 15).
        min_dist: Minimum distance between points in the output space
            (default 0.1).

    Returns:
        Array of shape ``(N, n_components)`` with the reduced coordinates.

    Raises:
        NotImplementedError: Always — implementation deferred to Phase 3.
    """
    logger.info(
        "UMAP: %s -> %d-D (n_neighbors=%d, min_dist=%.2f) [NOT IMPLEMENTED]",
        embeddings.shape,
        n_components,
        n_neighbors,
        min_dist,
    )
    raise NotImplementedError(
        "UMAP dimensionality reduction is not yet implemented — Phase 3."
    )


def run_hdbscan(
    umap_coords: np.ndarray,
    min_cluster_size: int = _CLUSTER_CFG["hdbscan_min_cluster_size"],
    min_samples: int = _CLUSTER_CFG["hdbscan_min_samples"],
) -> np.ndarray:
    """Cluster UMAP-reduced embeddings using HDBSCAN.

    HDBSCAN is a density-based clustering algorithm that does not require
    pre-specifying the number of clusters.  Points that do not belong to
    any dense region are labeled as noise (``-1``), making it ideal for
    discovering previously unknown glitch morphologies.

    Args:
        umap_coords: Input array of shape ``(N, 2)`` from :func:`run_umap`.
        min_cluster_size: Minimum number of points to form a cluster
            (default 30).
        min_samples: Number of samples in a neighborhood for a point to
            be considered a core point (default 10).

    Returns:
        Integer array of shape ``(N,)`` with cluster labels.  Label
        ``-1`` indicates noise / unclustered points.

    Raises:
        NotImplementedError: Always — implementation deferred to Phase 3.
    """
    logger.info(
        "HDBSCAN: %d points, min_cluster_size=%d, min_samples=%d [NOT IMPLEMENTED]",
        len(umap_coords),
        min_cluster_size,
        min_samples,
    )
    raise NotImplementedError(
        "HDBSCAN clustering is not yet implemented — Phase 3."
    )
