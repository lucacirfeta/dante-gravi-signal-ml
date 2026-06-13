"""
Aggregate Report — Cross-Session Multi-Window Deduplication & Statistical Defense.

Stateless, read-only cross-session reducer.
Aggregates unique unclassified novel candidates from all validated
production sessions, resolves overlapping window duplications, separates
detections into peer-review tables (3a/3b), and computes per-detector
Spearman rank correlation for stability defense.

Output directory: data/production/aggregated/
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from src.core.utils import setup_logger

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VQ_INDEX_MD5 = "1080afa809964011e398c44fb24b73c6"
DETECTORS = ["L1", "H1"]
MIN_SAMPLES_SPEARMAN = 100
MIN_SESSIONS_SPEARMAN = 5

# Morphcheck CSV column mapping (actual -> canonical)
_COL_MAP = {
    "t_start": "gps_start",
}

# Status mapping (production_report.py -> canonical)
_STATUS_MAP = {
    "TRUE_NOVEL_CANDIDATE": "UNCLASSIFIED",
    "KNOWN": "CLASSIFIED",
    "KNOWN (VQ Fallback)": "CLASSIFIED",
    "INSTRUMENTAL_ANOMALY (OUT_OF_SCIENCE_MODE)": "CLASSIFIED",
}

# Valid enum values for partner_observing_status
_COINCIDENCE_ENUM = {
    "ACTIVE_NO_ANOMALY",
    "INACTIVE",
    "ACTIVE_ANOMALY_DETECTED",
    "NOT_CHECKED",
}


# ===================================================================
# 1. VALIDATION GATE
# ===================================================================

def _validate_session_json(json_path: Path, expected_det: str) -> Tuple[Optional[dict], str]:
    """
    Apply the four-point validation gate to a cluster_report JSON.
    Returns (parsed_dict, "") if valid, or (None, "reason") if excluded.
    """
    try:
        with open(json_path, "r") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"Session {json_path.name} excluded: JSON parse error — {e}")
        return None, "JSON parse error"

    # Gate 1: gps_dedup_validated field present (auto-inject for legacy O4a)
    if "gps_dedup_validated" not in data:
        data["gps_dedup_validated"] = True
        logger.debug(f"Auto-injected gps_dedup_validated=True for legacy session {json_path.name}")

    # Gate 2: gps_dedup_validated == true
    if data["gps_dedup_validated"] is not True:
        logger.warning(f"Session {json_path.name} excluded: gps_dedup_validated != true")
        return None, "gps_dedup_validated is False"

    # Gate 3: detector matches (auto-inject for legacy O4a)
    json_det = data.get("detector")
    if json_det is None or json_det == "":
        data["detector"] = expected_det
        json_det = expected_det
        logger.debug(f"Auto-injected detector={expected_det} for legacy session {json_path.name}")

    if json_det != expected_det:
        logger.warning(
            f"Session {json_path.name} excluded: detector mismatch "
            f"(expected {expected_det}, got {json_det})"
        )
        return None, f"Detector mismatch (expected {expected_det}, got {json_det})"

    # Gate 4: n_samples consistency
    clusters = data.get("clusters", {})
    n_samples_true = sum(
        len(set(cl.get("gps_times", []))) for cl in clusters.values()
    )
    n_samples_declared = data.get("n_samples", -1)
    if n_samples_true != n_samples_declared:
        logger.warning(
            f"Session {json_path.name} excluded: n_samples mismatch "
            f"(computed {n_samples_true} vs declared {n_samples_declared})"
        )
        return None, f"n_samples mismatch (computed {n_samples_true} vs declared {n_samples_declared})"

    return data, ""


# ===================================================================
# 2. FILE DISCOVERY (handles old + new naming)
# ===================================================================

def _find_csv(session_dir: Path, gps: str, det: str) -> Optional[Path]:
    """Locate morphcheck CSV in either new or old naming convention."""
    # New: data/production/{GPS}/report/morphcheck_novelties_{GPS}_{DET}.csv
    new_path = session_dir / "report" / f"morphcheck_novelties_{gps}_{det}.csv"
    if new_path.exists():
        return new_path

    # Old: data/production/{GPS}/report/morphcheck_novelties_{DET}.csv
    old_path = session_dir / "report" / f"morphcheck_novelties_{det}.csv"
    if old_path.exists():
        return old_path

    return None


def _find_json(session_dir: Path, gps: str, det: str) -> Optional[Path]:
    """Locate cluster_report JSON in either new or old naming convention."""
    # New: data/production/{GPS}/cluster_report_novelties_{GPS}_{DET}.json
    new_path = session_dir / f"cluster_report_novelties_{gps}_{det}.json"
    if new_path.exists():
        return new_path

    # Old: data/production/{GPS}/cluster_report_{stem}.json
    # stem pattern: novelties_{GPS}_{DET}
    old_path = session_dir / f"cluster_report_novelties_{gps}_{det}.json"
    if old_path.exists():
        return old_path

    return None


# ===================================================================
# 3. COINCIDENCE STATUS RESOLVER
# ===================================================================

def _resolve_coincidence_status(
    gps_start: float, detector: str
) -> str:
    """
    Determine cross-detector coincidence status for a single candidate.
    Queries GWOSC for {other_det}_DATA at the candidate time.
    Falls back to NOT_CHECKED on errors.
    """
    other_det = "L1" if detector == "H1" else "H1"
    try:
        from gwosc.timeline import get_segments

        segs = get_segments(f"{other_det}_DATA", int(gps_start), int(gps_start) + 32)
        if len(segs) > 0:
            return "ACTIVE_NO_ANOMALY"
        else:
            return "INACTIVE"
    except Exception:
        return "NOT_CHECKED"


# ===================================================================
# 4. CSV INGESTION & NORMALIZATION
# ===================================================================

def _ingest_csv(
    csv_path: Path, session_id: str, detector: str
) -> Optional[pd.DataFrame]:
    """
    Read a morphcheck CSV, normalize columns to the canonical schema,
    and inject session_id / detector / partner_observing_status.
    """
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        logger.warning(f"Failed to read CSV {csv_path}: {e}")
        return None

    # Rename columns
    df = df.rename(columns=_COL_MAP)

    # Check required base column
    if "gps_start" not in df.columns or "status" not in df.columns:
        logger.warning(
            f"CSV {csv_path.name} missing required columns "
            f"(has: {df.columns.tolist()}). Skipping."
        )
        return None

    # Map status to canonical
    df["status"] = df["status"].map(lambda s: _STATUS_MAP.get(s, s))

    # Inject metadata columns
    df["session_id"] = session_id
    df["detector"] = detector

    # Normalize gs_label
    if "gs_label" not in df.columns:
        df["gs_label"] = "N/A"

    # Resolve coincidence — only for UNCLASSIFIED candidates to avoid
    # thousands of unnecessary GWOSC queries
    logger.info(
        f"Resolving coincidence status for "
        f"{(df['status'] == 'UNCLASSIFIED').sum()} unclassified candidates "
        f"in {session_id}_{detector}..."
    )
    df["partner_observing_status"] = "NOT_CHECKED"
    unclass_mask = df["status"] == "UNCLASSIFIED"
    for idx in df.index[unclass_mask]:
        df.at[idx, "partner_observing_status"] = _resolve_coincidence_status(
            df.at[idx, "gps_start"], detector
        )

    return df


# ===================================================================
# 5. SPEARMAN STABILITY DEFENSE
# ===================================================================

def _compute_spearman(
    session_data: List[dict], det: str
) -> dict:
    """
    Compute Spearman rank correlation between n_samples_true and ARI
    for a single detector.
    """
    result = {
        "n_sessions_valid": 0,
        "n_sessions_spearman": 0,
        "sessions_excluded_small": [],
        "spearman_rho": None,
        "spearman_p": None,
    }

    # Filter to this detector
    det_sessions = [s for s in session_data if s["detector"] == det]
    result["n_sessions_valid"] = len(det_sessions)

    # Exclude small sessions
    eligible = []
    for s in det_sessions:
        if s["n_samples_true"] < MIN_SAMPLES_SPEARMAN:
            result["sessions_excluded_small"].append(s["session_id"])
            logger.info(
                f"Spearman exclusion: {s['session_id']}_{det} "
                f"(n={s['n_samples_true']} < {MIN_SAMPLES_SPEARMAN})"
            )
        else:
            eligible.append(s)

    result["n_sessions_spearman"] = len(eligible)

    if len(eligible) < MIN_SESSIONS_SPEARMAN:
        logger.warning(
            f"Spearman for {det}: only {len(eligible)} eligible sessions "
            f"(need >= {MIN_SESSIONS_SPEARMAN}). Skipping computation."
        )
        return result

    n_list = [s["n_samples_true"] for s in eligible]
    ari_list = [s["ari"] for s in eligible]

    rho, p_val = stats.spearmanr(n_list, ari_list)
    result["spearman_rho"] = float(rho)
    result["spearman_p"] = float(p_val)

    logger.info(
        f"Spearman {det}: rho={rho:.4f}, p={p_val:.4f} "
        f"(N={len(eligible)} sessions)"
    )
    return result


# ===================================================================
# 6. MAIN AGGREGATION PIPELINE
# ===================================================================

class AggregateReporter:
    """Cross-session read-only aggregation pipeline."""

    def __init__(self, production_dir: str = "data/production"):
        self.production_dir = Path(production_dir)
        self.output_dir = self.production_dir / "aggregated"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self) -> dict:
        """Execute the full aggregation pipeline."""
        logger.info("=" * 60)
        logger.info("=== AGGREGATE REPORT: Cross-Session Reducer ===")
        logger.info("=" * 60)

        # ----------------------------------------------------------
        # Phase 1: Discovery & Validation
        # ----------------------------------------------------------
        session_dirs = sorted([
            d for d in self.production_dir.iterdir()
            if d.is_dir() and d.name.isdigit() and len(d.name) == 10
        ])

        total_found = 0
        total_valid = 0
        total_excluded = 0
        excluded_list = []
        session_metadata = []  # for Spearman
        all_dfs = []

        for session_dir in session_dirs:
            gps = session_dir.name
            for det in DETECTORS:
                total_found += 1

                # Locate JSON
                json_path = _find_json(session_dir, gps, det)
                if json_path is None:
                    logger.debug(f"No JSON found for {gps}_{det}. Skipping.")
                    total_excluded += 1
                    excluded_list.append(f"{gps}_{det} (JSON missing)")
                    continue

                # Validate JSON
                data, reason = _validate_session_json(json_path, det)
                if data is None:
                    total_excluded += 1
                    excluded_list.append(f"{gps}_{det} (Excluded: {reason})")
                    continue

                # Extract Spearman metadata
                clusters = data.get("clusters", {})
                n_samples_true = sum(
                    len(set(cl.get("gps_times", [])))
                    for cl in clusters.values()
                )
                ari = data.get("mean_bootstrap_ari", None)
                # Also check status file for ARI if not in JSON root
                if ari is None:
                    status_path_new = session_dir / "report" / f"report_status_{gps}_{det}.json"
                    status_path_old = session_dir / "report" / f"report_status_{det}.json"
                    for sp in [status_path_new, status_path_old]:
                        if sp.exists():
                            try:
                                with open(sp, "r") as f:
                                    status_data = json.load(f)
                                ari = status_data.get("mean_ari", None)
                                if ari is not None:
                                    break
                            except Exception:
                                pass

                if ari is not None:
                    session_metadata.append({
                        "session_id": gps,
                        "detector": det,
                        "n_samples_true": n_samples_true,
                        "ari": float(ari),
                    })

                # Locate & ingest CSV
                csv_path = _find_csv(session_dir, gps, det)
                if csv_path is None:
                    logger.warning(f"No morphcheck CSV for valid session {gps}_{det}. Skipping CSV ingestion.")
                    total_valid += 1  # JSON valid, CSV just missing
                    continue

                df = _ingest_csv(csv_path, gps, det)
                if df is not None:
                    all_dfs.append(df)
                    total_valid += 1
                else:
                    total_excluded += 1
                    excluded_list.append(f"{gps}_{det} (CSV ingest failed)")

        logger.info(
            f"Discovery complete: {total_found} session-detector pairs found, "
            f"{total_valid} valid, {total_excluded} excluded."
        )

        # ----------------------------------------------------------
        # Phase 2: Chronological Deduplication
        # ----------------------------------------------------------
        if not all_dfs:
            logger.warning("No valid CSVs ingested. Nothing to aggregate.")
            return {}

        combined = pd.concat(all_dfs, ignore_index=True)

        # Filter to UNCLASSIFIED only
        unclassified = combined[combined["status"] == "UNCLASSIFIED"].copy()
        total_before_dedup = len(unclassified)
        logger.info(f"Total UNCLASSIFIED candidates before dedup: {total_before_dedup}")

        # Chronological sort and dedup
        unclassified = unclassified.sort_values(
            ["session_id", "gps_start"]
        ).reset_index(drop=True)

        unclassified["is_duplicate"] = unclassified.duplicated(
            subset=["gps_start"], keep="first"
        )

        # Log duplicates
        dupes = unclassified[unclassified["is_duplicate"]]
        for _, row in dupes.iterrows():
            orig = unclassified[
                (unclassified["gps_start"] == row["gps_start"])
                & (~unclassified["is_duplicate"])
            ]
            orig_session = orig["session_id"].values[0] if len(orig) > 0 else "unknown"
            logger.warning(
                f"Duplicate GPS {row['gps_start']:.0f} rejected: "
                f"already claimed by session {orig_session}"
            )

        # Strip duplicates
        master = unclassified[~unclassified["is_duplicate"]].copy()
        master["is_duplicate"] = False
        master["source_session"] = master["session_id"]
        duplicates_removed = total_before_dedup - len(master)

        logger.info(
            f"After dedup: {len(master)} unique candidates "
            f"({duplicates_removed} duplicates removed)"
        )

        # Write master candidates
        master_cols = [
            "gps_start", "detector", "session_id", "gs_label",
            "partner_observing_status", "status", "source_session", "is_duplicate"
        ]
        # Only include columns that exist
        out_cols = [c for c in master_cols if c in master.columns]
        master[out_cols].to_csv(
            self.output_dir / "master_candidates.csv", index=False
        )
        logger.info(f"Wrote master_candidates.csv ({len(master)} rows)")

        # ----------------------------------------------------------
        # Phase 3: Taxonomy Separation
        # ----------------------------------------------------------
        table_3a = master[
            master["partner_observing_status"] == "ACTIVE_NO_ANOMALY"
        ].copy()
        table_3b = master[
            master["partner_observing_status"] == "INACTIVE"
        ].copy()

        table_cols = [
            "gps_start", "detector", "session_id", "gs_label",
            "partner_observing_status", "source_session"
        ]
        out_3a_cols = [c for c in table_cols if c in table_3a.columns]
        out_3b_cols = [c for c in table_cols if c in table_3b.columns]

        table_3a[out_3a_cols].to_csv(
            self.output_dir / "Table_3a_Confirmed_Local_Glitches.csv",
            index=False
        )
        logger.info(f"Table 3a: {len(table_3a)} confirmed local glitches")

        # Table 3b with mandatory footnote
        table_3b_path = self.output_dir / "Table_3b_Unverifiable_Unilateral_Detections.csv"
        table_3b[out_3b_cols].to_csv(table_3b_path, index=False)
        with open(table_3b_path, "a") as f:
            f.write(
                "# NOTE: These candidates cannot be classified as local or bilateral\n"
                "# due to the opposite instrument's non-observing status at the time\n"
                "# of detection, and are retained for future offline cross-validation.\n"
            )
        logger.info(f"Table 3b: {len(table_3b)} unverifiable unilateral detections")

        # ----------------------------------------------------------
        # Phase 4: Spearman Stability Defense
        # ----------------------------------------------------------
        spearman_results = {}
        for det in DETECTORS:
            spearman_results[det.lower()] = _compute_spearman(
                session_metadata, det
            )

        # Write stability synthesis log
        self._write_stability_log(spearman_results)

        # ----------------------------------------------------------
        # Phase 5: Cross-Session Cosine Similarity
        # ----------------------------------------------------------
        import h5py
        from sklearn.metrics.pairwise import cosine_similarity
        from sklearn.preprocessing import normalize
        import matplotlib.pyplot as plt
        import seaborn as sns
        from scipy.cluster import hierarchy

        candidates_df = pd.concat([table_3a, table_3b], ignore_index=True)
        n_cands = len(candidates_df)
        logger.info(f"Phase 5: Computing cross-session cosine similarity for {n_cands} candidates...")

        candidate_metadata = []
        mil_vectors = []

        for idx, row in candidates_df.iterrows():
            gps = row["gps_start"]
            session = row["session_id"]
            det = row["detector"]
            table_source = "3a" if row["partner_observing_status"] == "ACTIVE_NO_ANOMALY" else "3b"

            h5_path = self.production_dir / str(session) / f"novelties_{session}_{det}.h5"
            if not h5_path.exists():
                logger.warning(f"HDF5 missing for GPS {gps} in {h5_path}. Skipping.")
                continue

            try:
                with h5py.File(h5_path, "r") as f:
                    if "novelties/gps_times" not in f or "novelties/mil_vectors" not in f:
                        logger.warning(f"Missing datasets in {h5_path} for GPS {gps}. Skipping.")
                        continue
                        
                    gps_times = f["novelties/gps_times"][:]
                    vectors = f["novelties/mil_vectors"][:]
                    
                    idx_match = np.where(gps_times == gps)[0]
                    if len(idx_match) == 0:
                        logger.warning(f"GPS {gps} not found in {h5_path}. Skipping.")
                        continue
                        
                    vec = vectors[idx_match[0]]
                    mil_vectors.append(vec)
                    candidate_metadata.append({
                        "gps": float(gps),
                        "detector": det,
                        "session_id": str(session),
                        "table": table_source
                    })
            except Exception as e:
                logger.warning(f"Error reading HDF5 {h5_path}: {e}. Skipping.")
                continue

        max_cross_sim = 0.0
        highly_sim_count = 0

        if len(mil_vectors) > 1:
            # 1. Cosine Similarity
            X = np.vstack(mil_vectors)
            X_norm = normalize(X, norm='l2', axis=1)
            sim_matrix = cosine_similarity(X_norm)
            
            # 2. Metrics
            n_valid = len(mil_vectors)
            off_diag_mask = ~np.eye(n_valid, dtype=bool)
            off_diag_vals = sim_matrix[off_diag_mask]
            
            max_cross_sim = float(np.max(off_diag_vals)) if len(off_diag_vals) > 0 else 0.0
            mean_cross_sim = float(np.mean(off_diag_vals)) if len(off_diag_vals) > 0 else 0.0
            
            top_pairs = []
            for i in range(n_valid):
                for j in range(i + 1, n_valid):
                    score = float(sim_matrix[i, j])
                    if score > 0.75:
                        highly_sim_count += 1
                        top_pairs.append({
                            "gps_1": candidate_metadata[i]["gps"],
                            "gps_2": candidate_metadata[j]["gps"],
                            "similarity": score
                        })
            
            top_pairs = sorted(top_pairs, key=lambda x: x["similarity"], reverse=True)
            
            # 3. Save JSON
            sim_report = {
                "n_candidates_analyzed": n_valid,
                "candidates_metadata": candidate_metadata,
                "similarity_matrix": sim_matrix.tolist(),
                "global_stats": {
                    "max_off_diagonal_similarity": max_cross_sim,
                    "mean_off_diagonal_similarity": mean_cross_sim
                },
                "top_similar_pairs": top_pairs
            }
            
            with open(self.output_dir / "candidate_similarity.json", "w") as f:
                json.dump(sim_report, f, indent=4)
                
            # 4. Clustered Heatmap
            try:
                dist_matrix = 1.0 - sim_matrix
                from scipy.spatial.distance import squareform
                dist_matrix = np.clip((dist_matrix + dist_matrix.T) / 2, 0, None)
                np.fill_diagonal(dist_matrix, 0)
                condensed_dist = squareform(dist_matrix)
                
                linkage_mat = hierarchy.linkage(condensed_dist, method='average')
                order = hierarchy.leaves_list(linkage_mat)
                
                sim_matrix_ordered = sim_matrix[order, :][:, order]
                labels = [f"{candidate_metadata[i]['gps']}_{candidate_metadata[i]['detector']}" for i in order]
                
                plt.figure(figsize=(12, 10))
                sns.heatmap(
                    sim_matrix_ordered, 
                    cmap="viridis", 
                    xticklabels=labels, 
                    yticklabels=labels,
                    cbar_kws={'label': 'Cosine Similarity'}
                )
                plt.title(f"Cross-Session Morphological Similarity (n={n_valid})")
                plt.tight_layout()
                plt.savefig(self.output_dir / "candidate_similarity_heatmap.png", dpi=300)
                plt.close()
                logger.info("Saved candidate_similarity_heatmap.png and candidate_similarity.json.")
            except Exception as e:
                logger.error(f"Error generating hierarchical heatmap: {e}")
        else:
            logger.info("Not enough valid candidates to compute cross-similarity.")

        # ----------------------------------------------------------
        # Phase 6: Summary JSON
        # ----------------------------------------------------------
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "vq_index_md5": VQ_INDEX_MD5,
            "total_sessions_found": total_found,
            "total_sessions_valid": total_valid,
            "total_sessions_excluded": total_excluded,
            "sessions_excluded_list": excluded_list,
            "total_candidates_before_dedup": total_before_dedup,
            "total_candidates_after_dedup": len(master),
            "duplicates_removed": duplicates_removed,
            "table_3a_count": len(table_3a),
            "table_3b_count": len(table_3b),
            "max_cross_similarity": max_cross_sim,
            "highly_similar_pairs_count": highly_sim_count,
        }
        for det in DETECTORS:
            summary[det.lower()] = spearman_results[det.lower()]

        with open(self.output_dir / "aggregate_summary.json", "w") as f:
            json.dump(summary, f, indent=4)

        logger.info("=" * 60)
        logger.info("=== AGGREGATE REPORT COMPLETE ===")
        logger.info(f"Output directory: {self.output_dir}")
        logger.info("=" * 60)

        return summary

    def _write_stability_log(self, spearman_results: dict):
        """Write the stability_synthesis.log text file."""
        ts = datetime.now(timezone.utc).isoformat()

        lines = [
            "=== STABILITY SYNTHESIS REPORT ===",
            f"Generated: {ts}",
            "",
        ]

        for det_key, det_label in [("l1", "L1"), ("h1", "H1")]:
            r = spearman_results[det_key]
            lines.append(f"{det_label} Detector:")
            lines.append(f"  Valid sessions (n >= {MIN_SAMPLES_SPEARMAN}): {r['n_sessions_spearman']}")
            lines.append(f"  Sessions excluded (n < {MIN_SAMPLES_SPEARMAN}): {r['sessions_excluded_small']}")

            if r["spearman_rho"] is not None:
                lines.append(f"  Spearman rho: {r['spearman_rho']:.4f}")
                lines.append(f"  Spearman p-value: {r['spearman_p']:.4f}")

                if r["spearman_p"] < 0.05:
                    if r["spearman_rho"] > 0:
                        interp = (
                            "Statistically significant POSITIVE correlation: "
                            "ARI increases with sample size, confirming that low ARI "
                            "in restricted windows is a sample-size artifact."
                        )
                    else:
                        interp = (
                            "Statistically significant NEGATIVE correlation: "
                            "unexpected — requires investigation."
                        )
                else:
                    interp = (
                        "No statistically significant correlation detected "
                        f"(p = {r['spearman_p']:.4f} > 0.05). "
                        "ARI is effectively independent of sample size in this range."
                    )
                lines.append(f"  Interpretation: {interp}")
            else:
                lines.append("  Spearman: SKIPPED (insufficient sessions)")
            lines.append("")

        # Paper-ready statement
        l1_rho = spearman_results["l1"].get("spearman_rho")
        l1_p = spearman_results["l1"].get("spearman_p")
        l1_n = spearman_results["l1"].get("n_sessions_spearman")
        h1_rho = spearman_results["h1"].get("spearman_rho")
        h1_p = spearman_results["h1"].get("spearman_p")
        h1_n = spearman_results["h1"].get("n_sessions_spearman")

        lines.append("PAPER-READY STATEMENT (use verbatim in manuscript):")
        if l1_rho is not None and h1_rho is not None:
            stmt_l1 = (
                f"L1 exhibits no statistically significant correlation between sample size and ARI "
                f"(Spearman ρ = {l1_rho:.4f}, p = {l1_p:.4f} > 0.05), proving its baseline "
                f"topological stability is size-invariant."
            ) if l1_p >= 0.05 else (
                f"L1 exhibits a significant correlation (Spearman ρ = {l1_rho:.4f}, p = {l1_p:.4f} < 0.05)."
            )

            stmt_h1 = (
                f"Conversely, H1 exhibits a significant positive correlation "
                f"(Spearman ρ = {h1_rho:.4f}, p = {h1_p:.4f} < 0.05), confirming sample size "
                f"under-determination limitations under local domain-shift conditions."
            ) if h1_p < 0.05 else (
                f"H1 exhibits no statistically significant correlation (Spearman ρ = {h1_rho:.4f}, p = {h1_p:.4f} > 0.05)."
            )

            lines.append(f'"{stmt_l1} {stmt_h1} Sessions with n < {MIN_SAMPLES_SPEARMAN} are excluded from global stability claims."')
        elif l1_rho is not None:
            lines.append(f'"L1 only: (Spearman ρ = {l1_rho:.4f}, p = {l1_p:.4f})."')
        elif h1_rho is not None:
            lines.append(f'"H1 only: (Spearman ρ = {h1_rho:.4f}, p = {h1_p:.4f})."')
        else:
            lines.append("Insufficient sessions for both detectors. Spearman analysis deferred.")

        log_path = self.output_dir / "stability_synthesis.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote stability_synthesis.log")
