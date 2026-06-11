"""Log-likelihood threshold calibrator for DPMM anomaly detection.

Calibrates the anomaly threshold ONCE on the in-domain reference
(``indomain_index.npz``) using the identical PCA → UMAP → DPMM pipeline
used in clustering.  The resulting threshold is saved as a JSON constant
and can be injected into all subsequent clustering / stability runs via
``config.yaml``, eliminating per-run threshold instability.

Usage::

    from src.pipeline_v1_legacy.loglikelihood_calibrator import calibrate_loglikelihood_threshold
    calibrate_loglikelihood_threshold(
        reference_path="data/reference/indomain_index.npz",
        percentile=5.0,
        output_path="data/autopilot/reference/loglikelihood_threshold.json",
    )
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.mixture import BayesianGaussianMixture

from src.pipeline_v1_legacy.clustering import run_pca, run_umap
from src.core.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)


def calibrate_loglikelihood_threshold(
        reference_path: str | Path = "data/reference/indomain_index.npz",
        percentile: float = 5.0,
        output_path: str | Path = "data/autopilot/reference/loglikelihood_threshold.json",
) -> dict:
    """Calibrate the DPMM log-likelihood anomaly threshold on the reference.

    Runs the same dimensionality-reduction pipeline used by the clustering
    module (PCA 50 → UMAP 10D cosine) on the in-domain reference embeddings,
    fits a Bayesian Gaussian Mixture, and stores the *percentile*-th
    percentile of the per-sample log-likelihoods as the threshold.

    Args:
        reference_path: Path to the ``.npz`` reference index containing
            ``embeddings`` (L2-normalised) and ``labels`` arrays.
        percentile: Percentile of the log-likelihood distribution to use
            as the anomaly threshold (lower = stricter).  Default **5.0**.
        output_path: Destination JSON file for the calibrated threshold.

    Returns:
        The full result dictionary (same structure written to disk).

    Raises:
        FileNotFoundError: If *reference_path* does not exist.
    """
    reference_path = Path(reference_path)
    output_path = Path(output_path)

    if not reference_path.exists():
        raise FileNotFoundError(
            f"Reference index not found: {reference_path}. "
            f"Run 'python main.py build-indomain-reference' first."
        )

    # 1. Load reference embeddings
    data = np.load(reference_path)
    embeddings: np.ndarray = data["embeddings"]  # (N, 384), L2-normalised
    n_samples = len(embeddings)

    logger.info(
        "Loaded reference: %d embeddings from %s",
        n_samples,
        reference_path,
    )

    # 2. PCA(50) — same as clustering pipeline
    pca_reduced, pca_variance = run_pca(embeddings, n_components=50)

    # 3. UMAP(10D, cosine, min_dist=0.0) — same as clustering pipeline
    umap_embeddings = run_umap(
        pca_reduced,
        n_components=10,
        n_neighbors=30,
        min_dist=0.0,
    )

    # 4. Fit DPMM (BayesianGaussianMixture)
    logger.info("Fitting BayesianGaussianMixture (n_components=25)...")
    bgm = BayesianGaussianMixture(
        n_components=25,
        weight_concentration_prior_type="dirichlet_process",
        weight_concentration_prior=1.0 / 25,
        random_state=42,
        n_init=5,
    )
    bgm.fit(umap_embeddings)

    # 5. Compute per-sample log-likelihoods
    log_likelihoods = bgm.score_samples(umap_embeddings)

    # 6. Derive threshold
    threshold = float(np.percentile(log_likelihoods, percentile))

    logger.info(
        "Log-likelihood threshold calibrated: %.2f (p%.1f)",
        threshold,
        percentile,
    )

    # 7. Build output document
    result = {
        "threshold": round(threshold, 4),
        "percentile": percentile,
        "reference": str(reference_path),
        "n_samples": n_samples,
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
    }

    # 8. Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    logger.info("Saved log-likelihood threshold → %s", output_path)

    # 9. Update config.yaml automatically
    import re
    config_path = Path("config.yaml")
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()

            pattern = re.compile(r'(dpmm:\s*\n(?:\s+.*?\n)*?\s+anomaly_threshold:\s*)[^\n]+')
            new_content = pattern.sub(fr"\g<1>{round(threshold, 4)}   # calibrated fixed threshold", content)

            with open(config_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            logger.info("config.yaml updated with new anomaly_threshold: %.2f", threshold)
        except Exception as e:
            logger.warning("Could not update config.yaml automatically: %s", e)

    return result
