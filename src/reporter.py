"""Cluster reporting and visualization — Phase 3.

Generates structured JSON reports, UMAP scatter plots, and per-cluster
spectrogram contact sheets after the clustering pipeline completes.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from src.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)


# ---------------------------------------------------------------------------
# JSON + PNG + Gallery report
# ---------------------------------------------------------------------------


def save_cluster_report(
    result: dict,
    metadata: dict,
    output_dir: Path,
    detector: str = "H1",
) -> None:
    """Save a full cluster report: JSON, UMAP plot, and spectrogram gallery.

    Creates ``output_dir`` if it doesn't exist and writes:

    - ``cluster_report.json`` — structured pipeline + results report
    - ``umap_visualization.png`` — 2D UMAP scatter colored by cluster
    - ``cluster_gallery/cluster_{id}/`` — contact sheets per cluster

    Args:
        result: Dict returned by :func:`~src.clustering.run_full_pipeline`.
        metadata: Dict loaded from the companion ``.json`` file produced
            by the encoder (contains ``files``, ``model``, etc.).
        output_dir: Directory to write all outputs into.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    labels = result["labels"]
    umap_2d = result["umap_2d"]
    umap_10d = result["umap_10d"]
    stats = result["hdbscan_stats"]
    anomalous = result["anomalous_clusters"]

    # --- A) cluster_report.json ---
    _save_json_report(result, metadata, stats, anomalous, labels, output_dir, detector=detector)

    # --- B) umap_visualization.png ---
    _save_umap_plot(
        umap_2d, labels, stats, anomalous, output_dir, detector=detector
    )

    # --- C) cluster_gallery/ ---
    _save_cluster_gallery(
        labels, umap_10d, stats, anomalous, metadata, output_dir
    )

    logger.info("Cluster report saved to %s", output_dir)


def _save_json_report(
    result: dict,
    metadata: dict,
    stats: dict,
    anomalous: list[int],
    labels: np.ndarray,
    output_dir: Path,
    detector: str = "H1",
) -> None:
    """Write cluster_report.json."""
    files = metadata.get("files", [])

    # Build per-cluster detail
    clusters_detail = {}
    for cid, size in stats["cluster_sizes"].items():
        mask = labels == cid
        sample_files = [files[i] for i in np.where(mask)[0]] if files else []
        clusters_detail[str(cid)] = {
            "size": size,
            "is_anomalous": cid in anomalous,
            "sample_files": sample_files,
        }

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": metadata.get("model", "dinov2_vits14_reg"),
        "n_samples": int(len(labels)),
        "detector": detector,
        "pipeline": {
            "pca_components": 50,
            "pca_variance_explained": result["pca_variance"],
            "umap_clustering": {
                "n_components": 10,
                "n_neighbors": 20,
                "min_dist": 0.0,
            },
            "umap_viz": {
                "n_components": 2,
                "n_neighbors": 20,
                "min_dist": 0.1,
            },
            "hdbscan": {
                "min_cluster_size": 5,
                "min_samples": 3,
            },
        },
        "results": {
            "n_clusters": stats["n_clusters"],
            "n_noise": stats["n_noise"],
            "noise_ratio": stats["noise_ratio"],
            "cluster_sizes": stats["cluster_sizes"],
            "anomalous_clusters": anomalous,
            "clusters": clusters_detail,
        },
    }

    json_path = output_dir / "cluster_report.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)

    logger.info("JSON report saved: %s", json_path)


