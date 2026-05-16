"""Morphological similarity checker using cosine KNN search
against the Gravity Spy training set reference index."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from src.utils import setup_logger

logger = setup_logger(__name__)

def cosine_knn_search(
    query_embeddings: np.ndarray,
    reference_embeddings: np.ndarray,
    reference_labels: np.ndarray,
    k: int = 5,
) -> list[dict]:
    """Perform KNN search using cosine similarity."""
    # Assuming embeddings are already L2-normalized
    similarities = query_embeddings @ reference_embeddings.T
    
    results = []
    for i, sim_row in enumerate(similarities):
        # Get indices of top-K largest similarities
        top_indices = np.argsort(sim_row)[-k:][::-1]
        
        neighbors = []
        labels_in_top_k = []
        for rank, idx in enumerate(top_indices):
            label = str(reference_labels[idx])
            sim = float(sim_row[idx])
            neighbors.append({"label": label, "similarity": sim, "rank": rank + 1})
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
    """Assess novelty status based on KNN results."""
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

def run_morphological_crosscheck(
    anomalous_embeddings: np.ndarray,
    anomalous_files: list[str],
    anomalous_cluster_ids: list[int],
    reference_index_path: Path,
    output_path: Path,
    k: int = 5,
    novelty_threshold: float = 0.85,
    consensus_threshold: float = 0.6,
) -> dict:
    """Orchestrate full morphological crosscheck."""
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
    print(f"\n{color}{'='*80}")
    print(f"{'MORPHOLOGICAL CROSSCHECK SUMMARY' + det_str:^80}")
    print(f"{'='*80}{reset}")
    
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
