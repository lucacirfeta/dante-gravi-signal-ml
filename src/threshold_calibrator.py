"""Per-class cosine similarity threshold calibration for autopilot scan.

Loads the in-domain reference index (``indomain_index.npz``), computes
intra-class cosine similarities from random sample pairs, and saves
the N-th percentile as a per-class threshold to
``data/autopilot/reference/thresholds.json``.

These thresholds are consumed by :mod:`src.scan_live` to classify new
spectrograms as KNOWN, AMBIGUOUS, or NOVEL without any supervised
training.

Usage::

    from src.threshold_calibrator import calibrate_thresholds
    calibrate_thresholds(
        reference_path="data/reference/indomain_index.npz",
        percentile=5,
        output_path="data/autopilot/reference/thresholds.json",
    )
"""

from __future__ import annotations

import itertools
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.utils import setup_logger

logger: logging.Logger = setup_logger(__name__)


def calibrate_thresholds(
    reference_path: str | Path,
    percentile: int = 5,
    output_path: str | Path = "data/autopilot/reference/thresholds.json",
) -> dict:
    """Calibrate per-class cosine similarity thresholds.

    For each class in the reference index, samples up to 200 intra-class
    pairs, computes their cosine similarity (embeddings are already
    L2-normalised, so ``dot(a, b)`` equals cosine similarity), and takes
    the *percentile*-th percentile as the class threshold.

    Args:
        reference_path: Path to the ``.npz`` reference index containing
            ``embeddings`` and ``labels`` arrays.
        percentile: Percentile to use as threshold (lower = stricter).
            Default **5** means the 5th percentile of intra-class
            similarities.
        output_path: Destination JSON file for the thresholds.

    Returns:
        The full thresholds dictionary (same structure written to disk).

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

    # Load reference embeddings and labels
    data = np.load(reference_path)
    embeddings: np.ndarray = data["embeddings"]  # (N, 384), L2-normalised
    labels: np.ndarray = data["labels"]           # (N,) str

    unique_classes = sorted(set(labels))
    logger.info(
        "Loaded reference: %d embeddings, %d classes from %s",
        len(embeddings),
        len(unique_classes),
        reference_path,
    )

    max_pairs = 200
    thresholds: dict[str, float] = {}

    for cls in unique_classes:
        mask = labels == cls
        cls_embeddings = embeddings[mask]
        n_samples = len(cls_embeddings)

        if n_samples < 2:
            logger.warning(
                "Class %s has only %d sample(s) — skipping threshold calibration.",
                cls,
                n_samples,
            )
            continue

        # Generate intra-class pairs
        all_pairs = list(itertools.combinations(range(n_samples), 2))
        n_total_pairs = len(all_pairs)

        if n_total_pairs <= max_pairs:
            sampled_pairs = all_pairs
        else:
            sampled_pairs = random.sample(all_pairs, max_pairs)

        # Compute cosine similarities (dot product of L2-normalised vectors)
        similarities = np.array(
            [
                float(np.dot(cls_embeddings[i], cls_embeddings[j]))
                for i, j in sampled_pairs
            ],
            dtype=np.float64,
        )

        threshold = float(np.percentile(similarities, percentile))
        thresholds[cls] = round(threshold, 4)

        logger.info(
            "Class %s: threshold=%.4f (p%d, %d intra-class pairs)",
            cls,
            threshold,
            percentile,
            len(sampled_pairs),
        )

    # Build output document
    result = {
        "metadata": {
            "reference": str(reference_path),
            "percentile": percentile,
            "calibrated_at": datetime.now(timezone.utc).isoformat(),
            "n_classes": len(thresholds),
        },
        "thresholds": thresholds,
    }

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    logger.info(
        "Saved %d class thresholds → %s (percentile=%d)",
        len(thresholds),
        output_path,
        percentile,
    )
    return result
