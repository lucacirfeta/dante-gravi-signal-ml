"""Physics Correlation Test — Latent-space vs classical physical parameters.

Demonstrates that the DINOv2+DPMM clustering is anchored to physical
signal properties, not just visual patterns from ImageNet pretraining.

Architecture
------------
1. ``extract_physical_params`` — shared function for per-event extraction
   of Peak Frequency, Duration proxy, and SNR proxy from the *same* 32 s
   whitened window that DINOv2 processed.
2. ``compute_mantel_test`` — permutation-based Mantel test on two N×N
   distance matrices (latent cosine vs physical Euclidean).
3. ``run_physics_correlation`` — orchestrator that loads the Master
   Taxonomy, builds both distance matrices, and produces outputs.

SNR Definition (Non-negotiable for LVK reviewers)
--------------------------------------------------
The SNR computed here is a **proxy derived from the peak amplitude of the
whitened time series**, NOT a matched-filter SNR (PyCBC/BayesWave style).
Specifically: ``SNR_proxy = max(|whitened_ts|) / std(whitened_ts)``
over the full 32 s window.  This is explicitly documented in all outputs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import h5py
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial.distance import pdist, squareform
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from src.core.data_loader import fetch_strain_data
from src.core.preprocessor import whiten, bandpass
from src.core.utils import load_config, setup_logger

matplotlib.use("Agg")

logger = setup_logger(__name__)

_CFG = load_config()
_PREPROC = _CFG["preprocessing"]


# ---------------------------------------------------------------------------
# 1. Shared physical parameter extraction
# ---------------------------------------------------------------------------


def extract_physical_params(
    gps: float,
    detector: str,
    segment_duration: int = 32,
) -> dict:
    """Extract classical physical parameters from a strain segment.

    Uses the **same** 32 s window and preprocessing chain (whiten → bandpass)
    that DINOv2 processed, guaranteeing measurement consistency.

    Parameters
    ----------
    gps : float
        GPS start time of the segment.
    detector : str
        Detector identifier (``"H1"``, ``"L1"``).
    segment_duration : int
        Segment duration in seconds (default 32, matching the production
        pipeline window).

    Returns
    -------
    dict
        Keys: ``gps``, ``detector``, ``peak_freq_hz``, ``duration_s``,
        ``snr_proxy``.  All floats.

    Notes
    -----
    **SNR proxy**: ``max(|whitened_ts|) / std(whitened_ts)`` — peak of the
    whitened time series amplitude, NOT matched-filter SNR.
    """
    gps_start = int(gps)
    gps_end = gps_start + segment_duration

    # Fetch raw strain (local HDF5 first, GWOSC fallback)
    ts = fetch_strain_data(detector, gps_start, gps_end)

    # Preprocessing — identical to production pipeline
    ts_white = whiten(ts)
    ts_bp = bandpass(ts_white)

    # --- SNR proxy ---
    data = np.array(ts_bp.value, dtype=np.float64)
    std_val = np.std(data)
    snr_proxy = float(np.max(np.abs(data)) / std_val) if std_val > 0 else 0.0

    # --- Q-Transform for peak frequency and duration ---
    qrange = tuple(_PREPROC["qrange"])
    frange = tuple(_PREPROC["frange"])

    q_gram = ts_bp.q_transform(
        qrange=qrange,
        frange=frange,
        logf=True,
        whiten=False,  # already whitened
    )

    q_data = np.array(q_gram.value, dtype=np.float64)
    freqs = np.array(q_gram.yindex.value, dtype=np.float64)
    times = np.array(q_gram.xindex.value, dtype=np.float64)

    # Peak frequency: frequency bin at the global maximum
    max_idx = np.unravel_index(np.argmax(q_data), q_data.shape)
    peak_freq_hz = float(freqs[max_idx[1]]) if q_data.ndim == 2 else float(freqs[max_idx[0]])

    # Duration proxy: temporal half-max width at the peak frequency row
    if q_data.ndim == 2:
        # q_data shape is (n_times, n_freqs) in gwpy
        freq_row = q_data[:, max_idx[1]]
    else:
        freq_row = q_data

    half_max = np.max(freq_row) * 0.5
    above_half = freq_row >= half_max
    if np.any(above_half):
        indices = np.where(above_half)[0]
        t_start_idx, t_end_idx = indices[0], indices[-1]
        if t_end_idx > t_start_idx and len(times) > t_end_idx:
            duration_s = float(times[t_end_idx] - times[t_start_idx])
        else:
            duration_s = float(times[1] - times[0]) if len(times) > 1 else 0.01
    else:
        duration_s = 0.01  # fallback

    # Sanity clamps
    peak_freq_hz = float(np.clip(peak_freq_hz, frange[0], frange[1]))
    duration_s = max(duration_s, 0.001)

    return {
        "gps": float(gps),
        "detector": detector,
        "peak_freq_hz": peak_freq_hz,
        "duration_s": duration_s,
        "snr_proxy": snr_proxy,
    }


# ---------------------------------------------------------------------------
# 2. Mantel test (permutation-based)
# ---------------------------------------------------------------------------


def compute_mantel_test(
    dist_a: np.ndarray,
    dist_b: np.ndarray,
    n_permutations: int = 9999,
    seed: int = 42,
) -> dict:
    """Permutation-based Mantel test between two square distance matrices.

    The analytic Pearson p-value is invalid for pairwise distances because
    each observation contributes to N-1 distances (non-independence).
    The permutation approach is the standard correction.

    Parameters
    ----------
    dist_a, dist_b : np.ndarray
        Symmetric N×N distance matrices.
    n_permutations : int
        Number of row/column permutations for the null distribution.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    dict
        ``r_pearson``, ``rho_spearman``, ``p_value_mantel``,
        ``n_permutations``, ``n_samples``.
    """
    assert dist_a.shape == dist_b.shape, "Distance matrices must have the same shape"
    n = dist_a.shape[0]

    # Condensed (upper-triangle) vectors
    cond_a = squareform(dist_a, checks=False)
    cond_b = squareform(dist_b, checks=False)

    # Observed correlations
    r_obs, _ = stats.pearsonr(cond_a, cond_b)
    rho_obs, _ = stats.spearmanr(cond_a, cond_b)

    # Permutation null distribution
    rng = np.random.default_rng(seed)
    n_greater = 0

    for _ in range(n_permutations):
        perm = rng.permutation(n)
        dist_b_perm = dist_b[np.ix_(perm, perm)]
        cond_b_perm = squareform(dist_b_perm, checks=False)
        r_perm, _ = stats.pearsonr(cond_a, cond_b_perm)
        if r_perm >= r_obs:
            n_greater += 1

    p_value = (n_greater + 1) / (n_permutations + 1)

    return {
        "r_pearson": float(r_obs),
        "rho_spearman": float(rho_obs),
        "p_value_mantel": float(p_value),
        "n_permutations": n_permutations,
        "n_samples": n,
    }


# ---------------------------------------------------------------------------
# 3. Orchestrator
# ---------------------------------------------------------------------------


def run_physics_correlation(
    taxonomy_csv: Path,
    production_dir: Path,
    output_dir: Path,
) -> dict:
    """Run the full Physics Correlation Test.

    Loads the Master Taxonomy, extracts MIL vectors and physical parameters
    for every event, computes the Mantel test (global + per-family), and
    produces CSV/JSON/figure outputs.

    Parameters
    ----------
    taxonomy_csv : Path
        Path to ``Master_Taxonomy_O4a.csv``.
    production_dir : Path
        Root of production session directories (contains per-session HDF5).
    output_dir : Path
        Directory for output files.

    Returns
    -------
    dict
        Summary statistics including global Mantel r and p-value.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Load taxonomy ---
    tax_df = pd.read_csv(taxonomy_csv)
    logger.info(f"Loaded {len(tax_df)} events from {taxonomy_csv}")

    # --- Collect MIL vectors from HDF5 ---
    mil_vectors = []
    valid_rows = []
    skipped = 0

    for idx, row in tax_df.iterrows():
        gps = row["gps_start"]
        session = row["session_id"]
        det = row["detector"]

        h5_path = production_dir / str(session) / f"novelties_{session}_{det}.h5"
        if not h5_path.exists():
            logger.warning(f"HDF5 missing: {h5_path}. Skipping GPS {gps}.")
            skipped += 1
            continue

        try:
            with h5py.File(h5_path, "r") as f:
                if "novelties/gps_times" not in f or "novelties/mil_vectors" not in f:
                    skipped += 1
                    continue
                gps_times = f["novelties/gps_times"][:]
                vectors = f["novelties/mil_vectors"][:]
                idx_match = np.where(gps_times == gps)[0]
                if len(idx_match) == 0:
                    skipped += 1
                    continue
                mil_vectors.append(vectors[idx_match[0]])
                valid_rows.append(row)
        except Exception as e:
            logger.warning(f"Error reading {h5_path}: {e}")
            skipped += 1

    if len(mil_vectors) < 3:
        logger.error(f"Only {len(mil_vectors)} valid events found (need ≥3). Aborting.")
        return {"status": "INSUFFICIENT_DATA", "n_valid": len(mil_vectors)}

    logger.info(f"Loaded {len(mil_vectors)} MIL vectors ({skipped} skipped).")
    valid_df = pd.DataFrame(valid_rows).reset_index(drop=True)
    X_mil = np.vstack(mil_vectors)

    # --- Extract physical parameters ---
    logger.info("Extracting physical parameters for all events...")
    phys_records = []
    failed_extraction = 0

    for i, row in valid_df.iterrows():
        gps = float(row["gps_start"])
        det = row["detector"]
        try:
            params = extract_physical_params(gps, det)
            phys_records.append(params)
        except Exception as e:
            logger.warning(f"Physical extraction failed for GPS {gps} ({det}): {e}")
            failed_extraction += 1
            phys_records.append({
                "gps": gps,
                "detector": det,
                "peak_freq_hz": np.nan,
                "duration_s": np.nan,
                "snr_proxy": np.nan,
            })

    phys_df = pd.DataFrame(phys_records)

    # Drop events with failed extraction
    valid_mask = phys_df[["peak_freq_hz", "duration_s", "snr_proxy"]].notna().all(axis=1)
    if valid_mask.sum() < 3:
        logger.error(f"Only {valid_mask.sum()} events with valid physics. Aborting.")
        return {"status": "INSUFFICIENT_PHYSICS", "n_valid": int(valid_mask.sum())}

    phys_df = phys_df[valid_mask].reset_index(drop=True)
    valid_df = valid_df[valid_mask].reset_index(drop=True)
    X_mil = X_mil[valid_mask.values]
    n_events = len(valid_df)

    logger.info(f"Proceeding with {n_events} events ({failed_extraction} extraction failures).")

    # --- Merge physics into taxonomy for CSV export ---
    export_df = valid_df.copy()
    export_df["peak_freq_hz"] = phys_df["peak_freq_hz"].values
    export_df["duration_s"] = phys_df["duration_s"].values
    export_df["snr_proxy_note"] = "peak_whitened_amplitude_NOT_matched_filter"
    export_df["snr_proxy"] = phys_df["snr_proxy"].values
    export_df.to_csv(output_dir / "physics_correlation.csv", index=False)
    logger.info(f"Saved physics_correlation.csv ({n_events} events).")

    # --- Singleton export ---
    singleton_mask = valid_df["global_family_id"].str.contains("Singleton", na=False)
    if singleton_mask.any():
        singleton_df = export_df[singleton_mask].copy()
        singleton_df.to_csv(output_dir / "singleton_physics.csv", index=False)
        logger.info(f"Saved singleton_physics.csv ({singleton_mask.sum()} singletons).")

    # --- Build distance matrices ---
    # Latent: 1 - cosine_similarity
    X_norm = normalize(X_mil, norm="l2", axis=1)
    sim_matrix = cosine_similarity(X_norm)
    latent_dist = np.clip(1.0 - sim_matrix, 0, None)
    np.fill_diagonal(latent_dist, 0)
    latent_dist = (latent_dist + latent_dist.T) / 2  # symmetrize

    # Physics: Euclidean on z-scored [freq, duration, snr]
    phys_features = phys_df[["peak_freq_hz", "duration_s", "snr_proxy"]].values.astype(np.float64)
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    phys_scaled = scaler.fit_transform(phys_features)
    physics_dist = squareform(pdist(phys_scaled, metric="euclidean"))

    # --- Global Mantel test ---
    logger.info(f"Running global Mantel test on {n_events}×{n_events} matrices...")
    if n_events < 30:
        logger.warning(f"n={n_events} < 30: statistical power may be insufficient for the Mantel test.")

    global_result = compute_mantel_test(latent_dist, physics_dist)
    logger.info(
        f"Global Mantel: r={global_result['r_pearson']:.4f}, "
        f"ρ={global_result['rho_spearman']:.4f}, "
        f"p={global_result['p_value_mantel']:.4f}"
    )

    # --- Per-family Mantel test ---
    family_results = []
    families = valid_df["global_family_id"].unique()

    for fam in families:
        fam_mask = (valid_df["global_family_id"] == fam).values
        n_fam = int(fam_mask.sum())

        if n_fam < 3:
            family_results.append({
                "family": fam,
                "n": n_fam,
                "r_pearson": np.nan,
                "rho_spearman": np.nan,
                "p_value_mantel": np.nan,
                "note": "n<3, correlation undefined",
            })
            continue

        fam_latent = latent_dist[np.ix_(fam_mask, fam_mask)]
        fam_physics = physics_dist[np.ix_(fam_mask, fam_mask)]

        try:
            fam_result = compute_mantel_test(fam_latent, fam_physics)
            family_results.append({
                "family": fam,
                "n": n_fam,
                "r_pearson": fam_result["r_pearson"],
                "rho_spearman": fam_result["rho_spearman"],
                "p_value_mantel": fam_result["p_value_mantel"],
                "note": "",
            })
            logger.info(
                f"  {fam} (n={n_fam}): r={fam_result['r_pearson']:.4f}, "
                f"p={fam_result['p_value_mantel']:.4f}"
            )
        except Exception as e:
            logger.warning(f"  {fam} (n={n_fam}): Mantel test failed: {e}")
            family_results.append({
                "family": fam,
                "n": n_fam,
                "r_pearson": np.nan,
                "rho_spearman": np.nan,
                "p_value_mantel": np.nan,
                "note": f"error: {e}",
            })

    family_stats_df = pd.DataFrame(family_results)

    # --- Save statistics ---
    stats_output = {
        "global": global_result,
        "per_family": family_results,
        "n_events_total": n_events,
        "n_failed_extraction": failed_extraction,
        "snr_definition": "peak_whitened_amplitude_NOT_matched_filter",
        "segment_duration_s": 32,
        "bandpass_hz": [_PREPROC["f_low"], _PREPROC["f_high"]],
    }
    with open(output_dir / "physics_correlation_stats.json", "w") as f:
        json.dump(stats_output, f, indent=2, default=str)
    logger.info("Saved physics_correlation_stats.json")

    # --- Generate figure ---
    _generate_figure(
        latent_dist, physics_dist, valid_df, phys_df,
        global_result, family_stats_df, output_dir
    )

    return stats_output


