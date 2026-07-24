"""Does any morphology recur across widely separated observing sessions?

A glitch *class* recurs: the same instrumental mechanism fires in January and
again in August. Noise does not. So among the most morphologically similar pairs
of candidates, a real class should contribute pairs separated by weeks or months,
while session-local instrumental states contribute pairs separated by minutes.

The confound this has to survive: candidates from the same session share an
instrumental state and sit close in time, so they are *expected* to be more
similar. The baseline is therefore not "half the pairs are cross-session" but
the actual cross-session fraction over all pairs, which is set by how the
candidates are distributed across sessions. The question is whether the
high-similarity tail is enriched for cross-session pairs **relative to that
baseline**, not whether it contains any.

Two statistics, both against the all-pairs baseline:

* ``cross_session_fraction`` in the top-N most similar pairs. Above baseline
  means similarity tracks something that persists across sessions; below means
  it tracks session-local state.
* ``session_span`` per candidate -- how many distinct sessions its k nearest
  neighbours occupy. A recurrent morphology should have neighbours drawn from
  many sessions.

Detectors are analysed separately: a cross-detector morphological comparison is
a different question, and the manuscripts keep the two detectors apart.

Usage
-----
    python -m src.pipeline_v2_production.inter_session_recurrence --run O4a

Writes ``data/production/aggregated/inter_session_recurrence_{run}.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from src.core.utils import record_environment, setup_logger

logger = setup_logger(__name__)

AGG = Path("data/production/aggregated")
PROD = Path("data/production")


def _load_mil_vectors(taxonomy: pd.DataFrame, detector: str
                      ) -> tuple[np.ndarray, pd.DataFrame]:
    """Fetch the stored MIL vector for every candidate of one detector.

    The vectors live in the per-session HDF5 written by the production scan, so
    they are the ones that actually produced the published scores -- no
    re-encoding, and therefore none of the window-offset or context sensitivity
    that re-scoring would reintroduce.
    """
    rows, vecs = [], []
    for session, grp in taxonomy[taxonomy.detector == detector].groupby("session_id"):
        h5 = PROD / str(session) / f"novelties_{session}_{detector}.h5"
        if not h5.exists():
            logger.warning(f"missing {h5.name}, {len(grp)} candidates skipped")
            continue
        with h5py.File(h5, "r") as f:
            g = f["novelties"]
            gps_all = g["gps_times"][:]
            mil_all = g["mil_vectors"][:]
        # rtol=0 is mandatory: np.isclose defaults to rtol=1e-5, which at
        # GPS ~1.4e9 is a tolerance of ~4 hours and silently matches the wrong
        # candidate. That bug reached two submissions before it was caught.
        for gps in grp.gps_start.astype(float):
            hit = np.where(np.isclose(gps_all, gps, atol=0.5, rtol=0))[0]
            if len(hit) != 1:
                continue
            vecs.append(np.asarray(mil_all[hit[0]], dtype=np.float32))
            rows.append({"session_id": session, "gps": gps})
    if not vecs:
        raise RuntimeError(f"no MIL vectors recovered for {detector}")
    v = np.vstack(vecs)
    v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
    return v, pd.DataFrame(rows)


def analyse(detector: str, taxonomy: pd.DataFrame, top_n: int = 2000,
            k_neighbours: int = 10, seed: int = 42) -> dict:
    rng = np.random.default_rng(seed)
    v, meta = _load_mil_vectors(taxonomy, detector)
    n = len(v)
    sess = meta.session_id.to_numpy()
    gps = meta.gps.to_numpy()
    logger.info(f"[{detector}] {n} candidates over {len(np.unique(sess))} sessions")

    sim = v @ v.T
    iu = np.triu_indices(n, k=1)
    s = sim[iu]
    cross = sess[iu[0]] != sess[iu[1]]
    dt_days = np.abs(gps[iu[0]] - gps[iu[1]]) / 86400.0

    baseline = float(cross.mean())
    order = np.argsort(s)[::-1]
    top = order[:top_n]
    top_cross = float(cross[top].mean())

    # Neighbour span: distinct sessions among each candidate's k nearest.
    np.fill_diagonal(sim, -np.inf)
    nn = np.argpartition(sim, -k_neighbours, axis=1)[:, -k_neighbours:]
    span = np.array([len(np.unique(sess[row])) for row in nn])

    # Null for the span: shuffle session labels, keeping session sizes.
    null_span = []
    for _ in range(200):
        perm = rng.permutation(sess)
        null_span.append(np.mean([len(np.unique(perm[row])) for row in nn]))
    null_span = np.array(null_span)

    z = float((span.mean() - null_span.mean()) / (null_span.std(ddof=1) + 1e-12))
    return {
        "detector": detector,
        "n_candidates": int(n),
        "n_sessions": int(len(np.unique(sess))),
        "similarity_mean": float(s.mean()),
        "similarity_p99": float(np.percentile(s, 99)),
        "cross_session_fraction_all_pairs": baseline,
        "cross_session_fraction_top": top_cross,
        "top_n": int(top_n),
        "enrichment_top_vs_baseline": float(top_cross / baseline) if baseline else None,
        "median_dt_days_top_cross": float(np.median(dt_days[top][cross[top]]))
            if cross[top].any() else None,
        "max_dt_days_top_cross": float(dt_days[top][cross[top]].max())
            if cross[top].any() else None,
        "neighbour_session_span_mean": float(span.mean()),
        "neighbour_session_span_null_mean": float(null_span.mean()),
        "neighbour_session_span_z": z,
        "k_neighbours": int(k_neighbours),
    }


def run(run_name: str = "O4a", top_n: int = 2000, k_neighbours: int = 10,
        seed: int = 42) -> dict:
    tax = pd.read_csv(AGG / f"Master_Taxonomy_{run_name}.csv")
    tax = tax[tax.robustness_class == "ROBUST"]
    out = {"run": run_name, "population": "ROBUST", "detectors": {}}
    for det in ("H1", "L1"):
        out["detectors"][det] = analyse(det, tax, top_n, k_neighbours, seed)
        r = out["detectors"][det]
        logger.info(
            f"[{det}] cross-session: {r['cross_session_fraction_top']:.1%} in the top "
            f"{top_n} pairs vs {r['cross_session_fraction_all_pairs']:.1%} baseline "
            f"(x{r['enrichment_top_vs_baseline']:.2f}) | neighbour span "
            f"{r['neighbour_session_span_mean']:.2f} vs null "
            f"{r['neighbour_session_span_null_mean']:.2f} (z={r['neighbour_session_span_z']:+.1f})"
        )
    dest = AGG / f"inter_session_recurrence_{run_name.lower()}.json"
    dest.write_text(json.dumps(out, indent=2))
    logger.info(f"wrote {dest}")
    record_environment(AGG, f"inter_session_recurrence_{run_name.lower()}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", default="O4a")
    p.add_argument("--top-n", type=int, default=2000)
    p.add_argument("--k-neighbours", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    run(a.run, a.top_n, a.k_neighbours, a.seed)


if __name__ == "__main__":
    main()