def _save_umap_plot(
    umap_2d: np.ndarray,
    labels: np.ndarray,
    stats: dict,
    anomalous: list[int],
    output_dir: Path,
    detector: str = "H1",
) -> None:
    """Create and save the 2D UMAP scatter plot."""
    fig, ax = plt.subplots(figsize=(12, 8))
    cmap = plt.cm.tab20

    unique_labels = sorted(set(labels))
    n_clusters = stats["n_clusters"]
    n_noise = stats["n_noise"]

    for label in unique_labels:
        mask = labels == label

        if label == -1:
            # Noise points
            ax.scatter(
                umap_2d[mask, 0],
                umap_2d[mask, 1],
                c="gray",
                s=5,
                alpha=0.4,
                label=f"Noise ({n_noise})",
            )
        else:
            color = cmap(label % 20)
            size_count = stats["cluster_sizes"].get(int(label), 0)

            if label in anomalous:
                # Anomalous clusters get star markers
                ax.scatter(
                    umap_2d[mask, 0],
                    umap_2d[mask, 1],
                    c=[color],
                    s=60,
                    marker="*",
                    edgecolors="black",
                    linewidths=0.5,
                    label=f"* Cluster {label} ({size_count})",
                )
            else:
                ax.scatter(
                    umap_2d[mask, 0],
                    umap_2d[mask, 1],
                    c=[color],
                    s=20,
                    alpha=0.7,
                    label=f"Cluster {label} ({size_count})",
                )

    ax.set_title(
        f"O4a {detector} - DINOv2 Clustering ({n_clusters} clusters, {n_noise} noise)",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_xlabel("UMAP-1")
    ax.set_ylabel("UMAP-2")

    # Place legend outside plot if many clusters
    ax.legend(
        bbox_to_anchor=(1.02, 1),
        loc="upper left",
        fontsize=8,
        framealpha=0.9,
    )

    fig.tight_layout()
    plot_path = output_dir / "umap_visualization.png"
    fig.savefig(plot_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

    logger.info("UMAP visualization saved: %s", plot_path)


def _save_cluster_gallery(
    labels: np.ndarray,
    umap_10d: np.ndarray,
    stats: dict,
    anomalous: list[int],
    metadata: dict,
    output_dir: Path,
) -> None:
    """Create per-cluster gallery folders with contact sheets."""
    files = metadata.get("files", [])
    if not files:
        logger.warning("No file list in metadata — skipping gallery generation.")
        return

    gallery_dir = output_dir / "cluster_gallery"
    gallery_dir.mkdir(parents=True, exist_ok=True)

    for cid in sorted(stats["cluster_sizes"].keys()):
        cluster_dir = gallery_dir / f"cluster_{cid}"
        cluster_dir.mkdir(parents=True, exist_ok=True)

        # Find indices belonging to this cluster
        mask = labels == cid
        indices = np.where(mask)[0]

        # Pick up to 9 closest to centroid in 10D UMAP space
        centroid = umap_10d[indices].mean(axis=0)
        distances = np.linalg.norm(umap_10d[indices] - centroid, axis=1)
        closest_order = np.argsort(distances)
        representative_indices = indices[closest_order[:9]]

        # Copy spectrogram PNGs into cluster folder
        copied_paths = []
        for idx in representative_indices:
            if idx < len(files):
                src_path = Path(files[idx])
                if src_path.exists():
                    dst_path = cluster_dir / src_path.name
                    shutil.copy2(src_path, dst_path)
                    copied_paths.append(dst_path)

        # Generate contact sheet (3×3 grid)
        if copied_paths:
            _make_contact_sheet(
                copied_paths,
                cluster_dir,
                cid,
                stats["cluster_sizes"][cid],
                is_anomalous=(cid in anomalous),
            )


def _make_contact_sheet(
    image_paths: list[Path],
    cluster_dir: Path,
    cluster_id: int,
    cluster_size: int,
    is_anomalous: bool,
) -> None:
    """Create a 3×3 contact sheet from representative spectrograms."""
    n_images = len(image_paths)
    cols = 3
    rows = 3

    fig, axes = plt.subplots(rows, cols, figsize=(9, 9))

    # Title
    if is_anomalous:
        title = f"* ANOMALOUS - Cluster {cluster_id} - {cluster_size} samples"
    else:
        title = f"Cluster {cluster_id} - {cluster_size} samples"
    fig.suptitle(title, fontsize=14, fontweight="bold")

    for idx in range(rows * cols):
        row, col = divmod(idx, cols)
        ax = axes[row][col]
        ax.axis("off")

        if idx < n_images:
            try:
                img = Image.open(image_paths[idx])
                ax.imshow(np.array(img), cmap="viridis")
            except Exception:
                ax.text(0.5, 0.5, "Error", ha="center", va="center")
        # Empty cells are left blank (axis is off)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    sheet_path = cluster_dir / "contact_sheet.png"
    fig.savefig(sheet_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Human-readable console summary
# ---------------------------------------------------------------------------


def print_summary(result: dict) -> None:
    """Print a human-readable clustering summary to the console.

    Args:
        result: Dict returned by :func:`~src.clustering.run_full_pipeline`.
    """
    stats = result["hdbscan_stats"]
    anomalous = result["anomalous_clusters"]
    labels = result["labels"]

    print("\n" + "=" * 60)
    print("  CLUSTERING SUMMARY")
    print("=" * 60)
    print(f"  Total samples:    {len(labels)}")
    print(f"  Clusters found:   {stats['n_clusters']}")
    print(f"  Noise points:     {stats['n_noise']} ({stats['noise_ratio']:.1%})")
    print(f"  PCA variance:     {result['pca_variance']:.1%}")
    print("-" * 60)
    print(f"  {'ID':>4}  {'Size':>6}  {'Status'}")
    print(f"  {'-' * 4}  {'-' * 6}  {'-' * 20}")

    for cid, size in sorted(stats["cluster_sizes"].items()):
        flag = "  * ANOMALOUS" if cid in anomalous else ""
        print(f"  {cid:>4}  {size:>6}{flag}")

    if anomalous:
        print("-" * 60)
        print(f"  *  Anomalous clusters (novel candidates): {anomalous}")

    print("=" * 60 + "\n")