# ---------------------------------------------------------------------------
# 4. Figure generation
# ---------------------------------------------------------------------------


def _generate_figure(
    latent_dist: np.ndarray,
    physics_dist: np.ndarray,
    valid_df: pd.DataFrame,
    phys_df: pd.DataFrame,
    global_result: dict,
    family_stats_df: pd.DataFrame,
    output_dir: Path,
) -> None:
    """Generate the two-panel physics correlation figure.

    Panel A: Scatter of condensed distance vectors (latent vs physics).
    Panel B: Boxplots of physical parameters grouped by family.
    """
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    # --- Panel A: Distance scatter ---
    ax = axes[0]
    cond_latent = squareform(latent_dist, checks=False)
    cond_physics = squareform(physics_dist, checks=False)

    # Subsample if too many points for readability
    n_pairs = len(cond_latent)
    if n_pairs > 5000:
        rng = np.random.default_rng(42)
        idx = rng.choice(n_pairs, 5000, replace=False)
        cond_latent_plot = cond_latent[idx]
        cond_physics_plot = cond_physics[idx]
    else:
        cond_latent_plot = cond_latent
        cond_physics_plot = cond_physics

    ax.scatter(cond_physics_plot, cond_latent_plot, alpha=0.15, s=4, c="#4a90d9", edgecolors="none")

    # Regression line
    slope, intercept = np.polyfit(cond_physics_plot, cond_latent_plot, 1)
    x_line = np.linspace(cond_physics_plot.min(), cond_physics_plot.max(), 100)
    ax.plot(x_line, slope * x_line + intercept, color="#e74c3c", linewidth=2, label="Linear fit")

    r_val = global_result["r_pearson"]
    p_val = global_result["p_value_mantel"]
    ax.set_xlabel("Physical Distance (z-scored Euclidean)", fontsize=12)
    ax.set_ylabel("Latent Distance (1 − cosine similarity)", fontsize=12)
    ax.set_title("Mantel Test: Latent vs Physical Space", fontsize=14)
    ax.annotate(
        f"Mantel r = {r_val:.3f}\np (perm) = {p_val:.4f}\nn = {global_result['n_samples']}",
        xy=(0.05, 0.95), xycoords="axes fraction",
        fontsize=11, verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="wheat", alpha=0.8),
    )
    ax.legend(fontsize=10)

    # --- Panel B: Physical parameters by family ---
    ax2 = axes[1]
    plot_df = valid_df[["global_family_id"]].copy()
    plot_df["Peak Freq (Hz)"] = phys_df["peak_freq_hz"].values
    plot_df["Duration (s)"] = phys_df["duration_s"].values
    plot_df["SNR proxy"] = phys_df["snr_proxy"].values

    # Only plot families with n >= 2 for readability
    family_counts = plot_df["global_family_id"].value_counts()
    plot_families = family_counts[family_counts >= 2].index.tolist()
    plot_df_filtered = plot_df[plot_df["global_family_id"].isin(plot_families)]

    if not plot_df_filtered.empty:
        melted = plot_df_filtered.melt(
            id_vars=["global_family_id"],
            value_vars=["Peak Freq (Hz)", "Duration (s)", "SNR proxy"],
            var_name="Parameter",
            value_name="Value",
        )
        import seaborn as sns
        sns.boxplot(
            data=melted,
            x="global_family_id",
            y="Value",
            hue="Parameter",
            ax=ax2,
            palette="Set2",
        )
        ax2.set_xlabel("Family", fontsize=12)
        ax2.set_ylabel("Value (original scale)", fontsize=12)
        ax2.set_title("Physical Parameters by Morphological Family", fontsize=14)
        ax2.tick_params(axis="x", rotation=45)
        ax2.legend(fontsize=9, loc="upper right")
    else:
        ax2.text(0.5, 0.5, "No multi-member families to plot",
                 ha="center", va="center", transform=ax2.transAxes, fontsize=14)

    plt.tight_layout()
    fig_path = output_dir / "fig_latent_vs_physics.png"
    plt.savefig(fig_path, dpi=300, bbox_inches="tight")
    plt.close()
    logger.info(f"Saved {fig_path}")
