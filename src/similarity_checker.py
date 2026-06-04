"""Morphological similarity checker using cosine KNN search
against the Gravity Spy training set reference index."""

from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from src.utils import setup_logger

logger = setup_logger(__name__)


def cosine_knn_search(
        query_embeddings: np.ndarray,
        reference_embeddings: np.ndarray,
        reference_labels: np.ndarray,
        k: int = 5,
        device: torch.device | None = None,
) -> list[dict]:
    """Perform KNN search using cosine similarity (GPU-accelerated).

    Uses PyTorch tensor algebra on the best available device for the
    matrix multiplication and top-K extraction.  Embeddings are assumed
    to be L2-normalized so that ``dot(q, r) == cosine_similarity(q, r)``.

    Args:
        query_embeddings: Query array of shape ``(Q, D)``.
        reference_embeddings: Reference array of shape ``(R, D)``.
        reference_labels: Label array of shape ``(R,)``.
        k: Number of nearest neighbours to retrieve.
        device: Compute device override.  Defaults to auto-detection.

    Returns:
        List of dicts, one per query, with keys ``query_idx``,
        ``neighbors``, ``top_label``, ``top_similarity``,
        ``label_distribution``.
    """
    from src.utils import get_device

    if device is None:
        device = get_device(verbose=False)

    # Transfer to accelerator in FP32
    q_tensor = torch.from_numpy(query_embeddings).to(device).float()
    r_tensor = torch.from_numpy(reference_embeddings).to(device).float()

    with torch.no_grad():
        # Cosine similarity via dot product on L2-normalised vectors
        similarity_matrix = torch.mm(q_tensor, r_tensor.T)

        # Top-K extraction on device
        topk_values, topk_indices = torch.topk(
            similarity_matrix, k=min(k, r_tensor.shape[0]), dim=1
        )

        # Move to host only for final result construction
        sim_values = topk_values.cpu().numpy()
        idx_nearest = topk_indices.cpu().numpy()

    results = []
    for i in range(len(query_embeddings)):
        neighbors = []
        labels_in_top_k = []
        for rank_idx in range(sim_values.shape[1]):
            label = str(reference_labels[idx_nearest[i, rank_idx]])
            sim = float(sim_values[i, rank_idx])
            neighbors.append(
                {"label": label, "similarity": sim, "rank": rank_idx + 1}
            )
            labels_in_top_k.append(label)

        label_distribution = dict(Counter(labels_in_top_k))
        top_label = max(label_distribution.items(), key=lambda x: x[1])[0]
        top_similarity = neighbors[0]["similarity"]

        results.append({
            "query_idx": i,
            "neighbors": neighbors,
            "top_label": top_label,
            "top_similarity": top_similarity,
            "label_distribution": label_distribution,
        })

    return results


def assess_novelty(
        knn_results: list[dict],
        novelty_threshold: float = 0.85,
        consensus_threshold: float = 0.6,
) -> list[dict]:
    """Assess novelty status based on KNN results using a fixed global threshold.

    .. note::
        This method uses a static threshold and is maintained for backward
        compatibility and reproducibility of published results. For new
        experiments, prefer :func:`assess_novelty_dynamic` which adapts to
        the session-local noise floor of each detector run.

    Args:
        knn_results: Output from :func:`cosine_knn_search`.
        novelty_threshold: Cosine similarity below which a segment is NOVEL.
        consensus_threshold: Label agreement fraction above which a segment
            is KNOWN (vs AMBIGUOUS).

    Returns:
        Enriched list of dicts with ``novelty_status`` key added.
    """
    enriched_results = []
    for r in knn_results:
        result = r.copy()
        top_sim = result["top_similarity"]
        top_label = result["top_label"]
        total_k = sum(result["label_distribution"].values())
        agreement = result["label_distribution"][top_label] / total_k

        if top_sim < novelty_threshold:
            status = "NOVEL"
        elif agreement >= consensus_threshold:
            status = "KNOWN"
        else:
            status = "AMBIGUOUS"

        result["novelty_status"] = status
        enriched_results.append(result)

    return enriched_results


