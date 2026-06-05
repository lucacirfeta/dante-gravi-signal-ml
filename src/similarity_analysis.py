import json
import logging
from pathlib import Path
import numpy as np
import argparse
from typing import Dict, Any

from src.utils import setup_logger

logger = setup_logger(__name__)


def analyze_similarity(
        session_id: str,
        detector: str,
        run: str = "O4a",
        reference_path: str = "data/reference/indomain_index.npz",
        reports_dir: Path | str | None = None,
) -> None:
    """Analyze cosine similarity distributions for clusters.

    Args:
        session_id: Session identifier.
        detector: Detector name (e.g. 'H1').
        run: Observing run (e.g. 'O4a').
        reference_path: Path to the morphological reference index.
        reports_dir: If provided, write {detector}_similarity_analysis.json here
            instead of the legacy analysis/ subdirectory.
    """
    base_dir = Path(f"data/runs/{run}/{session_id}")
    clusters_dir = base_dir / "clusters" / detector
    # Legacy output dir (backward compat)
    analysis_dir = base_dir / "analysis"

    if reports_dir is not None:
        rdir = Path(reports_dir)
        morphcheck_path = rdir / f"morphcheck_summary_{detector}.json"
        cluster_report_path = rdir / f"cluster_report_{detector}.json"
    else:
        morphcheck_path = clusters_dir / "morphcheck_report.json"
        cluster_report_path = clusters_dir / "cluster_report.json"

    if not morphcheck_path.exists():
        # Fallback to legacy morphcheck paths
        legacy_morphcheck_path = clusters_dir / "morphcheck_report.json"
        if legacy_morphcheck_path.exists():
            morphcheck_path = legacy_morphcheck_path
        elif reference_path is not None:
            ref_name = Path(reference_path).stem
            morphcheck_path = base_dir / "morphcheck" / detector / f"{ref_name}.json"
        if not morphcheck_path.exists():
            auto_dir = base_dir / "morphcheck" / detector
            if auto_dir.exists():
                reports = list(auto_dir.glob("*.json"))
                if reports:
                    morphcheck_path = sorted(reports)[-1]
                    
    if not cluster_report_path.exists():
        legacy_cluster_report = clusters_dir / "cluster_report.json"
        if legacy_cluster_report.exists():
            cluster_report_path = legacy_cluster_report

    if not morphcheck_path.exists():
        logger.error("Morphological crosscheck report not found for %s", detector)
        raise FileNotFoundError(f"Missing morphological crosscheck report for {detector}")
    if not cluster_report_path.exists():
        logger.error("Cluster report not found at %s", cluster_report_path)
        raise FileNotFoundError(f"Missing cluster report at {cluster_report_path}")

    with open(morphcheck_path, "r", encoding="utf-8") as f:
        morphcheck = json.load(f)

    with open(cluster_report_path, "r", encoding="utf-8") as f:
        cluster_report = json.load(f)

    anomalous_clusters_list = cluster_report.get("anomalous_clusters", [])
    if isinstance(anomalous_clusters_list, dict):
        anomalous_clusters_list = list(anomalous_clusters_list.keys())

    anomalous_clusters = set(anomalous_clusters_list)

    # Group samples by cluster ID
    clusters: Dict[int, list] = {}
    for detail in morphcheck.get("details", []):
        cid = detail["cluster_id"]
        if cid not in clusters:
            clusters[cid] = []
        clusters[cid].append(detail)

    results = []

    print(f"\n{'=' * 80}")
    print(f"{'SIMILARITY ANALYSIS SUMMARY (' + detector + ')':^80}")
    print(f"{'=' * 80}")

    for cid, samples in clusters.items():
        n_samples = len(samples)

        # Collect all similarities for each class across all samples in the cluster
        class_similarities: Dict[str, list] = {}
        for sample in samples:
            for neighbor in sample.get("neighbors", []):
                label = neighbor["label"]
                sim = neighbor["similarity"]
                if label not in class_similarities:
                    class_similarities[label] = []
                class_similarities[label].append(sim)

        # Calculate mean similarity per class
        mean_sims = {label: float(np.mean(sims)) for label, sims in class_similarities.items()}

        # Sort classes by mean similarity
        sorted_classes = sorted(mean_sims.items(), key=lambda x: x[1], reverse=True)

        top5 = sorted_classes[:5]
        top5_classes = [c[0] for c in top5]
        mean_sim_top5 = [round(c[1], 4) for c in top5]

        mean_sim_top1 = mean_sim_top5[0] if mean_sim_top5 else 0.0

        ratio_top1_top2 = None
        if len(mean_sim_top5) >= 2 and mean_sim_top5[1] > 0:
            ratio_top1_top2 = round(mean_sim_top1 / mean_sim_top5[1], 4)

        std_top5 = round(float(np.std(mean_sim_top5)), 4) if mean_sim_top5 else 0.0

        if mean_sim_top1 > 0.95:
            interpretation = "KNOWN — alta similarità verso classi note"
        elif mean_sim_top1 <= 0.85:
            interpretation = "NOVEL candidate — bassa similarità verso tutte le classi note"
        elif ratio_top1_top2 is not None and ratio_top1_top2 < 1.05:
            interpretation = "AMBIGUOUS — equidistante tra classi note"
        else:
            top_class = top5_classes[0] if top5_classes else "Unknown"
            interpretation = f"Sottovariante di {top_class}"

        is_anomalous = cid in anomalous_clusters

        report_entry = {
            "cluster_id": cid,
            "is_anomalous": is_anomalous,
            "n_samples": n_samples,
            "top5_classes": top5_classes,
            "mean_sim_top1": mean_sim_top1,
            "mean_sim_top5": mean_sim_top5,
            "std_top5": std_top5,
            "ratio_top1_top2": ratio_top1_top2,
            "interpretation": interpretation
        }
        results.append(report_entry)

        status_str = "anomalous" if is_anomalous else "normal"
        top1_label = top5_classes[0] if top5_classes else "N/A"
        top1_sim = mean_sim_top1
        ratio_str = f"{ratio_top1_top2:.2f}" if ratio_top1_top2 is not None else "N/A"

        print(f"Cluster {cid} ({status_str}, {n_samples} samples): top-1 = {top1_label} (sim={top1_sim:.2f}), "
              f"ratio top1/top2 = {ratio_str} -> {interpretation}")

    print(f"{'=' * 80}\n")

    # Write output — prefer reports_dir (unified layout), fall back to analysis/
    if reports_dir is not None:
        output_dir = Path(reports_dir)
    else:
        output_dir = analysis_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{detector}_similarity_analysis.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    logger.info("Saved similarity analysis to %s", output_path)
