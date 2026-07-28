"""Is the DSD survivor population an artifact of the dictionary size K? (P4)

The native O4a index has K=1216 centroids, a number set by a fixed tokens-per-
centroid ratio, not by anything physical. If which candidates survive the DSD
depends on that choice, the survivor set -- the central object of the survey --
is partly an artifact of a hyperparameter.

This is the K-analogue of the background-resampling test (P5): P5 held K fixed
and resampled the background; P4 holds the background fixed and sweeps K over
{512, 1024, 1216, 2048}. It reuses P5's cached patch tokens for the same 130
near-threshold candidates and the same 1300-segment background, so the two tests
are directly comparable and nothing is re-encoded -- only the K-means dictionary
is rebuilt at each K and the candidates re-scored.

The answer is read from the same threshold-independent statistics P5 used, for
the same reason (reproducing the production survive/reject threshold is subtle;
it is calibrated on un-vetoed background while the index is built on vetoed
background, LAB_NOTEBOOK section 19):

* **Score rank correlation** between each K and the production K=1216 -- if a
  candidate ranks high at one K and high at another, the ordering is a property
  of the candidate, not of K.
* **Per-candidate score std** across K -- how much a candidate's score wobbles
  as the dictionary is coarsened or refined.
* **ROBUST vs rejected separation** at each K -- if survivors still outscore
  rejected candidates at every K, the boundary is not a K artifact.

Requires the P5 token cache; run ``dsd-index-stability`` first if it is absent.

Usage
-----
    python -m src.pipeline_v2_production.dsd_k_sensitivity
    python -m src.pipeline_v2_production.dsd_k_sensitivity --k-values 512 1024 1216 2048

Writes
``data/production/aggregated/dsd_k_sensitivity_{run}_{representation}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.index_contract import load_taxonomy_view, qrange_tag
from src.core.utils import load_config, record_environment, setup_logger
from src.pipeline_v2_production.dsd_index_stability import _sample
from src.pipeline_v3_multiscale.norm_leakage.common import topk_score

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
TOP_K = 68
PRODUCTION_K = 1216
DEFAULT_K_VALUES = (512, 1024, 1216, 2048)


def _build_index_k(tokens: np.ndarray, k: int, seed: int) -> np.ndarray:
    """K-means dictionary of exactly k L2-normed centroids over stacked tokens."""
    from sklearn.cluster import MiniBatchKMeans

    flat = tokens.reshape(-1, tokens.shape[-1])
    km = MiniBatchKMeans(n_clusters=k, batch_size=4096, compute_labels=False,
                         random_state=seed, n_init="auto")
    km.fit(flat)
    c = km.cluster_centers_
    return c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-12)


def run(run_name: str = "O4a", n_candidates: int = 40,
        k_values=DEFAULT_K_VALUES, seed: int = 42) -> dict:
    qrange = tuple(
        int(value) for value in load_config()["preprocessing"]["qrange"]
    )
    taxonomy, contract = load_taxonomy_view(
        AGG,
        run_name,
        index_qrange=qrange,
        query_qrange=qrange,
    )
    threshold_path = AGG / (
        f"dsd_thresholds_{run_name.lower()}_{contract.representation}.json"
    )
    threshold_record = json.loads(threshold_path.read_text(encoding="utf-8"))
    if (
        threshold_record.get("representation", {}).get("variant")
        != contract.representation
    ):
        raise RuntimeError("DSD threshold representation mismatch")
    cands = _sample(
        taxonomy.assign(
            gps_start=lambda data: data.gps_start.astype(int)
        ),
        n_candidates,
        threshold_record["thresholds"],
    )
    candidate_keys = np.asarray(
        [
            f"{detector}:{gps}"
            for detector, gps in zip(cands.detector, cands.gps_start)
        ]
    )
    cache = AGG / (
        f"dsd_index_stability_tokens_{run_name.lower()}_"
        f"{contract.cache_tag}_{qrange_tag(qrange)}_"
        f"n{n_candidates}_s{seed}.npz"
    )
    if not cache.exists():
        raise FileNotFoundError(
            f"{cache.name} missing. Run `dsd-index-stability` first to build the "
            "candidate/background token cache this test reuses.")
    logger.info(f"loading cached tokens from {cache.name}")
    z = np.load(cache, allow_pickle=True)
    cand_tok, kept, bg_tok = z["cand"], z["kept"], z["bg"]
    if (
        tuple(int(value) for value in z["qrange"].tolist()) != qrange
        or str(z["representation"].item()) != contract.representation
        or not np.array_equal(z["candidate_keys"], candidate_keys)
    ):
        raise RuntimeError(f"Token cache contract mismatch: {cache}")
    cands = cands[kept].reset_index(drop=True)
    is_rob = (cands.dsd_class == "ROBUST").to_numpy()
    logger.info(f"{len(cand_tok)} candidates ({int(is_rob.sum())} ROBUST, "
                f"{int((~is_rob).sum())} rejected); sweeping K={list(k_values)}")

    k_values = sorted(set(int(k) for k in k_values))
    scores = np.zeros((len(k_values), len(cand_tok)))
    rob_mean, rej_mean = {}, {}
    for i, k in enumerate(k_values):
        cents = _build_index_k(bg_tok, k, seed)
        s = np.array([topk_score(t, cents, TOP_K) for t in cand_tok])
        scores[i] = s
        rob_mean[k] = float(s[is_rob].mean())
        rej_mean[k] = float(s[~is_rob].mean())
        logger.info(f"K={k}: ROBUST {rob_mean[k]:.3f} vs rejected {rej_mean[k]:.3f}")

    # Rank correlation of every K against the production K, plus pairwise.
    from scipy.stats import spearmanr
    if PRODUCTION_K in k_values:
        ref = scores[k_values.index(PRODUCTION_K)]
        vs_prod = {k: float(spearmanr(scores[i], ref).statistic)
                   for i, k in enumerate(k_values) if k != PRODUCTION_K}
    else:
        vs_prod = {}
    rhos = [spearmanr(scores[i], scores[j]).statistic
            for i in range(len(k_values)) for j in range(i + 1, len(k_values))]
    per_cand_std = scores.std(axis=0)

    out = {
        "run": run_name,
        "representation": contract.representation,
        "taxonomy_path": str(contract.path),
        "qrange": list(qrange),
        "n_candidates": int(len(cand_tok)),
        "n_robust": int(is_rob.sum()), "n_rejected": int((~is_rob).sum()),
        "k_values": k_values, "production_k": PRODUCTION_K, "seed": seed,
        "n_background_segments": int(bg_tok.shape[0]),
        # --- primary, threshold-independent ---
        "rank_correlation_vs_production_k": vs_prod,
        "rank_correlation_pairwise_mean": float(np.mean(rhos)),
        "rank_correlation_pairwise_min": float(np.min(rhos)),
        "per_candidate_score_std_median": float(np.median(per_cand_std)),
        "per_candidate_score_std_max": float(per_cand_std.max()),
        "robust_mean_by_k": rob_mean,
        "rejected_mean_by_k": rej_mean,
        "separation_by_k": {k: rob_mean[k] - rej_mean[k] for k in k_values},
    }
    dest = AGG / (
        f"dsd_k_sensitivity_{run_name.lower()}_"
        f"{contract.representation}.json"
    )
    dest.write_text(json.dumps(out, indent=2))
    logger.info(
        f"rank-corr vs production K: { {k: round(v, 3) for k, v in vs_prod.items()} } | "
        f"pairwise mean {out['rank_correlation_pairwise_mean']:.3f} "
        f"(min {out['rank_correlation_pairwise_min']:.3f}) | per-candidate std "
        f"median {out['per_candidate_score_std_median']:.4f}")
    logger.info(f"wrote {dest}")
    record_environment(
        AGG,
        f"dsd_k_sensitivity_{run_name.lower()}_{contract.representation}",
    )
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--n-candidates", type=int, default=40,
                   help="Must match the P5 token cache this test reuses.")
    p.add_argument("--k-values", type=int, nargs="+", default=list(DEFAULT_K_VALUES))
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    run(a.run, n_candidates=a.n_candidates, k_values=a.k_values, seed=a.seed)


if __name__ == "__main__":
    main()