def compute_baseline_stats(
        null_similarities: list[float] | np.ndarray,
) -> dict:
    """Compute session-local baseline statistics from null (no-glitch) segments.

    The DINOv2 embedding space for whitened LIGO strain is empirically very
    stable: across 30 consecutive L1 noise segments, we measured
    ``mean=0.940, std=0.021`` for the top-1 cosine similarity against the
    in-domain reference index.  This function formalises the measurement so
    that :func:`assess_novelty_dynamic` can adapt to any detector/run.

    Args:
        null_similarities: Array of max cosine similarities from NULL
            (no-injection) segments processed with the same pipeline.
            Minimum recommended: 20 samples.

    Returns:
        Dict with keys ``mean``, ``std``, ``n_samples``,
        ``min``, ``max``, ``p5``, ``p95``.
    """
    arr = np.asarray(null_similarities, dtype=float)
    if len(arr) < 5:
        raise ValueError(
            f"Need at least 5 null samples for a stable baseline (got {len(arr)})."
        )
    return {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "n_samples": int(len(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p5": float(np.percentile(arr, 5)),
        "p95": float(np.percentile(arr, 95)),
    }


def assess_novelty_dynamic(
        knn_results: list[dict],
        baseline_stats: dict,
        k_sigma: float = 2.5,
        consensus_threshold: float = 0.6,
) -> list[dict]:
    """Assess novelty using a session-adaptive, sigma-based threshold.

    Instead of comparing ``top_similarity`` against a hard global threshold,
    this method computes a **novelty score** relative to the session-local
    noise floor::

        novelty_score = baseline_mean - top_similarity

    A segment is classified as **NOVEL** if::

        novelty_score > k_sigma * baseline_std

    This is equivalent to saying the similarity dropped more than
    ``k_sigma`` standard deviations below the expected noise baseline.

    **Physical motivation:** Whitened LIGO strain produces highly stable
    DINOv2 embeddings (measured ``std ≈ 0.021`` on L1 O4a data).  A
    correctly-injected broadband glitch at SNR > 50 causes a drop of
    ~0.06–0.08 in cosine similarity, which corresponds to ~3 sigma.  A
    static threshold of 0.85 misses all these events because the noise
    floor itself sits at ~0.94.  The dynamic approach correctly identifies
    them at k=2.5 with a false-alarm rate < 1% (assuming Gaussian noise).

    Args:
        knn_results: Output from :func:`cosine_knn_search`.
        baseline_stats: Dict returned by :func:`compute_baseline_stats`,
            must contain ``mean`` and ``std``.
        k_sigma: Number of sigma below the baseline required for NOVEL
            classification.  Default 2.5 gives a theoretical FAR of ~0.6%
            under Gaussian assumptions.
        consensus_threshold: Label agreement fraction above which a
            non-novel segment is classified as KNOWN vs AMBIGUOUS.

    Returns:
        Enriched list of dicts with keys ``novelty_status``,
        ``novelty_score``, ``novelty_sigma`` added to each result.
    """
    baseline_mean = baseline_stats["mean"]
    baseline_std = baseline_stats["std"]

    if baseline_std <= 0:
        logger.warning(
            "Baseline std is zero — falling back to assess_novelty() with "
            "static threshold derived from baseline_mean - k_sigma * 0.021."
        )
        baseline_std = 0.021  # empirical fallback from L1 O4a measurements

    dynamic_threshold = baseline_mean - k_sigma * baseline_std
    logger.info(
        "Dynamic threshold: NOVEL if sim < %.4f  (baseline_mean=%.4f, std=%.4f, k=%.1f)",
        dynamic_threshold, baseline_mean, baseline_std, k_sigma,
    )

    enriched_results = []
    for r in knn_results:
        result = r.copy()
        top_sim = result["top_similarity"]
        top_label = result["top_label"]
        total_k = sum(result["label_distribution"].values())
        agreement = result["label_distribution"][top_label] / total_k

        novelty_score = baseline_mean - top_sim
        novelty_sigma = novelty_score / baseline_std

        if novelty_score > k_sigma * baseline_std:
            status = "NOVEL"
        elif agreement >= consensus_threshold:
            status = "KNOWN"
        else:
            status = "AMBIGUOUS"

        result["novelty_status"] = status
        result["novelty_score"] = float(novelty_score)
        result["novelty_sigma"] = float(novelty_sigma)
        result["dynamic_threshold"] = float(dynamic_threshold)
        enriched_results.append(result)

    return enriched_results


def run_morphological_crosscheck(
        anomalous_embeddings: np.ndarray,
        anomalous_files: list[str],
        anomalous_cluster_ids: list[int],
        reference_index_path: Path,
        output_path: Path,
        k: int = 5,
        novelty_threshold: float = 0.85,
        consensus_threshold: float = 0.6,

        logger: logging.Logger | logging.LoggerAdapter | None = None, ) -> dict:
    """Orchestrate full morphological crosscheck."""

    logger = logger or logging.getLogger(__name__)
    from src.reference_builder import load_reference_index

    ref_embeddings, ref_labels = load_reference_index(reference_index_path)

    logger.info("Running cosine KNN search for %d queries against %d references",
                len(anomalous_embeddings), len(ref_embeddings))

    knn_results = cosine_knn_search(anomalous_embeddings, ref_embeddings, ref_labels, k=k)
    enriched_results = assess_novelty(
        knn_results,
        novelty_threshold=novelty_threshold,
        consensus_threshold=consensus_threshold
    )

    novel_count = 0
    known_count = 0
    ambiguous_count = 0
    novel_files = []
    details = []

    for i, r in enumerate(enriched_results):
        status = r["novelty_status"]
        if status == "NOVEL":
            novel_count += 1
            novel_files.append(anomalous_files[i])
        elif status == "KNOWN":
            known_count += 1
        else:
            ambiguous_count += 1

        details.append({
            "file": anomalous_files[i],
            "cluster_id": anomalous_cluster_ids[i],
            "novelty_status": status,
            "top_label": r["top_label"],
            "top_similarity": r["top_similarity"],
            "label_distribution": r["label_distribution"],
            "neighbors": r["neighbors"],
        })

    summary = {
        "total_checked": len(enriched_results),
        "novel": novel_count,
        "known": known_count,
        "ambiguous": ambiguous_count,
        "novel_files": novel_files,
        "details": details,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    return summary


def print_morphological_summary(summary: dict, detector: str | None = None) -> None:
    """Print human-readable table of crosscheck results."""
    det_colors = {
        "H1": "\033[96m",  # Cyan
        "L1": "\033[92m",  # Green
        "V1": "\033[95m",  # Magenta
    }
    color = det_colors.get(str(detector).upper(), "")
    reset = "\033[0m" if color else ""

    det_str = f" ({detector})" if detector else ""
    print(f"\n{color}{'=' * 80}")
    print(f"{'MORPHOLOGICAL CROSSCHECK SUMMARY' + det_str:^80}")
    print(f"{'=' * 80}{reset}")

    header = f"{'File':<30} {'Cluster':<8} {'Status':<12} {'Nearest Class':<20} {'Sim':<5}"
    print(header)
    print("-" * 80)

    for d in summary["details"]:
        file_base = Path(d['file']).name[:28]
        status = d['novelty_status']

        # ANSI colors
        color_start = ""
        color_end = ""
        if status == "NOVEL":
            color_start = "\033[91m"  # Red
            color_end = "\033[0m"
        elif status == "KNOWN":
            color_start = "\033[92m"  # Green
            color_end = "\033[0m"
        elif status == "AMBIGUOUS":
            color_start = "\033[93m"  # Yellow
            color_end = "\033[0m"

        row = f"{file_base:<30} {d['cluster_id']:<8} {color_start}{status:<12}{color_end} {d['top_label']:<20} {d['top_similarity']:.2f}"
        print(row)

    print("-" * 80)
    print(f"Total checked: {summary['total_checked']}")
    print(f"  NOVEL:     {summary['novel']}")
    print(f"  KNOWN:     {summary['known']}")
    print(f"  AMBIGUOUS: {summary['ambiguous']}")
    print("=" * 80)
