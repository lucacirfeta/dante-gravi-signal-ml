"""Sensitivity of the coherent DSD taxonomy to temporal-bootstrap choices.

The production calibration resamples complete, non-overlapping chronological
blocks.  This audit varies the block length and also evaluates the overlapping
moving-block construction without changing the released production thresholds.
It reuses only the frozen background-score arrays and coherent candidate
taxonomy, records their hashes, and reports exact class-transition matrices.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline_v2_production.background_calibration import (
    block_bootstrap_p99_ci,
)

AGG = Path("data/production/aggregated")
REP = "idxq4-64_queryq4-64"
THRESHOLDS = AGG / f"dsd_thresholds_o4a_{REP}.json"
TAXONOMY = AGG / f"Master_Taxonomy_O4a_{REP}.csv"
OUTPUT = AGG / f"dsd_block_length_sensitivity_o4a_{REP}.json"
CLASSES = ("ROBUST", "AMBIGUOUS", "BACKGROUND")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def classify_population(
    frame: pd.DataFrame,
    thresholds: dict[str, tuple[float, float]],
) -> np.ndarray:
    labels: list[str] = []
    for detector, score in zip(frame["detector"], frame["dsd_score"]):
        lower, upper = thresholds[str(detector)]
        value = float(score)
        labels.append(
            "ROBUST" if value > upper else "AMBIGUOUS" if value >= lower else "BACKGROUND"
        )
    return np.asarray(labels, dtype="U10")


def summarize_transition(reference: np.ndarray, alternative: np.ndarray) -> dict:
    reference = np.asarray(reference, dtype="U10")
    alternative = np.asarray(alternative, dtype="U10")
    if reference.shape != alternative.shape:
        raise ValueError("Transition populations must have identical shape")
    matrix = {
        before: {
            after: int(np.sum((reference == before) & (alternative == after)))
            for after in CLASSES
        }
        for before in CLASSES
    }
    changed = int(np.sum(reference != alternative))
    return {
        "n_total": int(reference.size),
        "n_changed": changed,
        "changed_fraction": float(changed / reference.size),
        "matrix": matrix,
    }


def moving_block_p99_ci(
    scores: np.ndarray,
    *,
    block_length: int,
    B: int,
    seed: int,
    chunk_size: int = 500,
) -> dict[str, float | int]:
    """Overlapping moving-block bootstrap with circular-length truncation."""
    values = np.asarray(scores, dtype=np.float64)
    length = int(block_length)
    if values.ndim != 1 or not np.isfinite(values).all():
        raise ValueError("scores must be a finite one-dimensional array")
    if length < 1 or length > len(values) // 2:
        raise ValueError("block_length must leave at least two sampled blocks")
    if B < 2 or chunk_size < 1:
        raise ValueError("B must be at least 2 and chunk_size positive")

    starts = np.arange(len(values) - length + 1, dtype=np.int64)
    offsets = np.arange(length, dtype=np.int64)
    blocks = values[starts[:, None] + offsets[None, :]]
    n_draws = int(np.ceil(len(values) / length))
    rng = np.random.default_rng(seed)
    distribution = np.empty(B, dtype=np.float64)
    for first in range(0, B, chunk_size):
        size = min(chunk_size, B - first)
        chosen = rng.integers(0, len(blocks), size=(size, n_draws))
        samples = blocks[chosen].reshape(size, -1)[:, : len(values)]
        distribution[first : first + size] = np.percentile(samples, 99, axis=1)
    return {
        "p99": float(np.percentile(values, 99)),
        "ci_lower": float(np.percentile(distribution, 2.5)),
        "ci_upper": float(np.percentile(distribution, 97.5)),
        "bootstrap_replicates": int(B),
        "bootstrap_seed": int(seed),
        "block_length": length,
        "n_overlapping_blocks": int(len(blocks)),
        "n_blocks_per_replica": n_draws,
    }


def run(*, block_lengths: tuple[int, ...], B: int, seed: int) -> dict:
    threshold_doc = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    taxonomy = pd.read_csv(TAXONOMY)
    score_column = "native_score_idxq4_64_queryq4_64"
    class_column = "robustness_class_idxq4_64_queryq4_64"
    required = {"detector", score_column, class_column}
    if missing := required.difference(taxonomy.columns):
        raise RuntimeError(f"Taxonomy lacks columns: {sorted(missing)}")
    taxonomy = taxonomy.rename(
        columns={score_column: "dsd_score", class_column: "dsd_class"}
    )
    if not np.isfinite(taxonomy["dsd_score"].to_numpy(dtype=float)).all():
        raise RuntimeError("Taxonomy contains non-finite coherent scores")
    if set(taxonomy["detector"].astype(str)) != {"H1", "L1"}:
        raise RuntimeError("Expected exactly H1 and L1 in coherent taxonomy")

    production_thresholds = {
        detector: (
            float(values["ci_lower"]),
            float(values["ci_upper"]),
        )
        for detector, values in threshold_doc["thresholds"].items()
    }
    stored = taxonomy["dsd_class"].astype(str).to_numpy(dtype="U10")
    recomputed_production = classify_population(taxonomy, production_thresholds)
    if not np.array_equal(stored, recomputed_production):
        raise RuntimeError("Stored taxonomy disagrees with production thresholds")

    score_paths = {
        detector: Path(values["background_scores_path"])
        for detector, values in threshold_doc["thresholds"].items()
    }
    scores = {detector: np.load(path) for detector, path in score_paths.items()}
    if any(len(values) != 5000 for values in scores.values()):
        raise RuntimeError("Sensitivity audit requires both 5000-score populations")

    schemes: dict[str, dict[str, dict]] = {
        "non_overlapping": {},
        "moving_overlapping": {},
    }
    for length in block_lengths:
        nbb = {
            detector: block_bootstrap_p99_ci(
                values,
                B=B,
                seed=seed,
                block_length=length,
            )
            for detector, values in scores.items()
        }
        mbb = {
            detector: moving_block_p99_ci(
                values,
                B=B,
                seed=seed,
                block_length=length,
            )
            for detector, values in scores.items()
        }
        for name, result in (("non_overlapping", nbb), ("moving_overlapping", mbb)):
            limits = {
                detector: (float(value["ci_lower"]), float(value["ci_upper"]))
                for detector, value in result.items()
            }
            labels = classify_population(taxonomy, limits)
            schemes[name][str(length)] = {
                "thresholds": result,
                "class_counts": {
                    label: int(np.sum(labels == label)) for label in CLASSES
                },
                "transition_from_production": summarize_transition(stored, labels),
            }

    output = {
        "schema_version": 1,
        "status": "complete",
        "experiment": "dsd_block_length_sensitivity",
        "scope": (
            "Sensitivity of coherent O4a DSD confidence limits and deterministic "
            "dispositions to block length and non-overlapping versus overlapping "
            "moving-block resampling; production thresholds are not overwritten."
        ),
        "representation": REP,
        "bootstrap_replicates_per_cell": int(B),
        "bootstrap_seed": int(seed),
        "block_lengths": list(block_lengths),
        "production": {
            "scheme": "non_overlapping",
            "block_length": 17,
            "thresholds": threshold_doc["thresholds"],
            "class_counts": {
                label: int(np.sum(stored == label)) for label in CLASSES
            },
        },
        "sources": {
            "thresholds": {"path": str(THRESHOLDS), "sha256": file_sha256(THRESHOLDS)},
            "taxonomy": {"path": str(TAXONOMY), "sha256": file_sha256(TAXONOMY)},
            "background_scores": {
                detector: {"path": str(path), "sha256": file_sha256(path)}
                for detector, path in score_paths.items()
            },
        },
        "schemes": schemes,
    }
    OUTPUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--block-lengths", nargs="+", type=int, default=[8, 17, 32, 64])
    parser.add_argument("--replicates", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=20260811)
    args = parser.parse_args()
    result = run(
        block_lengths=tuple(dict.fromkeys(args.block_lengths)),
        B=args.replicates,
        seed=args.seed,
    )
    for scheme, cells in result["schemes"].items():
        for length, cell in cells.items():
            changed = cell["transition_from_production"]["n_changed"]
            print(f"{scheme} b={length}: changed={changed}/{cell['transition_from_production']['n_total']}")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
