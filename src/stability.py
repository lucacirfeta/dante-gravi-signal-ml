"""Clustering stability analysis module.

Evaluates the robustness of the clustering pipeline by applying
random perturbations to UMAP and HDBSCAN parameters and computing
the pairwise Adjusted Rand Index (ARI) over multiple runs.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

import numpy as np
from sklearn.metrics import adjusted_rand_score

from src.clustering import (
    identify_anomalous_clusters,
    run_hdbscan,
    run_pca,
    run_umap,
)
from src.dpmm_clustering import run_dpmm
from src.utils import setup_logger, session_path

logger: logging.Logger = setup_logger(__name__)


def run_stability_analysis(
    embeddings: np.ndarray,
    cluster_cfg: dict,
    n_runs: int = 20,
    session_id: str = "default",
    detector: str = "H1",
    run: str = "O4a",
    anomaly_criterion: str = "likelihood",
) -> None:
    """Run stability analysis and save report.

    Args:
        embeddings: Array of shape (N, 384)
        cluster_cfg: Dictionary containing clustering config parameters
        n_runs: Number of perturbed runs to perform
        session_id: Current session identifier
        detector: Detector identifier (e.g. H1)
    """
    logger.info("=== STABILITY ANALYSIS: %d runs ===", n_runs)

    n_samples = len(embeddings)

    # 1. Run PCA once (as it is deterministic given the same seed and we don't perturb it)
    logger.info("Running baseline PCA...")
    pca_reduced, _ = run_pca(
        embeddings,
        n_components=cluster_cfg.get("pca_components", 50),
    )

    # 2. Determine base parameters
    umap_clust_cfg = cluster_cfg.get("umap_clustering", {})
    hdbscan_cfg = cluster_cfg.get("hdbscan", {})

    base_n_neighbors = umap_clust_cfg.get("n_neighbors", 30)
    base_min_cluster_size = hdbscan_cfg.get("min_cluster_size", 15)

    raw_anomaly = cluster_cfg.get("anomaly_threshold", 10)
    anomaly_threshold = (
        max(10, int(n_samples * 0.01))
        if raw_anomaly == "auto"
        else raw_anomaly
    )

    # Track results
    run_labels = []
    run_metadata = []

    # Frequency array to track how often each sample is anomalous
    sample_anomaly_counts = np.zeros(n_samples, dtype=int)

    # 3. Baseline run (no perturbation) to establish reference clusters
    logger.info("Running baseline clustering (Run 0)...")
    base_umap = run_umap(
        pca_reduced,
        n_components=umap_clust_cfg.get("n_components", 10),
        n_neighbors=base_n_neighbors,
        min_dist=umap_clust_cfg.get("min_dist", 0.0),
    )
    algorithm = cluster_cfg.get("algorithm", "dpmm")
    
    if algorithm == "dpmm":
        dpmm_cfg = cluster_cfg.get("dpmm", {})

        # Resolve calibrated anomaly threshold: 'auto' or missing → auto-calibrate if possible
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

        base_labels, base_stats, base_anomalous = run_dpmm(
            base_umap,
            n_components=dpmm_cfg.get("n_components", 25),
            anomaly_percentile=dpmm_cfg.get("anomaly_percentile", 5.0),
            anomaly_threshold=dpmm_anomaly_threshold,
        )
        if anomaly_criterion == "likelihood":
            from sklearn.mixture import BayesianGaussianMixture
            bgm = BayesianGaussianMixture(
                n_components=dpmm_cfg.get("n_components", 25),
                weight_concentration_prior_type="dirichlet_process",
                weight_concentration_prior=1.0 / dpmm_cfg.get("n_components", 25),
                random_state=42,
                n_init=5,
            )
            bgm.fit(base_umap)
            base_log_likelihoods = bgm.score_samples(base_umap).tolist()
            
            anomalous_set = set(base_anomalous)
            anomalous_clusters_set = set()
            for cid in set(base_labels):
                if cid == -1: continue
                members = np.where(base_labels == cid)[0]
                if len(members) == 0: continue
                below_thresh = sum(1 for m in members if m in anomalous_set)
                if below_thresh / len(members) > 0.5:
                    anomalous_clusters_set.add(int(cid))
            base_anomalous_to_save = sorted(list(anomalous_clusters_set))
            base_log_likelihoods_to_save = base_log_likelihoods
        else:
            base_anomalous_to_save = base_anomalous
            base_log_likelihoods_to_save = None
    else:
        base_labels, base_stats = run_hdbscan(
            base_umap,
            min_cluster_size=base_min_cluster_size,
            min_samples=hdbscan_cfg.get("min_samples", 10),
            cluster_selection_method=hdbscan_cfg.get("cluster_selection_method", "eom"),
        )
        base_anomalous = identify_anomalous_clusters(
            base_labels, base_stats, small_cluster_threshold=anomaly_threshold
        )
        base_anomalous_to_save = base_anomalous
        base_log_likelihoods_to_save = None

    # Add baseline to results
    run_labels.append(base_labels)
    base_run_meta = {
        "run": 0,
        "type": "baseline",
        "umap_seed": 42,
        "n_neighbors": base_n_neighbors,
        "min_cluster_size": base_min_cluster_size,
        "n_clusters": base_stats["n_clusters"],
        "anomalous_clusters": base_anomalous_to_save,
    }
    if base_log_likelihoods_to_save is not None:
        base_run_meta["log_likelihoods"] = base_log_likelihoods_to_save
    run_metadata.append(base_run_meta)

    if algorithm == "dpmm":
        if anomaly_criterion == "likelihood":
            for cid in base_anomalous_to_save:
                sample_anomaly_counts[base_labels == cid] += 1
        else:
            sample_anomaly_counts[base_anomalous] += 1
    else:
        for cid in base_anomalous_to_save:
            sample_anomaly_counts[base_labels == cid] += 1

    # 4. Perturbed runs
    for i in range(1, n_runs + 1):
        seed = random.randint(0, 100000)
        
        # Perturb parameters by random factor in [0.8, 1.2]
        factor_umap = random.uniform(0.8, 1.2)
        factor_hdbscan = random.uniform(0.8, 1.2)
        
        p_n_neighbors = max(2, int(round(base_n_neighbors * factor_umap)))
        p_min_cluster = max(2, int(round(base_min_cluster_size * factor_hdbscan)))

        logger.info(
            "Run %d/%d | seed=%d | n_neighbors=%d | min_cluster_size=%d",
            i, n_runs, seed, p_n_neighbors, p_min_cluster
        )

        p_umap = run_umap(
            pca_reduced,
            n_components=umap_clust_cfg.get("n_components", 10),
            n_neighbors=p_n_neighbors,
            min_dist=umap_clust_cfg.get("min_dist", 0.0),
            random_state=seed,
        )

        if algorithm == "dpmm":
            dpmm_cfg = cluster_cfg.get("dpmm", {})
            p_labels, p_stats, p_anomalous = run_dpmm(
                p_umap,
                n_components=dpmm_cfg.get("n_components", 25),
                anomaly_percentile=dpmm_cfg.get("anomaly_percentile", 5.0),
                random_state=seed,
                anomaly_threshold=dpmm_anomaly_threshold,
            )
            if anomaly_criterion == "likelihood":
                from sklearn.mixture import BayesianGaussianMixture
                bgm = BayesianGaussianMixture(
                    n_components=dpmm_cfg.get("n_components", 25),
                    weight_concentration_prior_type="dirichlet_process",
                    weight_concentration_prior=1.0 / dpmm_cfg.get("n_components", 25),
                    random_state=seed,
                    n_init=5,
                )
                bgm.fit(p_umap)
                p_log_likelihoods = bgm.score_samples(p_umap).tolist()
                
                anomalous_set = set(p_anomalous)
                anomalous_clusters_set = set()
                for cid in set(p_labels):
                    if cid == -1: continue
                    members = np.where(p_labels == cid)[0]
                    if len(members) == 0: continue
                    below_thresh = sum(1 for m in members if m in anomalous_set)
                    if below_thresh / len(members) > 0.5:
                        anomalous_clusters_set.add(int(cid))
                p_anomalous_to_save = sorted(list(anomalous_clusters_set))
                p_log_likelihoods_to_save = p_log_likelihoods
            else:
                p_anomalous_to_save = p_anomalous
                p_log_likelihoods_to_save = None
        else:
            p_labels, p_stats = run_hdbscan(
                p_umap,
                min_cluster_size=p_min_cluster,
                min_samples=hdbscan_cfg.get("min_samples", 10),
                cluster_selection_method=hdbscan_cfg.get("cluster_selection_method", "eom"),
            )
            p_anomalous = identify_anomalous_clusters(
                p_labels, p_stats, small_cluster_threshold=anomaly_threshold
            )
            p_anomalous_to_save = p_anomalous
            p_log_likelihoods_to_save = None

        run_labels.append(p_labels)
        p_run_meta = {
            "run": i,
            "type": "perturbed",
            "umap_seed": seed,
            "n_neighbors": p_n_neighbors,
            "min_cluster_size": p_min_cluster,
            "n_clusters": p_stats["n_clusters"],
            "anomalous_clusters": p_anomalous_to_save,
        }
        if p_log_likelihoods_to_save is not None:
            p_run_meta["log_likelihoods"] = p_log_likelihoods_to_save
        run_metadata.append(p_run_meta)

        if algorithm == "dpmm":
            if anomaly_criterion == "likelihood":
                for cid in p_anomalous_to_save:
                    sample_anomaly_counts[p_labels == cid] += 1
            else:
                sample_anomaly_counts[p_anomalous] += 1
        else:
            for cid in p_anomalous_to_save:
                sample_anomaly_counts[p_labels == cid] += 1

    # 5. Calculate ARI matrix
    total_runs = n_runs + 1
    ari_matrix = np.zeros((total_runs, total_runs))
    ari_values = []

    for i in range(total_runs):
        for j in range(i, total_runs):
            if i == j:
                ari = 1.0
            else:
                ari = adjusted_rand_score(run_labels[i], run_labels[j])
                ari_values.append(ari)
            ari_matrix[i, j] = ari
            ari_matrix[j, i] = ari

    mean_ari = float(np.mean(ari_values)) if ari_values else 1.0
    std_ari = float(np.std(ari_values)) if ari_values else 0.0

    # 6. Interpretation
    if mean_ari > 0.8:
        interpretation = "robust"
    elif mean_ari >= 0.5:
        interpretation = "moderate"
    else:
        interpretation = "unstable"

    # 7. Consistently anomalous clusters (>= 80% of runs)
    threshold_count = int(total_runs * 0.8)
    consistently_anomalous_samples = np.where(sample_anomaly_counts >= threshold_count)[0]
    
    # Map back to baseline cluster IDs
    stable_anomalous_clusters = set()
    for idx in consistently_anomalous_samples:
        cid = base_labels[idx]
        if cid != -1:
            stable_anomalous_clusters.add(int(cid))
    
    stable_anomalous_list = sorted(list(stable_anomalous_clusters))

    # 8. Save report
    if session_id == "default":
        output_dir = Path("data/stability")
    else:
        output_dir = session_path(run, session_id) / "stability"
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"stability_report_{detector}.json"

    report = {
        "session_id": session_id,
        "detector": detector,
        "n_samples": n_samples,
        "n_runs_total": total_runs,
        "anomaly_criterion_used": anomaly_criterion,
        "ari_stats": {
            "mean": mean_ari,
            "std": std_ari,
            "interpretation": interpretation,
        },
        "stable_anomalous_clusters_baseline_ids": stable_anomalous_list,
        "ari_matrix": ari_matrix.tolist(),
        "runs": run_metadata,
    }

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=4)

    logger.info("Stability report saved to %s", report_path)

    # 9. Log requested summary
    print(
        f"Stability ARI ({detector}): mean={mean_ari:.2f} ± {std_ari:.2f} — "
        f"clusters {stable_anomalous_list} anomalous across {threshold_count}/{total_runs} runs"
    )
