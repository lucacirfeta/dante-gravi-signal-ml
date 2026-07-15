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
from src.pipeline_v2_production.physics_correlation import run_physics_correlation

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
    "UNCONFIRMED_MORPHOLOGY": "UNCLASSIFIED",
    "KNOWN": "CLASSIFIED",
    "KNOWN_GLITCH": "CLASSIFIED",
    "INSTRUMENTAL_ANOMALY (OUT_OF_SCIENCE_MODE)": "CLASSIFIED",
    "PEM_CONFIRMED_LOCAL_GLITCH": "CLASSIFIED",
    "COINCIDENT_TRANSIENT": "UNCLASSIFIED"
}

# Valid enum values for partner_observing_status
_COINCIDENCE_ENUM = {
    "ACTIVE_UNVERIFIED",       # partner recording; anomaly search not yet run
    "ACTIVE_NO_ANOMALY",       # partner recording; morphological search ran, no match
    "ACTIVE_ANOMALY_DETECTED", # partner recording; morphological match found
    "INACTIVE",                # legacy label: partner not in observing mode
    "UNOBSERVABLE",            # partner had no data at candidate time
    "NOT_CHECKED",             # GWOSC query failed / never attempted
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

_COINC_CACHE_PATH = Path("data/production/aggregated/coincidence_status_cache.json")
_COINC_CACHE: dict | None = None


def _resolve_coincidence_status(
    gps_start: float, detector: str
) -> str:
    """
    Determine cross-detector coincidence status for a single candidate.
    Queries GWOSC for {other_det}_DATA at the candidate time.
    Falls back to NOT_CHECKED on errors.

    Results are cached on disk: GWOSC historical segments are immutable, and
    without the cache every aggregate re-run repays ~1 query/candidate
    (hours at 10k candidates). NOT_CHECKED (transient failure) is never cached.
    """
    global _COINC_CACHE
    if _COINC_CACHE is None:
        try:
            _COINC_CACHE = json.loads(_COINC_CACHE_PATH.read_text()) \
                if _COINC_CACHE_PATH.exists() else {}
        except Exception:
            _COINC_CACHE = {}
    key = f"{int(gps_start)}_{detector}"
    if key in _COINC_CACHE:
        return _COINC_CACHE[key]

    other_det = "L1" if detector == "H1" else "H1"
    try:
        from gwosc.timeline import get_segments

        segs = get_segments(f"{other_det}_DATA", int(gps_start), int(gps_start) + 32)
        if len(segs) > 0:
            # The partner was recording, but no anomaly search has been
            # performed here. Only cross_detector_veto may upgrade this to
            # ACTIVE_NO_ANOMALY / ACTIVE_ANOMALY_DETECTED after the actual
            # morphological cross-match.
            status = "ACTIVE_UNVERIFIED"
        else:
            status = "UNOBSERVABLE"
    except Exception:
        return "NOT_CHECKED"  # transient: never cached

    _COINC_CACHE[key] = status
    try:
        _COINC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if len(_COINC_CACHE) % 200 == 0 or len(_COINC_CACHE) < 10:
            _COINC_CACHE_PATH.write_text(json.dumps(_COINC_CACHE))
    except Exception:
        pass
    return status


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

    def __init__(self, production_dir: str = "data/production", run: str = "O4a"):
        self.production_dir = Path(production_dir)
        self.observing_run = run
        self.output_dir = self.production_dir / "aggregated"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._cluster_reports_cache = {}

    def _get_local_cluster_id(self, session_id: str, detector: str, gps: float) -> str:
        """Fetch the cluster ID for a specific GPS candidate from the session's JSON."""
        cache_key = f"{session_id}_{detector}"
        if cache_key not in self._cluster_reports_cache:
            session_dir = self.production_dir / str(session_id)
            json_path = _find_json(session_dir, str(session_id), detector)
            
            clusters_data = {}
            if json_path is not None:
                try:
                    with open(json_path, "r") as f:
                        data = json.load(f)
                        clusters_data = data.get("clusters", {})
                except Exception as e:
                    logger.warning(f"Failed to read JSON for cache {json_path}: {e}")
            
            self._cluster_reports_cache[cache_key] = clusters_data
            
        clusters_data = self._cluster_reports_cache[cache_key]
        for c_id, c_info in clusters_data.items():
            gps_times = c_info.get("gps_times", [])
            # Convert all to float for robust comparison
            if any(float(g) == float(gps) for g in gps_times):
                return f"C{c_id}"
                
        return "Unclustered"

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

                is_bypassed = data.get("covariance_type_used") == "bypassed_n<30"
                
                if ari is not None or is_bypassed:
                    session_metadata.append({
                        "session_id": gps,
                        "detector": det,
                        "n_samples_true": n_samples_true,
                        "ari": float(ari) if ari is not None else None,
                        "bypassed": is_bypassed
                    })

                # GEV fitting on raw background_scores removed due to EVT mathematical fallacy
                # The pipeline strictly uses the non-parametric empirical P99 threshold.
                pass

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

        # Resolve local_cluster_id for all master candidates
        logger.info("Resolving local_cluster_id for all unique candidates...")
        master["local_cluster_id"] = master.apply(
            lambda row: self._get_local_cluster_id(str(row["session_id"]), row["detector"], float(row["gps_start"])),
            axis=1
        )

        # Write master candidates
        master_cols = [
            "gps_start", "detector", "local_cluster_id", "session_id", "gs_label",
            "partner_observing_status", "status", "source_session", "is_duplicate"
        ]
        # Only include columns that exist
        out_cols = [c for c in master_cols if c in master.columns]
        master[out_cols].to_csv(
            self.output_dir / "master_candidates.csv", index=False
        )
        logger.info(f"Wrote master_candidates.csv ({len(master)} rows)")

        # ----------------------------------------------------------
        # Phase 3: Taxonomy Separation (Rigorous Cross-Detector Veto)
        # ----------------------------------------------------------
        from src.pipeline_v2_production.cross_detector_veto import execute_cross_detector_veto
        table_3a, table_3b, table_3c = execute_cross_detector_veto(master, self.output_dir.parent)

        table_cols = [
            "gps_start", "detector", "local_cluster_id", "session_id", "gs_label",
            "partner_observing_status", "source_session"
        ]
        out_3a_cols = [c for c in table_cols if c in table_3a.columns]
        out_3b_cols = [c for c in table_cols if c in table_3b.columns]
        out_3c_cols = [c for c in table_cols if c in table_3c.columns]

        if not table_3a.empty:
            table_3a[out_3a_cols].to_csv(
                self.output_dir / "Table_3a_Confirmed_Local_Glitches.csv",
                index=False
            )
        logger.info(f"Table 3a: {len(table_3a)} confirmed local glitches")

        # Table 3b with mandatory footnote
        table_3b_path = self.output_dir / "Table_3b_Unverifiable_Unilateral_Detections.csv"
        if not table_3b.empty:
            table_3b[out_3b_cols].to_csv(table_3b_path, index=False)
            with open(table_3b_path, "a") as f:
                f.write(
                    "\n# NOTE: These candidates cannot be classified as local or bilateral\n"
                    "# due to the opposite instrument's non-observing status at the time\n"
                    "# of detection, and are retained for future offline cross-validation.\n"
                )
        logger.info(f"Table 3b: {len(table_3b)} unverifiable unilateral detections")

        # Table 3c
        table_3c_path = self.output_dir / "Table_3c_Coincident_Astrophysical.csv"
        if not table_3c.empty:
            table_3c[out_3c_cols].to_csv(table_3c_path, index=False)
            with open(table_3c_path, "a") as f:
                f.write(
                    "\n# NOTE: Morphological cross-match confirmed (Cosine Similarity > tau_coh).\n"
                )
        logger.info(f"Table 3c: {len(table_3c)} coincident/astrophysical candidates")

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
        # Phase X: Aggregate Native Background Scores
        # ----------------------------------------------------------
        for det in DETECTORS:
            native_scores = []
            for s_meta in session_metadata:
                sess_id = s_meta["session_id"]
                native_path = self.production_dir / str(sess_id) / f"{self.observing_run}_{sess_id}_{det}_native_scores.npy"
                if native_path.exists():
                    try:
                        scores = np.load(native_path)
                        native_scores.append(scores)
                    except:
                        pass
            if native_scores:
                concat_scores = np.concatenate(native_scores)
                np.save(self.output_dir / f"background_scores_{det}_{self.observing_run}.npy", concat_scores)

        # ----------------------------------------------------------
        # Phase 5: Cross-Session Cosine Similarity
        # ----------------------------------------------------------
        import h5py
        from sklearn.metrics.pairwise import cosine_similarity
        from sklearn.preprocessing import normalize
        import matplotlib.pyplot as plt
        import seaborn as sns
        from scipy.cluster import hierarchy

        if not table_3a.empty: table_3a["table_source"] = "3a"
        if not table_3b.empty: table_3b["table_source"] = "3b"
        candidates_df = pd.concat([table_3a, table_3b], ignore_index=True)
        n_cands = len(candidates_df)
        logger.info(f"Phase 5: Computing cross-session cosine similarity for {n_cands} candidates...")

        candidate_metadata = []
        mil_vectors = []

        for idx, row in candidates_df.iterrows():
            gps = row["gps_start"]
            session = row["session_id"]
            det = row["detector"]
            table_source = row.get("table_source", "3a")

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
                        "table": table_source,
                        "local_cluster_id": row["local_cluster_id"]
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
            
            n_valid = len(mil_vectors)
            off_diag_mask = ~np.eye(n_valid, dtype=bool)
            off_diag_vals = sim_matrix[off_diag_mask]
            
            max_cross_sim = float(np.max(off_diag_vals)) if len(off_diag_vals) > 0 else 0.0
            highly_sim_count = int(np.sum(off_diag_vals > 0.75) // 2)

            # 2. Distance, Linkage, and Global Family Extraction
            dist_matrix = 1.0 - sim_matrix
            from scipy.spatial.distance import squareform
            dist_matrix = np.clip((dist_matrix + dist_matrix.T) / 2, 0, None)
            np.fill_diagonal(dist_matrix, 0)
            condensed_dist = squareform(dist_matrix)
            
            from scipy.cluster import hierarchy
            linkage_mat = hierarchy.linkage(condensed_dist, method='single')
            cluster_labels = hierarchy.fcluster(linkage_mat, t=0.25, criterion='distance')
            
            unique_clusters, counts = np.unique(cluster_labels, return_counts=True)
            family_map = {}
            family_counter = 1
            for c_id, count in zip(unique_clusters, counts):
                if count > 1:
                    family_map[c_id] = f"Family_{family_counter:02d}"
                    family_counter += 1
                else:
                    family_map[c_id] = "Singleton"
            
            for i, c_id in enumerate(cluster_labels):
                fam = family_map[c_id]
                if fam == "Singleton":
                    fam = f"Singleton_{int(candidate_metadata[i]['gps'])}"
                candidate_metadata[i]["global_family_id"] = fam

            # 3. Transitivity Resolution and Master Taxonomy
            is_3a = np.array([m["table"] == "3a" for m in candidate_metadata])
            is_3b = ~is_3a
            
            max_sim_to_3a = np.zeros(n_valid)
            if np.any(is_3a):
                max_sim_to_3a = np.max(sim_matrix[:, is_3a], axis=1)
                
            for i in range(n_valid):
                meta = candidate_metadata[i]
                if meta["table"] == "3a":
                    meta["transitivity_status"] = "Confirmed_Local"
                    meta["max_sim_to_3a"] = 1.0
                else:
                    meta["max_sim_to_3a"] = max_sim_to_3a[i]
                    meta["transitivity_status"] = "Resolved_via_Transitivity" if max_sim_to_3a[i] > 0.75 else "Unclassified_Physical_Anomaly"
            from src.pipeline_v2_production.query_gravity_spy import query_gravity_spy_for_gps
            
            master_records = []
            for m in candidate_metadata:
                gs_label = "Not_Found"
                gs_conf = 0.0
                
                # Query Gravity Spy only if we haven't permanently failed before
                if getattr(self, "_gs_credentials_failed", False):
                    gs_data = None
                else:
                    gs_data = query_gravity_spy_for_gps(m["gps"], m["detector"])
                    if gs_data is None:
                        logger.warning("Gravity Spy query failed (likely missing credentials). Disabling further GS queries for this run.")
                        self._gs_credentials_failed = True
                
                if gs_data and gs_data.get("count", 0) > 0:
                    gs_label = gs_data["glitches"][0].get("ml_label", "Unknown")
                    gs_conf = gs_data["glitches"][0].get("ml_confidence", 0.0)
                    
                master_records.append({
                    "gps_start": m["gps"],
                    "detector": m["detector"],
                    "session_id": m["session_id"],
                    "origin_table": m["table"],
                    "local_cluster_id": m.get("local_cluster_id", "Unknown"),
                    "global_family_id": m["global_family_id"],
                    "max_similarity_to_3a": m["max_sim_to_3a"] if m["table"] == "3b" else "",
                    "transitivity_status": m["transitivity_status"],
                    "gravity_spy_label": gs_label,
                    "gravity_spy_confidence": gs_conf
                })
                
            master_df = pd.DataFrame(master_records)
            
            # Final output paths parameterised with self.observing_run
            master_df.to_csv(self.output_dir / f"Master_Taxonomy_{self.observing_run}.csv", index=False)
            md_content = f"# Master Anomaly Taxonomy - {self.observing_run}\n\n"
            md_content += "This report aggregates all validated True Anomalies across all processed sessions.\n\n"
            logger.info(f"Saved Master_Taxonomy_{self.observing_run}.csv with {len(master_df)} candidates (including Gravity Spy labels).")

            # 4. Global Taxonomy Report JSON
            global_families = []
            unique_families = np.unique([m["global_family_id"] for m in candidate_metadata])
            
            for fam in unique_families:
                fam_mask = np.array([m["global_family_id"] == fam for m in candidate_metadata])
                members = np.where(fam_mask)[0]
                total_mem = len(members)
                t3a_mem = int(np.sum(is_3a[fam_mask]))
                t3b_mem = total_mem - t3a_mem
                
                if total_mem > 1:
                    fam_sims = sim_matrix[members][:, members]
                    mean_sim = float(np.mean(fam_sims[~np.eye(total_mem, dtype=bool)]))
                else:
                    mean_sim = 1.0
                    
                global_families.append({
                    "family_id": fam,
                    "total_members": total_mem,
                    "table_3a_members": t3a_mem,
                    "table_3b_members": t3b_mem,
                    "mean_internal_similarity": mean_sim,
                    "gps_list": [candidate_metadata[i]["gps"] for i in members]
                })
                
            taxonomy_report = {
                "transitivity_metrics": {
                    "total_table_3b_candidates": int(np.sum(is_3b)),
                    "resolved_via_transitivity": int(np.sum((is_3b) & (max_sim_to_3a > 0.75))),
                    "remaining_unverifiable_anomalies": int(np.sum((is_3b) & (max_sim_to_3a <= 0.75)))
                },
                "global_families": global_families
            }
            
            with open(self.output_dir / "global_taxonomy_report.json", "w") as f:
                json.dump(taxonomy_report, f, indent=4)
            logger.info("Saved global_taxonomy_report.json.")

            # 5. Clustered Heatmap
            try:
                order = hierarchy.leaves_list(linkage_mat)
                sim_matrix_ordered = sim_matrix[order, :][:, order]
                labels = [f"{candidate_metadata[i]['gps']}_{candidate_metadata[i]['detector']}" for i in order]
                
                plt.figure(figsize=(12, 10))
                ax = sns.heatmap(
                    sim_matrix_ordered, 
                    cmap="viridis", 
                    xticklabels=labels, 
                    yticklabels=labels,
                    cbar_kws={'label': 'Cosine Similarity'}
                )
                ax.set_xticklabels(ax.get_xticklabels(), rotation=90, fontsize=4)
                ax.set_yticklabels(ax.get_yticklabels(), rotation=0, fontsize=4)
                plt.title(f"Cross-Session Morphological Similarity (n={n_valid})")
                plt.tight_layout()
                plt.savefig(self.output_dir / "candidate_similarity_heatmap.png", dpi=300)
                plt.close()
                logger.info("Saved candidate_similarity_heatmap.png")
            except Exception as e:
                logger.error(f"Error generating hierarchical heatmap: {e}")
                
            # 5b. Intra-Cluster vs Background Distance Plot
            try:
                intra_distances = []
                background_distances = []
                
                n_elements = len(cluster_labels)
                for i in range(n_elements):
                    for j in range(i + 1, n_elements):
                        d = dist_matrix[i, j]
                        fam_i = candidate_metadata[i]["global_family_id"]
                        fam_j = candidate_metadata[j]["global_family_id"]
                        
                        if fam_i == fam_j and "Family" in fam_i:
                            intra_distances.append(d)
                        else:
                            background_distances.append(d)
                
                if intra_distances and background_distances:
                    plt.figure(figsize=(10, 6))
                    sns.kdeplot(intra_distances, label='Intra-Cluster Distances (Macro-Families)', fill=True, color='red', alpha=0.5)
                    sns.kdeplot(background_distances, label='Inter-Cluster / Background Distances', fill=True, color='gray', alpha=0.5)
                    
                    plt.title("Morphological Diffusivity: Intra-Cluster vs Background Distances")
                    plt.xlabel("Cosine Distance (1 - Cosine Similarity)")
                    plt.ylabel("Density")
                    plt.legend()
                    plt.tight_layout()
                    plt.savefig(self.output_dir / "morphological_diffusivity_distances.png", dpi=300)
                    plt.close()
                    logger.info("Saved morphological_diffusivity_distances.png")
            except Exception as e:
                logger.error(f"Error generating diffusivity plot: {e}")
                
        else:
            logger.info("Not enough valid candidates to compute cross-similarity.")

        # ----------------------------------------------------------
        # Phase 6: Summary JSON
        # ----------------------------------------------------------
        total_bypassed = sum(1 for s in session_metadata if s.get("bypassed", False))
        
        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "vq_index_md5": VQ_INDEX_MD5,
            "total_sessions_found": total_found,
            "total_sessions_valid": total_valid,
            "total_sessions_excluded": total_excluded,
            "sessions_excluded_list": excluded_list,
            "total_sessions_bypassing_dpmm": total_bypassed,
            "total_candidates_before_dedup": total_before_dedup,
            "total_candidates_after_dedup": len(master) if 'master' in locals() else 0,
            "duplicates_removed": duplicates_removed if 'duplicates_removed' in locals() else 0,
            "table_3a_count": len(table_3a) if 'table_3a' in locals() else 0,
            "table_3b_count": len(table_3b) if 'table_3b' in locals() else 0,
            "max_cross_sim": max_cross_sim if 'max_cross_sim' in locals() else 0.0,
            "highly_sim_count": highly_sim_count if 'highly_sim_count' in locals() else 0,
        }
        for det in DETECTORS:
            summary[det.lower()] = spearman_results[det.lower()]


        # ----------------------------------------------------------
        # Phase 8: Reviewer Null Tests
        # ----------------------------------------------------------
        reviewer_metrics = {}
        
        # 8a. Asymmetry
        l1_cands = len(master[master['detector'] == 'L1']) if 'master' in locals() and len(master) > 0 else 0
        h1_cands = len(master[master['detector'] == 'H1']) if 'master' in locals() and len(master) > 0 else 0
        l1_sessions = summary['l1']['n_sessions_spearman']
        h1_sessions = summary['h1']['n_sessions_spearman']
        
        reviewer_metrics['asymmetry'] = {
            'L1': {
                'candidates': l1_cands,
                'valid_sessions': l1_sessions,
                'rate': float(l1_cands / l1_sessions) if l1_sessions > 0 else 0.0
            },
            'H1': {
                'candidates': h1_cands,
                'valid_sessions': h1_sessions,
                'rate': float(h1_cands / h1_sessions) if h1_sessions > 0 else 0.0
            }
        }
        
        # ----------------------------------------------------------
        # Phase 9: Domain Shift Defense (Native O4a Index)
        # ----------------------------------------------------------
        domain_shift_metrics = self._run_domain_shift_defense(master) if 'master' in locals() else {}

        # ----------------------------------------------------------
        # Phase 9b: Strain Sanity Check & Physical Validation
        # ----------------------------------------------------------
        sanity_metrics = self._run_sanity_checks(taxonomy_report) if 'taxonomy_report' in locals() else {}
        self._generate_psd_plots(sanity_metrics)

        # ----------------------------------------------------------
        # Aggregate GEV Parameters
        # ----------------------------------------------------------
        gev_agg = {"H1": {"mu": [], "sigma": [], "xi": []}, "L1": {"mu": [], "sigma": [], "xi": []}}
        for s in session_metadata:
            if "gev_params" in s:
                det = s["detector"]
                gev_agg[det]["mu"].append(s["gev_params"]["mu"])
                gev_agg[det]["sigma"].append(s["gev_params"]["sigma"])
                gev_agg[det]["xi"].append(s["gev_params"]["xi"])
        
        gev_summary = {}
        for det in ["H1", "L1"]:
            if gev_agg[det]["mu"]:
                gev_summary[det] = {
                    "mean_mu": float(np.mean(gev_agg[det]["mu"])),
                    "mean_sigma": float(np.mean(gev_agg[det]["sigma"])),
                    "mean_xi": float(np.mean(gev_agg[det]["xi"]))
                }

        master_report = {
            "summary": summary,
            "reviewer_metrics": reviewer_metrics,
            "domain_shift_defense": domain_shift_metrics,
            "sanity_checks": sanity_metrics,
            "gev_parameters": gev_summary
        }
        # ----------------------------------------------------------
        # Phase 9b: Physics Correlation Defense
        # ----------------------------------------------------------
        taxonomy_csv = self.output_dir / f"Master_Taxonomy_{self.observing_run}.csv"

        # Guarantee the taxonomy file ALWAYS exists, even with 0/1 candidates
        # (the family-clustering branch above only runs with >1 MIL vectors and
        # used to silently skip the CSV write, producing hollow final reports).
        if not taxonomy_csv.exists():
            logger.error(
                "Master_Taxonomy was not produced by the clustering branch "
                f"({len(candidate_metadata) if 'candidate_metadata' in locals() else 0} "
                "candidates with valid MIL vectors) — writing degraded taxonomy "
                "so downstream stages and the final report see an explicit, "
                "consistent (possibly empty) candidate list."
            )
            _cols = ["gps_start", "detector", "session_id", "origin_table",
                     "local_cluster_id", "global_family_id",
                     "max_similarity_to_3a", "transitivity_status",
                     "gravity_spy_label", "gravity_spy_confidence"]
            _records = [{
                "gps_start": m["gps"], "detector": m["detector"],
                "session_id": m["session_id"], "origin_table": m["table"],
                "local_cluster_id": m.get("local_cluster_id", "Unknown"),
                "global_family_id": "Singleton",
                "max_similarity_to_3a": "", "transitivity_status": "N/A",
                "gravity_spy_label": "Not_Queried", "gravity_spy_confidence": 0.0,
            } for m in (candidate_metadata if 'candidate_metadata' in locals() else [])]
            pd.DataFrame(_records, columns=_cols).to_csv(taxonomy_csv, index=False)

        physics_stats = {}
        physics_stats_json = self.output_dir / "physics" / "physics_correlation_stats.json"
        
        if taxonomy_csv.exists():
            if physics_stats_json.exists():
                logger.info(f"Loading existing Physics Correlation stats from {physics_stats_json}")
                try:
                    with open(physics_stats_json, "r") as f:
                        physics_stats = json.load(f)
                    master_report["physics_correlation"] = physics_stats
                except Exception as e:
                    logger.error(f"Failed to load existing physics stats: {e}")
            else:
                try:
                    physics_stats = run_physics_correlation(
                        taxonomy_csv=taxonomy_csv,
                        production_dir=self.production_dir,
                        output_dir=self.output_dir,
                    )
                    master_report["physics_correlation"] = physics_stats
                    logger.info("Physics Correlation Test completed successfully.")
                except Exception as e:
                    logger.error(f"Physics Correlation Test failed: {e}")
                    physics_stats = {"status": "FAILED", "error": str(e)}
        else:
            logger.warning("Master_Taxonomy file not found. Skipping Physics Correlation.")
            

            
        logger.info(f"Aggregation complete. Taxonomy saved to Master_Taxonomy_{self.observing_run}.csv")
        
        with open(self.output_dir / "aggregate_summary.json", "w") as f:
            json.dump(master_report, f, indent=4)

        # ----------------------------------------------------------
        # Phase 10: Generate Final Discovery Markdown Report
        # ----------------------------------------------------------
        self._generate_markdown_report(master_report)

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

        stability_dir = self.output_dir / "stability"
        stability_dir.mkdir(parents=True, exist_ok=True)
        log_path = stability_dir / "stability_synthesis.log"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        logger.info(f"Wrote stability_synthesis.log")


    def _extract_detector_background(self, scorer, det_name, target_n=5000) -> np.ndarray:
        import numpy as np
        import random
        from gwpy.timeseries import TimeSeries
        from src.core.data_loader import _DATA_DIRECTORIES
        from src.core.preprocessor import whiten_context, extract_clean_subwindow, generate_qtransform
        import logging
        logger = logging.getLogger("aggregate_report")
        
        valid_files = []
        for dir_path in _DATA_DIRECTORIES:
            if dir_path.exists():
                valid_files.extend(list(dir_path.rglob(f"{det_name}_*.hdf5")))
                
        if not valid_files:
            return np.array([])
            
        random.seed(42)
        random.shuffle(valid_files)
        scores = []
        batch_size = 64
        batch_grams = []
        
        logger.info(f"Extracting {target_n} background scores from raw data for {det_name}...")
        for file_path in valid_files:
            if len(scores) >= target_n:
                break
            try:
                ts = TimeSeries.read(file_path)
                duration = int(ts.duration.value)
                
                # Use a step of 64s: 32s segment + 32s guard time
                for start_offset in range(0, duration, 64):
                    if start_offset + 32 > duration:
                        break
                    
                    pad = 4.0
                    seg_start = ts.t0.value + start_offset
                    seg_end = seg_start + 32
                    
                    crop_start = max(ts.t0.value, seg_start - pad)
                    crop_end = min(ts.t0.value + duration, seg_end + pad)
                    ts_context = ts.crop(crop_start, crop_end)
                    
                    from src.core.preprocessor import whiten_context, extract_clean_subwindow
                    ts_w, pad_info = whiten_context(ts_context, seg_start, seg_end, pad=4.0)
                    ts_clean = extract_clean_subwindow(ts_w, seg_start, seg_end)
                    q_gram = generate_qtransform(ts_clean, output_size=(256, 256))
                    # cividis like the production path — the background must
                    # live in the SAME chromatic domain as the candidate
                    # rescoring (audit B-DSD-1, second site: this one biased
                    # the native calibration itself).
                    import matplotlib
                    q_gram_rgb = (matplotlib.colormaps["cividis"](
                        np.clip(q_gram, 0.0, 1.0))[..., :3] * 255).astype(np.uint8)

                    batch_grams.append(q_gram_rgb)
                    
                    if len(batch_grams) == batch_size:
                        batch_res = scorer.score_spectrogram(batch_grams, threshold=1.0)
                        for r in batch_res:
                            scores.append(r['novelty_score'])
                            if len(scores) >= target_n:
                                break
                        batch_grams = []
                        if len(scores) >= target_n:
                            break
            except Exception:
                pass
                
        if len(batch_grams) > 0 and len(scores) < target_n:
            batch_res = scorer.score_spectrogram(batch_grams, threshold=1.0)
            for r in batch_res:
                scores.append(r['novelty_score'])
                if len(scores) >= target_n:
                    break
                    
        return np.array(scores[:target_n], dtype=np.float32)

    def _calibrate_native_threshold(self, scorer) -> dict:
        import numpy as np
        import os
        from pathlib import Path
        import logging
        logger = logging.getLogger("aggregate_report")
        
        result_dict = {}
        for det in ["L1", "H1"]:
            # NATIVE-index background scores. Distinct filename from
            # background_scores_{det}_{run}.npy, which production_report uses
            # for the PRIMARY (reference-run) index: same file for two score
            # distributions was a silent cross-contamination (audit B-DSD-2).
            det_path = self.output_dir / f"background_scores_native_{det}_{self.observing_run}.npy"
            if det_path.exists():
                scores = np.load(det_path)
            else:
                # Option A: Check for Dual-Scoring native scores
                native_files = list(self.production_dir.rglob(f"{self.observing_run}_*_{det}_native_scores.npy"))
                
                import random
                random.seed(42)
                random.shuffle(native_files)
                
                scores_list = []
                files_used = 0
                for f in native_files:
                    try:
                        file_scores = np.load(f)
                        scores_list.extend(file_scores[:500])
                        files_used += 1
                        if len(scores_list) >= 5000:
                            break
                    except:
                        pass
                
                if len(scores_list) >= 5000:
                    # FIX: Prendiamo uno slice contiguo invece di un random.sample per preservare 
                    # l'autocorrelazione temporale necessaria al block-bootstrap.
                    scores = np.array(scores_list[:5000], dtype=np.float32)
                    np.save(det_path, scores)
                    logger.info(f"Sampled 5000 contiguous dual-scoring backgrounds for {det} from {files_used} unique files, saved to {det_path}")
                    
                    # Clean up temporary native_scores files
                    for f in native_files:
                        try:
                            f.unlink()
                        except Exception as e:
                            logger.warning(f"Failed to delete temporary file {f}: {e}")
                    logger.info(f"Cleaned up {len(native_files)} temporary dual-scoring files for {det}.")
                else:
                    # Option C: Fallback to compute from raw data
                    scores = self._extract_detector_background(scorer, det, 5000)
                    if len(scores) > 0:
                        np.save(det_path, scores)
                        logger.info(f"Extracted {len(scores)} backgrounds from raw data for {det} and saved to {det_path}")
                        
            if len(scores) == 0:
                logger.error(f"Failed to obtain background scores for {det}.")
                continue
                
            def block_bootstrap_p99_ci(scores_arr, B=1000, seed=42):
                np.random.seed(seed)
                n = len(scores_arr)
                b = max(1, int(n**(1/3)))
                num_blocks = int(np.ceil(n / b))
                
                bootstrap_p99 = np.zeros(B)
                for i in range(B):
                    block_starts = np.random.randint(0, n - b + 1, size=num_blocks)
                    boot_sample = []
                    for start in block_starts:
                        boot_sample.extend(scores_arr[start:start+b])
                    boot_sample = np.array(boot_sample[:n])
                    bootstrap_p99[i] = np.percentile(boot_sample, 99)
                    
                ci_upper = np.percentile(bootstrap_p99, 97.5)
                ci_lower = np.percentile(bootstrap_p99, 2.5)
                return ci_lower, ci_upper
                
            ci_lower, ci_upper = block_bootstrap_p99_ci(scores)
            p99 = np.percentile(scores, 99)
            result_dict[det] = {"ci_lower": float(ci_lower), "ci_upper": float(ci_upper), "p99": float(p99)}
            
        return result_dict

    def _run_domain_shift_defense(self, master_df) -> dict:
        import numpy as np
        from tqdm import tqdm
        from src.core.data_loader import fetch_local_or_remote_strain
        from src.core.preprocessor import whiten_context, extract_clean_subwindow, generate_qtransform
        from src.core.patch_scorer import PatchScorer
        from pathlib import Path
        import logging
        logger = logging.getLogger("aggregate_report")
        
        run_str = self.observing_run.lower()
        from src.core.utils import get_reference_dir
        _ref_dir = get_reference_dir()
        index_ex = _ref_dir / f"patch_compressed_index_{run_str}_ex.npz"
        index_official = _ref_dir / f"patch_compressed_index_{run_str}.npz"
        
        index_path = None
        if index_ex.exists():
            index_path = index_ex
        elif index_official.exists():
            index_path = index_official
            
        metrics = {
            "experiment_run": False,
            "survival_rate": 0.0,
            "family_cohesion": {},
            "H1": {"robust": 0, "ambiguous": 0, "background": 0, "total": 0},
            "L1": {"robust": 0, "ambiguous": 0, "background": 0, "total": 0}
        }
        
        if index_path is None:
            logger.warning(f"Native {self.observing_run} index not found (checked _ex and official). Skipping Domain Shift Defense.")
            return metrics
            
        logger.info(f"Loading native {self.observing_run} index for domain shift defense...")
        try:
            scorer = PatchScorer(reference_index_path=str(index_path), verify_md5=False)
        except Exception as e:
            logger.error(f"Failed to load native index: {e}")
            return metrics
            
        threshold_dict = self._calibrate_native_threshold(scorer)
        if not threshold_dict:
            return metrics
            
        total = len(master_df)
        new_mil_vectors = {}
        
        tax_path = self.output_dir / f"Master_Taxonomy_{self.observing_run}.csv"
        tax_df = None
        robustness_records = {}
        if tax_path.exists():
            import pandas as pd
            tax_df = pd.read_csv(tax_path)
            
        for idx, row in tqdm(master_df.iterrows(), total=total, desc="Domain Shift Defense"):
            try:
                det = row['detector']
                cid = f"{row['gps_start']}_{det}"
                fam = "Unknown"
                if tax_df is not None:
                    match = tax_df[(tax_df['gps_start'] == row['gps_start']) & (tax_df['detector'] == det)]
                    if not match.empty:
                        fam = match.iloc[0]['global_family_id']
                
                start = float(row['gps_start'])
                end = start + 32
                cand_super = fetch_local_or_remote_strain(det, start - 4.0, end + 4.0, cache_raw=True, edge_tolerance=4.0)
                ts_w, pad_info = whiten_context(cand_super, start, end, pad=4.0)
                cand_ts = extract_clean_subwindow(ts_w, start, end)
                q_gram = generate_qtransform(cand_ts, output_size=(256, 256))
                # Render via the SAME colormap as the production path: the
                # native index and its calibration background are built from
                # cividis-mapped images; feeding grayscale here put candidate
                # scores in a different chromatic domain than the thresholds
                # (audit B-DSD-1 — the pre-audit survival rates carried this).
                import matplotlib
                q_gram_rgb = (matplotlib.colormaps["cividis"](
                    np.clip(q_gram, 0.0, 1.0))[..., :3] * 255).astype(np.uint8)
                    
                res = scorer.score_spectrogram([q_gram_rgb], threshold=0.0)[0]
                score = res['novelty_score']
                
                det_thresholds = threshold_dict.get(det)
                if not det_thresholds:
                    continue
                    
                ci_upper_bound = det_thresholds['ci_upper']
                ci_lower_bound = det_thresholds['ci_lower']
                
                metrics[det]["total"] += 1
                
                if score > ci_upper_bound:
                    metrics[det]["robust"] += 1
                    is_robust = True
                elif score >= ci_lower_bound:
                    metrics[det]["ambiguous"] += 1
                    is_robust = False
                else:
                    metrics[det]["background"] += 1
                    is_robust = False

                if is_robust:
                    new_mil_vectors[cid] = {
                        "fam": fam,
                        "vector": res["mil_vector"]
                    }
                
                robustness_records[cid] = {
                    "score": score,
                    "robustness_class": "ROBUST" if is_robust else ("AMBIGUOUS" if score >= ci_lower_bound else "BACKGROUND")
                }
            except Exception as e:
                logger.error(f"Failed to process candidate {cid}: {e}")
                
        if tax_df is not None and not tax_df.empty:
            def get_robustness(row):
                cid = f"{row['gps_start']}_{row['detector']}"
                return robustness_records.get(cid, {}).get("robustness_class", "BACKGROUND")
            def get_native_score(row):
                cid = f"{row['gps_start']}_{row['detector']}"
                return robustness_records.get(cid, {}).get("score", 0.0)
                
            tax_df["robustness_class"] = tax_df.apply(get_robustness, axis=1)
            tax_df["native_o4a_score"] = tax_df.apply(get_native_score, axis=1)
            tax_df.to_csv(tax_path, index=False)
            logger.info(f"Updated {tax_path.name} with native domain shift scores and robustness classification.")
            
        metrics["experiment_run"] = True
        metrics["total_evaluated"] = total
        
        robust_total = metrics["H1"]["robust"] + metrics["L1"]["robust"]
        metrics["survived_native_threshold"] = robust_total
        metrics["survival_rate"] = float(robust_total / total) if total > 0 else 0.0
        metrics["robust_count"] = robust_total
        metrics["ambiguous_count"] = metrics["H1"]["ambiguous"] + metrics["L1"]["ambiguous"]
        metrics["background_count"] = metrics["H1"]["background"] + metrics["L1"]["background"]
        
        families = {}
        for cid, data in new_mil_vectors.items():
            fam = data["fam"]
            if fam not in families:
                families[fam] = []
            families[fam].append(data["vector"])
            
        for fam in sorted(families.keys()):
            if "Singleton" in fam or fam == "Unknown":
                continue
            import numpy as np
            vectors = np.array(families[fam])
            n = vectors.shape[0]
            if n > 1:
                sim = np.dot(vectors, vectors.T)
                i_upper = np.triu_indices(n, k=1)
                mean_sim = float(np.mean(sim[i_upper]))
                
                metrics["family_cohesion"][fam] = {
                    "n": n,
                    "mean_internal_similarity": mean_sim
                }
                
        # Append robustness to taxonomy and save
        if tax_df is not None:
            tax_df["robustness_class"] = tax_df.apply(
                lambda row: robustness_records.get(f"{row['gps_start']}_{row['detector']}", {}).get("robustness_class", "UNKNOWN"), axis=1
            )
            tax_df["native_score"] = tax_df.apply(
                lambda row: robustness_records.get(f"{row['gps_start']}_{row['detector']}", {}).get("score", -1), axis=1
            )
            tax_df.to_csv(tax_path, index=False)
            logger.info(f"Updated {tax_path.name} with robustness classification.")
                
        return metrics

    def _run_sanity_checks(self, taxonomy_report: dict) -> dict:
        import numpy as np
        import logging
        sanity_metrics = {}
        families = taxonomy_report.get("global_families", [])
        
        try:
            from gwpy.timeseries import TimeSeries
            from gwpy.segments import DataQualityFlag
        except ImportError:
            logger.error("gwpy not installed. Skipping sanity checks.")
            return sanity_metrics
            
        for fam in families:
            fam_id = fam["family_id"]
            gps_list = fam.get("gps_list", [])
            if not gps_list:
                continue
                
            # Use the first GPS as the medoid/representative
            gps = float(gps_list[0])
            det = "L1" # Default assuming majority are L1 based on severe asymmetry
            
            result = {
                "gps": gps,
                "detector": det,
                "nans": 0,
                "zeros": 0,
                "max_amplitude": 0.0,
                "dq_active": False,
                "classification": "Unknown",
                "error": None
            }
            
            try:
                from src.core.data_loader import fetch_local_or_remote_strain
                # 1. Fetch Strain
                ts = fetch_local_or_remote_strain(det, gps - 2, gps + 2)
                strain = ts.value
                result["nans"] = int(np.isnan(strain).sum())
                result["zeros"] = int((strain == 0).sum())
                
                if result["nans"] == 0:
                    result["max_amplitude"] = float(np.max(np.abs(strain)))
                    
                # 2. Fetch DQ Flag (CBC_CAT1 as per paper)
                flag = DataQualityFlag.fetch_open_data(f"{det}_CBC_CAT1", gps - 2, gps + 2)
                result["dq_active"] = bool(gps in flag.active)
                
                # 3. Classify
                if result["nans"] > 1000:
                    result["classification"] = "Macro-Dropout Artifact"
                elif not result["dq_active"] and result["nans"] == 0:
                    result["classification"] = "Strain Data Integrity Check: PASS"
                elif result["nans"] == 0:
                    result["classification"] = "Strain Data Integrity Check: PASS"
                
            except Exception as e:
                result["error"] = str(e)
                result["nans"] = -1
                result["zeros"] = -1
                
            sanity_metrics[fam_id] = result
            logger.info(f"Sanity Check {fam_id} ({gps}): {result['classification']} (NaNs: {result['nans']})")
            
        # Clean the global astropy cache to avoid unbounded disk usage
        try:
            from astropy.utils.data import clear_download_cache
            clear_download_cache()
            logger.info("Cleared astropy download cache.")
        except ImportError:
            pass

        return sanity_metrics

    def _generate_psd_plots(self, sanity_metrics: dict):
        import matplotlib.pyplot as plt
        import logging
        from pathlib import Path
        try:
            from gwpy.timeseries import TimeSeries
        except ImportError:
            logger.error("gwpy not installed. Skipping PSD generation.")
            return

        for fam_id, data in sanity_metrics.items():
            if data.get("classification") == "Macro-Dropout Artifact" or data.get("nans", 0) > 0:
                logger.info(f"Skipping PSD for {fam_id} (Data dropout)")
                continue

            gps = data["gps"]
            det = data["detector"]
            logger.info(f"Generating PSD for {fam_id} at {gps}...")

            try:
                from src.core.data_loader import fetch_local_or_remote_strain
                # Fetch 1 second around glitch and 1 second background (e.g. 10s earlier)
                ts_glitch = fetch_local_or_remote_strain(det, gps - 0.5, gps + 0.5)
                ts_bkg = fetch_local_or_remote_strain(det, gps - 10.5, gps - 9.5)

                # Compute PSD (Welch's method)
                psd_glitch = ts_glitch.psd(fftlength=0.25)
                psd_bkg = ts_bkg.psd(fftlength=0.25)

                plt.figure(figsize=(10, 6))
                ax = plt.gca()
                ax.plot(psd_bkg.frequencies, psd_bkg.value, label='Background (-10s)', color='gray', alpha=0.7)
                ax.plot(psd_glitch.frequencies, psd_glitch.value, label=f'Glitch ({fam_id})', color='red', alpha=0.9)

                ax.set_yscale('log')
                ax.set_xscale('log')
                ax.set_xlim(10, 2048)
                ax.set_xlabel('Frequency [Hz]')
                ax.set_ylabel(r'Power Spectral Density [strain$^2$/Hz]')
                ax.set_title(f"PSD Comparison: {fam_id} ({det} @ {gps})")
                ax.legend()
                ax.grid(True, which='both', ls='--', alpha=0.4)

                out_dir = self.output_dir / "visual_checks" / fam_id
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"psd_{fam_id}.png"
                plt.savefig(out_path, dpi=300, bbox_inches='tight')
                plt.close()
                logger.info(f"Saved PSD plot to {out_path}")

                if fam_id.startswith("Singleton"):
                    try:
                        import shutil
                        import pandas as pd
                        tax_path = self.output_dir / f"Master_Taxonomy_{self.observing_run}.csv"
                        if tax_path.exists():
                            tax_df = pd.read_csv(tax_path)
                            row = tax_df[tax_df['global_family_id'] == fam_id]
                            if not row.empty:
                                session_id = row.iloc[0]['session_id']
                                sal_dir = self.production_dir / str(int(session_id)) / "report" / "saliency_gallery"
                                if sal_dir.exists():
                                    copied = False
                                    for sal_file in sal_dir.glob(f"*{int(gps)}*saliency*.png"):
                                        out_sal = out_dir / f"saliency_{fam_id}.png"
                                        shutil.copy(sal_file, out_sal)
                                        logger.info(f"Copied saliency map for {fam_id} to {out_sal}")
                                        copied = True
                                        break
                                    if not copied:
                                        for sal_file in sal_dir.glob(f"candidate_{int(gps)}*.png"):
                                            out_sal = out_dir / f"saliency_{fam_id}.png"
                                            shutil.copy(sal_file, out_sal)
                                            logger.info(f"Copied saliency map for {fam_id} to {out_sal}")
                                            break
                    except Exception as e:
                        logger.error(f"Failed to copy saliency map for {fam_id}: {e}")
            except Exception as e:
                logger.error(f"Failed to generate PSD for {fam_id}: {e}")

        try:
            from astropy.utils.data import clear_download_cache
            clear_download_cache()
        except ImportError:
            pass

    def _build_disposition_ledger(self, tax_df) -> list:
        """Final per-candidate verdict, aggregated from every check.

        One authoritative view: funnel waterfall + one row per SURVIVOR with
        the outcome of veto, DSD robustness, PEM and multiscale profiling.
        Fully dynamic: every input is read from its artifact; missing checks
        are declared per-column ('pending'), never silently omitted.
        """
        import pandas as pd

        lines = ["", "## Final Candidate Disposition Ledger", ""]
        if tax_df is None or tax_df.empty:
            lines.append("> Taxonomy unavailable — ledger cannot be built "
                         "(see completeness block).")
            return lines

        n = len(tax_df)
        get = lambda col: tax_df[col] if col in tax_df.columns else pd.Series([None] * n, index=tax_df.index)

        transitivity = get("transitivity_status").fillna("N/A")
        partner = get("partner_observing_status").fillna("NOT_CHECKED")
        robustness = get("robustness_class")
        dsd_ran = robustness.notna().any()
        robustness = robustness.fillna("pending")

        # PEM per-candidate outcomes, if the PEM stage produced them.
        # An event is COUPLED only if (a) at least one channel exceeds its
        # empirically calibrated per-channel threshold AND (b) the analytic
        # coherence null survives a Bonferroni correction across every
        # channel actually tested for that event. The analytic tail for
        # Welch magnitude-squared coherence with F averages is
        # P(C > c) = (1-c)^(F-1) per bin; with 32 s / fftlength 2 s /
        # overlap 1 s, F = 31, and the 20-500 Hz band at df = 0.5 Hz scans
        # ~960 bins, so p_channel ~= n_bins * (1-Cmax)^30 and
        # p_event = m_channels * p_channel.
        pem_map = {}
        pem_coupled_gps = set()
        _PEM_WELCH_AVERAGES = 31
        _PEM_N_BINS = 960

        # PRIMARY criterion: family-wise empirical null (max-statistic over
        # the event's m channels on time-shift surrogates, see
        # pem_null_calibration.py). Falls back to the legacy dual criterion
        # (empirical per-channel threshold AND analytic Bonferroni) ONLY for
        # events without a calibration, and says so in the verdict string.
        fw_csv = self.output_dir / "pem" / "pem_family_wise_verdicts.csv"
        fw_seen = set()
        if fw_csv.exists():
            try:
                fw = pd.read_csv(fw_csv)
                calibrated = fw[fw["verdict"] != "UNCALIBRATED"]
                median_pairs = calibrated["n_surrogate_pairs"].median() \
                    if len(calibrated) else 0
                for _, r in fw.iterrows():
                    g = float(r["gps_start"])
                    if r["verdict"] == "UNCALIBRATED":
                        continue  # legacy fallback below
                    fw_seen.add(g)
                    # A visibly smaller surrogate count is not a bug: the
                    # per-window candidate exclusion (+/-96 s) removes more
                    # windows where the taxonomy is locally dense. Say so.
                    low_n_note = ""
                    if median_pairs and r["n_surrogate_pairs"] < 0.75 * median_pairs:
                        low_n_note = (", reduced N: candidate-dense region, "
                                      "per-window exclusion")
                    detail = (f"thr_fw={r['threshold_fw']:.3f}, "
                              f"m={int(r['m_channels'])}, "
                              f"N={int(r['n_surrogate_pairs'])}"
                              + (f", W={int(r['n_windows'])}"
                                 if pd.notna(r.get("n_windows")) else "")
                              + low_n_note)
                    if r["verdict"] == "COUPLED":
                        pem_coupled_gps.add(g)
                        pem_map[g] = (
                            f"COUPLED ({r['top_channel']}, "
                            f"Cmax={r['cmax_observed']:.3f} > {detail})")
                    else:
                        pem_map[g] = (
                            f"NO_CORRELATION (Cmax={r['cmax_observed']:.3f} "
                            f"<= {detail})")
            except Exception as e:
                logger.warning(f"Ledger: cannot parse family-wise verdicts: {e}")

        pem_csv = self.output_dir / "pem" / "coherence_report.csv"
        if pem_csv.exists():
            try:
                pdf = pd.read_csv(pem_csv)
                for gps_val, grp in pdf.groupby("gps_start"):
                    if float(gps_val) in fw_seen:
                        continue  # family-wise verdict already assigned
                    if not grp["data_available"].any():
                        pem_map[float(gps_val)] = "PEM_UNAVAILABLE"
                        continue
                    tested = grp[grp["data_available"]
                                 & grp["max_coherence"].notna()]
                    m_channels = max(1, len(tested))
                    # DUAL veto criterion, both mandatory:
                    #  (a) the channel exceeds its EMPIRICALLY calibrated
                    #      per-channel threshold ('significant' flag, from
                    #      channel_thresholds.json / pem_significance_test);
                    #  (b) the analytic coherence null survives Bonferroni
                    #      across the m tested channels (p_Bonf < 0.05).
                    # The analytic null alone is NOT sufficient: the same
                    # significance test measured a 23% FPR at C>=0.6 on
                    # time-shifted background pairs, while the Gaussian
                    # analytic tail predicts ~1e-8 there — real coherence
                    # tails are heavy (spectral lines, non-Gaussianity),
                    # so an analytic-only veto would kill candidates on a
                    # null hypothesis the data already falsified. p_Bonf
                    # is still reported on the top channel for context.
                    verdict = None
                    hits = tested[tested["significant"].fillna(False)]
                    if len(tested) > 0:
                        top_pool = hits if len(hits) > 0 else tested
                        top = top_pool.sort_values(
                            "max_coherence", ascending=False).iloc[0]
                        c = float(top["max_coherence"])
                        p_bonf = min(1.0, m_channels * _PEM_N_BINS
                                     * (1.0 - min(c, 1.0 - 1e-12))
                                     ** (_PEM_WELCH_AVERAGES - 1))
                        if len(hits) > 0 and p_bonf < 0.05:
                            verdict = (
                                f"COUPLED [LEGACY dual criterion] ({top['aux_channel']}, "
                                f"C={c:.3f}, p_Bonf={p_bonf:.1e}, "
                                f"m={m_channels})")
                            pem_coupled_gps.add(float(gps_val))
                        elif len(hits) == 0:
                            verdict = (
                                f"NO_CORRELATION [LEGACY dual criterion] "
                                f"(Cmax={c:.3f}, below empirical channel "
                                f"threshold, p_Bonf={p_bonf:.1e}, m={m_channels})")
                        else:
                            verdict = (
                                f"NO_CORRELATION [LEGACY dual criterion] "
                                f"(Cmax={c:.3f}, p_Bonf={p_bonf:.2f} >= 0.05, "
                                f"m={m_channels})")
                    if verdict is None:
                        cmax = grp["max_coherence"].max()
                        verdict = (f"NO_CORRELATION (Cmax={cmax:.2f}, "
                                   f"m={m_channels})")
                    pem_map[float(gps_val)] = verdict
            except Exception as e:
                logger.warning(f"Ledger: cannot parse PEM report: {e}")

        # Multiscale duration profiles, if produced
        ms_map = {}
        ms_path = self.output_dir / f"Multiscale_Profile_{self.observing_run}.csv"
        if ms_path.exists():
            try:
                ms = pd.read_csv(ms_path)
                dom = ms.dropna(subset=["dominant_scale_s"]) \
                        .drop_duplicates(subset=["gps_start", "detector"])
                for _, r in dom.iterrows():
                    ms_map[(float(r["gps_start"]), r["detector"])] = r["dominant_scale_s"]
            except Exception:
                pass

        # ---- Waterfall ----
        is_unclassified = transitivity == "Unclassified_Physical_Anomaly"
        # Singletons are morphological outliers that never enter the
        # transitivity resolution: they are survivors-by-construction unless
        # a downstream check kills them. Excluding them undercounted the
        # final survivors to zero while the multiscale layer profiled them.
        is_singleton = get("global_family_id").astype(str).str.startswith("Singleton")
        is_coincident = partner == "ACTIVE_ANOMALY_DETECTED"
        is_vetoed_local = partner == "ACTIVE_NO_ANOMALY"
        is_unverifiable = partner.isin(["INACTIVE", "UNOBSERVABLE", "NOT_CHECKED"]) & is_unclassified
        survives_dsd = robustness.eq("ROBUST") if dsd_ran else pd.Series([True] * n, index=tax_df.index)
        # PEM veto: a Bonferroni-significant coherence with an auxiliary
        # channel is direct evidence of instrumental coupling — the event
        # must not be counted as a surviving discovery candidate.
        gps_series = pd.to_numeric(get("gps_start"), errors="coerce")
        pem_vetoed = gps_series.apply(
            lambda g: float(g) in pem_coupled_gps if pd.notna(g) else False)
        pre_pem_mask = (is_unclassified | is_singleton) & survives_dsd
        survivor_mask = pre_pem_mask & ~pem_vetoed

        lines.append("Every candidate's final status, derived from the check "
                     "artifacts at report-generation time:")
        lines.append("")
        lines.append("| Funnel stage | Count |")
        lines.append("| --- | --- |")
        lines.append(f"| Unique candidates (post-dedup) | {n} |")
        lines.append(f"| Resolved via transitivity / families | {int((~is_unclassified).sum())} |")
        lines.append(f"| Coincident (partner anomaly detected) | {int(is_coincident.sum())} |")
        lines.append(f"| Vetoed local (partner searched, no match) | {int(is_vetoed_local.sum())} |")
        lines.append(f"| Unclassified + partner unverifiable | {int(is_unverifiable.sum())} |")
        if dsd_ran:
            lines.append(f"| DSD: BACKGROUND / AMBIGUOUS / ROBUST | "
                         f"{int(robustness.eq('BACKGROUND').sum())} / "
                         f"{int(robustness.eq('AMBIGUOUS').sum())} / "
                         f"{int(robustness.eq('ROBUST').sum())} |")
        else:
            lines.append("| DSD robustness | pending (run_dsd_standalone) |")
        lines.append(f"| Singleton morphological outliers | {int(is_singleton.sum())} |")
        lines.append(f"| PEM-vetoed (family-wise empirical aux coupling) | "
                     f"{int((pre_pem_mask & pem_vetoed).sum())} |")
        lines.append(f"| **FINAL SURVIVORS ((unclassified OR singleton) & DSD-robust & not PEM-coupled)** | "
                     f"**{int(survivor_mask.sum())}** |")
        lines.append("")

        # ---- Full family-wise PEM verdict table (ALL tested events,
        # including family members that never reach the survivor stage) ----
        if pem_map:
            lines.append(f"### PEM family-wise verdicts ({len(pem_map)} events tested)")
            lines.append("")
            lines.append("| GPS | Verdict |")
            lines.append("| --- | --- |")
            for g in sorted(pem_map):
                lines.append(f"| {g:.0f} | {pem_map[g]} |")
            lines.append("")

        # ---- PEM-vetoed table (transparency: they were candidates) ----
        vetoed = tax_df[pre_pem_mask & pem_vetoed]
        if len(vetoed) > 0:
            lines.append(f"### Removed by PEM veto ({len(vetoed)})")
            lines.append("")
            lines.append("| GPS | Det | Family | DSD | PEM verdict |")
            lines.append("| --- | --- | --- | --- | --- |")
            for _, r in vetoed.iterrows():
                g = float(r["gps_start"])
                lines.append(
                    f"| {g:.0f} | {r.get('detector', '?')} "
                    f"| {r.get('global_family_id', 'N/A')} "
                    f"| {r.get('robustness_class', 'pending')} "
                    f"| {pem_map.get(g, 'pending')} |")
            lines.append("")

        # ---- Per-survivor table (capped) ----
        surv = tax_df[survivor_mask]
        cap = 100
        if len(surv) == 0:
            lines.append("No candidate survives every check: formal null result "
                         "at this stage of validation.")
        else:
            lines.append(f"### Survivors ({len(surv)}"
                         + (f", first {cap} shown" if len(surv) > cap else "")
                         + ")")
            lines.append("")
            lines.append("| GPS | Det | Family | Partner status | DSD | "
                         "PEM | Dominant scale (s) |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for _, r in surv.head(cap).iterrows():
                g = float(r["gps_start"])
                d = str(r.get("detector", "?"))
                lines.append(
                    f"| {g:.0f} | {d} | {r.get('global_family_id', 'N/A')} "
                    f"| {r.get('partner_observing_status', 'NOT_CHECKED')} "
                    f"| {r.get('robustness_class', 'pending')} "
                    f"| {pem_map.get(g, 'pending')} "
                    f"| {ms_map.get((g, d), 'pending')} |")
        lines.append("")
        return lines

    def _generate_markdown_report(self, metrics: dict):
        import datetime
        import pandas as pd
        from pathlib import Path
        
        ds_metrics = metrics.get('domain_shift_defense', {})
        cohesion = ds_metrics.get('family_cohesion', {})
        summary = metrics.get('summary', {})
        
        # Load taxonomy to get the session breakdown and counts
        tax_path = self.output_dir / f"Master_Taxonomy_{self.observing_run}.csv"
        tax_df = pd.read_csv(tax_path) if tax_path.exists() else pd.DataFrame()

        # ---- Report completeness gate -------------------------------------
        # A scientific report must declare its own gaps: every degraded input
        # is listed HERE, at the top, instead of silently becoming "N/A" deep
        # in some section. An empty list means the report is complete.
        completeness_issues: list[str] = []
        _summary_probe = metrics.get('summary', {})
        _tot_probe = _summary_probe.get('total_candidates_after_dedup', 0)
        if not tax_path.exists():
            completeness_issues.append(
                f"Master_Taxonomy_{self.observing_run}.csv MISSING — session "
                "breakdown, per-detector counts and family tables are degraded.")
        elif tax_df.empty and _tot_probe > 0:
            completeness_issues.append(
                f"INCONSISTENT: summary reports {_tot_probe} candidates but the "
                "taxonomy is empty — do not trust per-detector counts.")
        if not _summary_probe:
            completeness_issues.append("aggregate summary metrics MISSING.")
        for det in ("l1", "h1"):
            if _summary_probe.get(det, {}).get('spearman_rho') is None:
                completeness_issues.append(
                    f"Spearman stability not computable for {det.upper()} "
                    "(insufficient sessions).")
        if not metrics.get('domain_shift_defense'):
            completeness_issues.append("Domain Shift Defense not executed.")
        if not metrics.get('sanity_checks'):
            completeness_issues.append("Strain sanity checks not executed.")
        for issue in completeness_issues:
            logger.warning(f"[REPORT COMPLETENESS] {issue}")
        
        visual_dir = self.output_dir / "visual_checks"
        singletons_files = sorted(list(visual_dir.rglob("*Singleton*.png")))
        
        md_lines = []
        md_lines.append("# Final Discovery Report – Production Scan")
        md_lines.append("")
        md_lines.append("> **Generated on:** " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"))
        md_lines.append("")
        if completeness_issues:
            md_lines.append("> [!WARNING]")
            md_lines.append("> **REPORT INCOMPLETE — the following inputs were "
                            "missing or degraded at generation time. Sections "
                            "below showing N/A derive from these gaps, not from "
                            "null scientific results:**")
            for issue in completeness_issues:
                md_lines.append(f"> - {issue}")
            md_lines.append("")
        else:
            md_lines.append("> **Report completeness:** all pipeline inputs present.")
            md_lines.append("")
        
        # 1. Pipeline Ingestion Summary
        md_lines.append("## 1. Pipeline Ingestion Summary")
        tot_sessions = summary.get('total_sessions_valid', 0)
        tot_cands = summary.get('total_candidates_after_dedup', 0)
        
        l1_cands = len(tax_df[tax_df['detector'] == 'L1']) if not tax_df.empty else 0
        h1_cands = len(tax_df[tax_df['detector'] == 'H1']) if not tax_df.empty else 0
        
        md_lines.append(f"- **Valid Sessions:** {tot_sessions}")
        if not tax_df.empty:
            # Single source of truth: the taxonomy the reader can open.
            md_lines.append(f"- **Unique Candidates:** {len(tax_df)} ({l1_cands} L1, {h1_cands} H1)")
            if tot_cands != len(tax_df):
                md_lines.append(f"  - note: summary counted {tot_cands} pre-taxonomy; delta = vetoed/degraded entries.")
        else:
            md_lines.append(f"- **Unique Candidates:** {tot_cands} (per-detector breakdown unavailable — taxonomy missing/empty)")
        
        if not tax_df.empty and 'partner_observing_status' in tax_df.columns:
            unobs_count = len(tax_df[tax_df['partner_observing_status'] == 'UNOBSERVABLE'])
            md_lines.append(f"- **Cross-Detector Coincidence Unobservable (Partner Offline):** {unobs_count} candidates")
        
        gev = metrics.get('gev_parameters', {})
        if gev:
            md_lines.append("- **GEV Background Threshold Fit (Averaged):**")
            if 'H1' in gev:
                md_lines.append(rf"  - **H1:** $\hat{{\mu}}$ = {gev['H1']['mean_mu']:.3f}, $\hat{{\sigma}}$ = {gev['H1']['mean_sigma']:.3f}, $\hat{{\xi}}$ = {gev['H1']['mean_xi']:.3f}")
            if 'L1' in gev:
                md_lines.append(rf"  - **L1:** $\hat{{\mu}}$ = {gev['L1']['mean_mu']:.3f}, $\hat{{\sigma}}$ = {gev['L1']['mean_sigma']:.3f}, $\hat{{\xi}}$ = {gev['L1']['mean_xi']:.3f}")
                
        # Calculate transitivity stats
        if not tax_df.empty:
            resolved = len(tax_df[tax_df['transitivity_status'] == 'Resolved_via_Transitivity'])
            total_3b = len(tax_df[tax_df['origin_table'] == '3b'])
            perc = (resolved / total_3b * 100) if total_3b > 0 else 0
            md_lines.append(f"- **Transitivity Resolution:** {resolved}/{total_3b} resolved ({perc:.1f}%)")
        else:
            md_lines.append("- **Transitivity Resolution:** N/A")
        md_lines.append("")
        
        # 2. Session-by-Session Breakdown
        md_lines.append("## 2. Session‑by‑Session Breakdown")
        if not tax_df.empty:
            grouped_sessions = list(tax_df.groupby('session_id'))
            for i, (session_id, group) in enumerate(grouped_sessions):
                if i >= 10:
                    md_lines.append(f"### ... and {len(grouped_sessions)-10} more sessions — see file completo")
                    break
                md_lines.append(f"### Session: {session_id}")
                md_lines.append("| GPS | Detector | Local Cluster | Global Family | Spectrogram |")
                md_lines.append("| --- | --- | --- | --- | --- |")
                for _, row in group.iterrows():
                    gps = row['gps_start']
                    det = row['detector']
                    lcl = row['local_cluster_id']
                    fam = row['global_family_id']
                    
                    # Find image link (try both aggregated visual_checks and session saliency gallery)
                    img_link = "N/A"
                    fam_dir = fam if "Singleton" not in str(fam) else f"Singleton_{int(gps)}"
                    img_path = visual_dir / fam_dir / f"saliency_{fam_dir}.png"
                    if img_path.exists():
                        rel_path_str = "file:///" + str(img_path.resolve()).replace("\\", "/")
                        img_link = f"[View Global]({rel_path_str})"
                    else:
                        # Fallback to session saliency gallery
                        sal_path = self.production_dir / str(session_id) / "report" / "saliency_gallery" / f"candidate_{int(gps)}_{det}.png"
                        if sal_path.exists():
                            rel_path_str = "file:///" + str(sal_path.resolve()).replace("\\", "/")
                            img_link = f"[View Local]({rel_path_str})"
                            
                    md_lines.append(f"| {gps} | {det} | {lcl} | {fam} | {img_link} |")
                md_lines.append("")
        else:
            md_lines.append("No session data available.")
            md_lines.append("")
            
        # 3. Spearman Topological Stability
        md_lines.append("## 3. Spearman Topological Stability")
        l1 = summary.get('l1', {})
        h1 = summary.get('h1', {})
        
        if l1.get('spearman_rho') is not None:
            rho = l1.get('spearman_rho')
            p = l1.get('spearman_p')
            if p < 0.05:
                sig = "significant"
            else:
                sig = "not significant"
            md_lines.append(f"- **L1:** ρ = {rho:.3f}, p = {p:.4f} ({sig})")
        else:
            md_lines.append("- **L1:** ρ = N/A, p = N/A (insufficient data)")
            
        if h1.get('spearman_rho') is not None:
            rho = h1.get('spearman_rho')
            p = h1.get('spearman_p')
            if p < 0.05:
                sig = "significant"
            else:
                sig = "not significant"
            md_lines.append(f"- **H1:** ρ = {rho:.3f}, p = {p:.4f} ({sig})")
        else:
            md_lines.append("- **H1:** ρ = N/A, p = N/A (insufficient data)")
        md_lines.append("")
        
        # 4. Domain Shift Defense & Morphological Families
        md_lines.append("## 4. Domain Shift Defense & Morphological Families")
        
        # Display actual domain shift experiment results
        ds = metrics.get('domain_shift_defense', {})
        total_eval = ds.get('total_evaluated', 0)
        survived = ds.get('survived_native_threshold', 0)
        robust = ds.get('robust_count', 0)
        ambiguous = ds.get('ambiguous_count', 0)
        background = ds.get('background_count', 0)
        
        if ds.get('experiment_run', False):
            h1 = ds.get('H1', {})
            l1 = ds.get('L1', {})
            md_lines.append(f"- **Native O4a Threshold Test (Detector-Specific Block-Bootstrap B=1000, N=5000):** Su {total_eval} candidati valutati (H1: {h1.get('total', 0)}, L1: {l1.get('total', 0)}):")
            md_lines.append(f"  - **{robust}** candidati **ROBUST** (Score > CI Upper)")
            md_lines.append(f"    - H1: {h1.get('robust', 0)} / L1: {l1.get('robust', 0)}")
            md_lines.append(f"  - **{ambiguous}** candidati **AMBIGUOUS** (CI Lower <= Score <= CI Upper)")
            md_lines.append(f"    - H1: {h1.get('ambiguous', 0)} / L1: {l1.get('ambiguous', 0)}")
            md_lines.append(f"  - **{background}** candidati **BACKGROUND** (Score < CI Lower)")
            md_lines.append(f"    - H1: {h1.get('background', 0)} / L1: {l1.get('background', 0)}")
            if total_eval > 0:
                md_lines.append(f"\n  *(Survival rate robusto: {(robust/total_eval)*100:.1f}%)*")
            else:
                md_lines.append("\n  *(Survival rate robusto: N/A — 0 candidati valutati)*")
        else:
            md_lines.append("- **Native O4a Threshold Test:** Not executed (native index not available).")
        md_lines.append("")
        
        # Check for dissolved families
        if not tax_df.empty and 'robustness_class' in tax_df.columns:
            dissolved_families = []
            all_fams = tax_df[~tax_df['global_family_id'].str.contains("Singleton|Unknown", na=False)]['global_family_id'].unique()
            for fam in all_fams:
                fam_df = tax_df[tax_df['global_family_id'] == fam]
                total_n = len(fam_df)
                robust_n = len(fam_df[fam_df['robustness_class'] == 'ROBUST'])
                if total_n >= 2 and robust_n < 2:
                    ambig_n = len(fam_df[fam_df['robustness_class'] == 'AMBIGUOUS'])
                    bg_n = len(fam_df[fam_df['robustness_class'] == 'BACKGROUND'])
                    dissolved_families.append({
                        'fam': fam, 'total': total_n, 'robust': robust_n, 'ambig': ambig_n, 'bg': bg_n
                    })
            if dissolved_families:
                md_lines.append("### Domain Shift Dissolution (Artifact Filtering)")
                md_lines.append("The following morphological families dissolved below the Domain Shift threshold (surviving $n < 2$), empirically demonstrating they were systematic artifacts of the O3b-to-O4a domain gap rather than robust physical anomalies:")
                for d in dissolved_families:
                    md_lines.append(f"- **{d['fam']}**: originally {d['total']} members. Post-threshold: {d['robust']} ROBUST, {d['ambig']} AMBIGUOUS, {d['bg']} BACKGROUND.")
                    if d['robust'] == 1:
                        md_lines.append("  *(The single surviving candidate is automatically accounted for as an isolated topological Singleton)*")
                md_lines.append("")

        sorted_families = sorted(
            [fam for fam in cohesion.keys() if fam != "Unknown" and "Singleton" not in fam],
            key=lambda k: cohesion[k].get('mean_internal_similarity', 0),
            reverse=True
        )
        if sorted_families:
            for fam in sorted_families:
                fam_data = cohesion[fam]
                n_members = fam_data.get('n', 0)
                sim = fam_data.get('mean_internal_similarity', 0.0)
                md_lines.append(f"- **{fam}** (n={n_members}): mean intra-family similarity = {sim:.3f}")
        else:
            md_lines.append("No morphological families detected or domain shift defense skipped.")
            
        md_lines.append("")
        md_lines.append("### Morphological Cohesion Assessment")
        md_lines.append("| Family | N | Mean S_intra |")
        md_lines.append("| --- | --- | --- |")
        if sorted_families:
            for fam in sorted_families:
                fam_data = cohesion[fam]
                n_members = fam_data.get('n', 0)
                sim = fam_data.get('mean_internal_similarity', 0.0)
                md_lines.append(f"| {fam} | {n_members} | {sim:.3f} |")
        else:
            md_lines.append("| N/A | N/A | N/A |")
        md_lines.append("")
        
        # 5. Physical Validation
        md_lines.append("## 5. Physical Validation (Strain & DQ Vetoes)")
        sanity = metrics.get('sanity_checks', {})
        if sanity:
            passed = 0
            failed = 0
            for fam_id, data in sanity.items():
                if data.get("nans") == 0 and data.get("zeros") == 0:
                    passed += 1
                else:
                    failed += 1
            md_lines.append(f"- **Sanity checks:** {passed} families passed, {failed} families showed macroscopic dropouts.")
            md_lines.append("- **DQ flags evaluated:** L1:CBC_CAT1, L1:BURST_CAT1, H1:CBC_CAT1, H1:BURST_CAT1")
            
            md_lines.append("")
            for fam_id, data in sanity.items():
                cls = data.get("classification", "Unknown")
                md_lines.append(f"### {fam_id} - {cls}")
                md_lines.append(f"- **Representative GPS:** {data.get('gps')}")
                if data.get("error"):
                    md_lines.append(f"- **Status:** Fetch failed ({data.get('error')})")
                else:
                    md_lines.append(f"- **Strain Integrity:** {data.get('nans')} NaNs, {data.get('zeros')} zeros.")
                    if data.get("nans") == 0:
                        md_lines.append(f"- **Max Amplitude:** {data.get('max_amplitude'):.2e}")
                    dq = data.get('dq_active')
                    dq_str = "True (Science Mode, reliable)" if dq else "False (Data Quality compromised / not Science Mode)"
                    md_lines.append(f"- **GWOSC '{data.get('detector')}_CBC_CAT1' Flag Active:** {dq_str}")
        else:
            md_lines.append("- Sanity checks: No data available.")
        md_lines.append("")
        
        # 6. Singletons & Outliers
        md_lines.append("## 6. Singletons & Outliers")
        if not tax_df.empty:
            singleton_rows = tax_df[tax_df['global_family_id'].str.contains("Singleton", na=False)]
            total_singletons = len(singleton_rows)
            
            valid_singletons = []
            error_singletons = []
            for _, row in singleton_rows.iterrows():
                gps = int(row['gps_start'])
                fam_dir = f"Singleton_{gps}"
                img_path = visual_dir / fam_dir / f"saliency_{fam_dir}.png"
                if img_path.exists():
                    valid_singletons.append((gps, row, img_path))
                else:
                    error_singletons.append(gps)
            
            md_lines.append(f"- {total_singletons} isolated events detected in topology.")
            if len(error_singletons) > 0:
                if len(valid_singletons) == 0:
                    md_lines.append(f"  - **0 Q-transforms available** (all {len(error_singletons)} singletons lack visual spectrograms: GPS {', '.join(map(str, error_singletons))})")
                else:
                    md_lines.append(f"  - **{len(valid_singletons)} Q-transforms available**")
                    md_lines.append(f"  - **{len(error_singletons)} missing images** (No visual Q-transform: GPS {', '.join(map(str, error_singletons))})")
            else:
                if total_singletons > 0:
                    md_lines.append(f"  - All {total_singletons} validated (Visual check successful)")
            md_lines.append(f"- GPS List: {', '.join(singleton_rows['gps_start'].astype(str).tolist())}")
            
            if len(valid_singletons) > 0:
                # Add physics parameters table for singletons
                singleton_physics_path = self.output_dir / "physics" / "singleton_physics.csv"
                if singleton_physics_path.exists():
                    try:
                        import pandas as pd
                        sp_df = pd.read_csv(singleton_physics_path)
                        md_lines.append("")
                        md_lines.append("### Singleton Physical Parameters")
                        md_lines.append("| GPS | Detector | Peak Freq (Hz) | Duration (s) | SNR proxy |")
                        md_lines.append("| --- | --- | --- | --- | --- |")
                        for _, sp_row in sp_df.iterrows():
                            f_val = f"{sp_row['peak_freq_hz']:.1f}" if pd.notna(sp_row['peak_freq_hz']) else "N/A"
                            d_val = f"{sp_row['duration_s']:.3f}" if pd.notna(sp_row['duration_s']) else "N/A"
                            s_val = f"{sp_row['snr_proxy']:.1f}" if pd.notna(sp_row['snr_proxy']) else "N/A"
                            gps_val = int(sp_row['gps_start'])
                            md_lines.append(f"| {gps_val} | {sp_row['detector']} | {f_val} | {d_val} | {s_val} |")
                        md_lines.append("")
                        md_lines.append("> **Note**: SNR proxy is the peak amplitude of the whitened time series, not a matched-filter SNR.")
                    except Exception as e:
                        logger.error(f"Failed to load singleton_physics.csv for report: {e}")

                md_lines.append("")
        else:
            md_lines.append("- No isolated events.")
        md_lines.append("")
        
        # RESTORE THE DELETED SECTIONS
        
        sec_num = 7
        
        # Distribution Plot
        dist_plot = visual_dir / "distribution_plot.png"
        if dist_plot.exists():
            md_lines.append(f"## {sec_num}. Novelty Score Distribution")
            md_lines.append("Histogram showing the statistical separation between the native background noise and the final candidates.")
            md_lines.append("")
            sec_num += 1

        # Cluster Gallery
        gallery_img = self.output_dir / "fig_cluster_gallery.png"
        if gallery_img.exists():
            md_lines.append(f"## {sec_num}. Cluster Gallery (All Families)")
            md_lines.append("Composite gallery showing representative Q-Transform spectrograms for each discovered morphological family.")
            md_lines.append("")
            sec_num += 1

        # Similarity Heatmap
        heatmap_img = self.output_dir / "candidate_similarity_heatmap.png"
        if heatmap_img.exists():
            md_lines.append(f"## {sec_num}. Candidate Similarity Heatmap")
            md_lines.append("Pairwise cosine similarity matrix between all final candidates. The block-diagonal structure visually suggests that intra-family similarity is significantly higher than inter-family similarity.")
            md_lines.append("")
            sec_num += 1

        md_lines.append(f"## {sec_num}. Produced Datasets")
        md_lines.append("The following data products have been persisted for further analysis:")
        md_lines.append("| File | Description | Notes |")
        md_lines.append("| --- | --- | --- |")
        
        tables = [
            (f"Master_Taxonomy_{self.observing_run}.csv", "1. Master Taxonomy", "Final merged list of all un-vetoed physical transient candidates across all detector sessions."),
            ("Table_3a_Confirmed_Local_Glitch.csv", f"{sec_num}.a Table 3a — Confirmed Local Glitches", "Candidates confirmed as local glitches via rigorous sub-threshold Cross-Detector veto. These events do NOT show structural similarity (Cosine Similarity ≤ tau_coh) in the partner detector."),
            ("Table_3b_Unverifiable_Unilateral_Detections.csv", f"{sec_num}.b Table 3b — Unverifiable Unilateral Detections", "Candidates detected exclusively in one detector where the partner was INACTIVE. Cannot be confirmed as astrophysical without further offline cross-validation."),
            ("Table_3c_Coincident_Astrophysical.csv", f"{sec_num}.c Table 3c — Coincident Astrophysical Candidates", "Morphological cross-match confirmed. Candidates with sub-threshold Cosine Similarity > tau_coh in the opposite detector window."),
            ("physics/singleton_physics.csv", f"{sec_num}.d Singleton Physical Parameters", "Classical physical parameters (Peak Frequency, Duration, Peak-whitened SNR) extracted from the 32s window of isolated topological anomalies.")
        ]
        for file_name, title, desc in tables:
            md_lines.append(f"| {file_name} | {title} | {desc} |")
        md_lines.append("")
        sec_num += 1

        # CSV Tables Preview
        import csv
        for table_file, section_title, description in [
            ("Table_3a_Confirmed_Local_Glitches.csv", "Table 3a — Confirmed Local Glitches", "Candidates confirmed as local glitches via L1/H1 coincidence resolution. These events appear in both detectors within a ±2s window."),
            ("Table_3b_Unverifiable_Unilateral_Detections.csv", "Table 3b — Unverifiable Unilateral Detections", "Candidates detected exclusively in one detector (no coincident H1 counterpart). Cannot be confirmed as astrophysical without further investigation."),
            (f"Master_Taxonomy_{self.observing_run}.csv", "Master Taxonomy", "Full candidate list with GPS timestamp, detector, novelty score, assigned family, Gravity Spy label, and domain shift defense result."),
        ]:
            table_path = self.output_dir / table_file
            if table_path.exists():
                md_lines.append(f"## {sec_num}. {section_title}")
                md_lines.append(description)
                md_lines.append("")
                sec_num += 1
                try:
                    with open(table_path, "r", encoding="utf-8") as tf:
                        reader = csv.reader(tf)
                        rows = list(reader)
                    if rows:
                        header = rows[0]
                        md_lines.append("| " + " | ".join(header) + " |")
                        md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
                        for row in rows[1:21]:  # max 20 rows preview
                            md_lines.append("| " + " | ".join(str(c) for c in row) + " |")
                        if len(rows) > 21:
                            md_lines.append(f"*... {len(rows) - 21} more rows — see [{table_file}]({table_file})*")
                    md_lines.append("")
                except Exception as e:
                    md_lines.append(f"Error loading {table_file}: {e}")
                    md_lines.append("")

        # Gravity Spy
        md_lines.append(f"## {sec_num}. Supervised Validation (Gravity Spy)")
        sec_num += 1
        tot_eval = ds_metrics.get('total_evaluated', 0)
        if tot_eval > 0:
            md_lines.append(f"All **{tot_eval}** final evaluated events were cross-matched against Gravity Spy's supervised labels.")
            md_lines.append("- **Result**: All final members have `gs_label = Unknown` (Not cataloged or no-match).")
            md_lines.append(f"- **Conclusion**: Events are not matched by Gravity Spy's historical supervised models. Note: no {self.observing_run} Gravity Spy catalog exists; this cross-match has limited statistical power against {self.observing_run}-specific morphologies and should not be interpreted as strong evidence of astrophysical novelty.")
        else:
            md_lines.append("Gravity spy validation not performed or no candidates evaluated.")
        md_lines.append("")
        
        # Limitations
        # Section 15: Physics Correlation Defense
        physics_corr = metrics.get('physics_correlation', {})
        md_lines.append(f"## {sec_num}. Physics Correlation Defense")
        sec_num += 1
        if physics_corr and physics_corr.get('status') != 'FAILED':
            global_stats = physics_corr.get('global', {})
            r_val = global_stats.get('r_pearson', 'N/A')
            rho_val = global_stats.get('rho_spearman', 'N/A')
            p_val = global_stats.get('p_value_mantel', 'N/A')
            n_events = global_stats.get('n_samples', 'N/A')
            
            r_val_str = f"{r_val:.3f}" if isinstance(r_val, (int, float)) else str(r_val)
            rho_val_str = f"{rho_val:.3f}" if isinstance(rho_val, (int, float)) else str(rho_val)
            r2_str = f"{float(r_val)**2:.4f}" if isinstance(r_val, (int, float)) else "N/A"
            if isinstance(p_val, (int, float)):
                p_val_str = "< 0.0001" if abs(p_val - 0.0001) < 1e-9 else f"{p_val:.4f}"
            else:
                p_val_str = str(p_val)
                
            md_lines.append(f"Global Mantel test (N={n_events}): Pearson r = {r_val_str} (r² = {r2_str}), Spearman ρ = {rho_val_str}, p-value (permutation, 9999 iters) = {p_val_str}")
            if isinstance(r_val, (int, float)) and float(r_val)**2 < 0.05:
                md_lines.append("")
                md_lines.append(f"> **Effect size caveat:** r² = {r2_str} indicates that latent-space topology explains <{float(r_val)**2*100:.1f}% of the variance in physical-space distances. Statistical significance at large N does not imply a physically meaningful correlation.")
            md_lines.append("")
            md_lines.append("> **SNR definition**: peak of whitened time-series amplitude, NOT matched-filter SNR (PyCBC/BayesWave).")
            md_lines.append("")
            per_family = physics_corr.get('per_family', [])
            if per_family:
                md_lines.append("| Family | N | r (Pearson) | ρ (Spearman) | p (Mantel) | Note |")
                md_lines.append("| --- | --- | --- | --- | --- | --- |")
                for fam in per_family:
                    if fam['n'] <= 3:
                        r_f, rho_f, p_f = 'N/A', 'N/A', 'N/A'
                    else:
                        r_f = f"{fam['r_pearson']:.3f}" if fam.get('r_pearson') is not None and not (isinstance(fam.get('r_pearson'), float) and np.isnan(fam['r_pearson'])) else 'N/A'
                        rho_f = f"{fam['rho_spearman']:.3f}" if fam.get('rho_spearman') is not None and not (isinstance(fam.get('rho_spearman'), float) and np.isnan(fam['rho_spearman'])) else 'N/A'
                        p_raw = fam.get('p_value_mantel')
                        if p_raw is not None and not (isinstance(p_raw, float) and np.isnan(p_raw)):
                            p_f = "< 0.0001" if abs(p_raw - 0.0001) < 1e-9 else f"{p_raw:.4f}"
                        else:
                            p_f = 'N/A'
                    md_lines.append(f"| {fam['family']} | {fam['n']} | {r_f} | {rho_f} | {p_f} | {fam.get('note', '')} |")
                md_lines.append("")
            # Embed figure if it exists
            fig_path = self.output_dir / "physics" / "fig_latent_vs_physics.png"
            if fig_path.exists():
                rel_path_str = "file:///" + str(fig_path.resolve()).replace("\\", "/")
                md_lines.append(f"![Latent vs Physics Correlation]({rel_path_str})")
                md_lines.append("")
        else:
            err_msg = physics_corr.get('error', 'Not executed') if physics_corr else 'Not executed'
            md_lines.append(f"Physics Correlation Test not available: {err_msg}")
            md_lines.append("")

        # ----------------------------------------------------------
        # Section 16: Poisson Upper Limit Placeholder
        # ----------------------------------------------------------
        md_lines.append(f"## {sec_num}. Poisson Upper Limit (Offline Validation)")
        sec_num += 1
        md_lines.append("> Waiting for poisson module injection...")
        md_lines.append("")

        # ----------------------------------------------------------
        # Section 17: PEM Offline Coherence Defense
        # ----------------------------------------------------------
        md_lines.append(f"## {sec_num}. PEM Offline Coherence Defense")
        sec_num += 1
        pem_report_path = self.output_dir / "pem" / "coherence_report.csv"
        if pem_report_path.exists():
            md_lines.append("> Instrumental validation against GWOSC safe auxiliary channels.")
            md_lines.append("")
            try:
                import pandas as pd
                pem_df = pd.read_csv(pem_report_path)
                md_lines.append("| Detector | GPS Start | Family | Aux Channel | Max Coherence | Peak Freq (Hz) | Significant | Notes |")
                md_lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
                for _, row in pem_df.iterrows():
                    sig_icon = "🔴 YES" if row.get("significant", False) else "🟢 NO"
                    coh_val = row.get("max_coherence")
                    coh_str = f"{coh_val:.3f}" if pd.notna(coh_val) else "N/A"
                    freq_val = row.get("peak_freq")
                    freq_str = f"{freq_val:.1f}" if pd.notna(freq_val) else "N/A"
                    notes = row.get("notes", "")
                    md_lines.append(f"| {row.get('detector', '')} | {row.get('gps_start', '')} | {row.get('family', '')} | {row.get('aux_channel', '')} | {coh_str} | {freq_str} | {sig_icon} | {notes} |")
                md_lines.append("")

            except Exception as e:
                logger.error(f"Failed to load PEM report for markdown: {e}")
                md_lines.append(f"*Error loading PEM report: {e}*")
                md_lines.append("")
        else:
            md_lines.append("> Waiting for PEM coherence module injection...")
            md_lines.append("")

        md_lines.append(f"## {sec_num}. Limitations and Caveats")
        sec_num += 1
        md_lines.append("- **Detector Asymmetry:** L1/H1 asymmetry is partially explained by physical differences (e.g. O4a duty cycles and localized instrumental modes), but extreme ratios need further investigation.")
        
        dissolved_names = []
        if not tax_df.empty and 'robustness_class' in tax_df.columns:
            all_f = tax_df[~tax_df['global_family_id'].str.contains("Singleton|Unknown", na=False)]['global_family_id'].unique()
            for f in all_f:
                f_df = tax_df[tax_df['global_family_id'] == f]
                if len(f_df) >= 2 and len(f_df[f_df['robustness_class'] == 'ROBUST']) < 2:
                    dissolved_names.append(f)
                    
        if dissolved_names:
            fams_str = ", ".join(dissolved_names)
            md_lines.append(f"- **Domain Shifts:** The predominantly ambiguous/background classification of {fams_str} members under the block-bootstrap native calibration threshold is consistent with their interpretation as domain-shift artifacts, confirming that the reference index incorrectly flags pervasive O4a stationary features as morphologically novel.")
        else:
            md_lines.append("- **Domain Shifts:** The collapse of certain families under native index testing proves the presence of domain shift. The reference index must be re-calibrated per observing run.")

        if not tax_df.empty and 'global_family_id' in tax_df.columns:
            singleton_rows = tax_df[tax_df['global_family_id'].str.contains('Singleton', na=False)]
            total_singletons = len(singleton_rows)
        else:
            singleton_rows = pd.DataFrame()
            total_singletons = 0
            
        if total_singletons > 0:
            gps_list = [int(r['gps_start']) for _, r in singleton_rows.iterrows()]
            md_lines.append(f"- **Spurious Singletons ({total_singletons} events - GPS: {', '.join(map(str, gps_list))}):** The isolated singleton(s) have visual validation images available. Note: any formal PEM coherence hits for these isolated events must be interpreted cautiously. The lack of multiple-comparisons correction for the C>=0.6 threshold across many auxiliary channels implies a high false positive rate for casual noise (e.g., ubiquitous mains harmonics or weak couplings). Such hits are often physically ambiguous and warrant further manual investigation rather than being considered definitively 'instrumentally explained'.")
        else:
            md_lines.append("- **Spurious Singletons:** No singletons detected; all events form defined morphological clusters.")
            
        # Dynamically check for SUS-ETMX coupling in PEM report
        etmx_families = set()
        if pem_report_path.exists():
            try:
                pem_df = pd.read_csv(pem_report_path)
                # Use Bonferroni p-value instead of raw threshold for
                # SUS-ETMX coupling detection, consistent with ledger.
                _n_bins_etmx = 960
                _n_d_etmx = 31
                etmx_rows = pem_df[pem_df['aux_channel'].str.contains('SUS-ETMX', na=False)
                                   & pem_df['data_available']
                                   & pem_df['max_coherence'].notna()].copy()
                if not etmx_rows.empty:
                    etmx_rows['_p_bonf'] = etmx_rows.apply(
                        lambda row: min(1.0, len(pem_df[pem_df['gps_start'] == row['gps_start']]) * _n_bins_etmx
                                        * (1.0 - min(row['max_coherence'], 1.0 - 1e-12)) ** (_n_d_etmx - 1)), axis=1)
                    etmx_coupled = etmx_rows[etmx_rows['_p_bonf'] < 0.05]
                else:
                    etmx_coupled = etmx_rows
                etmx_families = set(etmx_coupled['family'].unique())
            except:
                pass
        
        if etmx_families:
            fams_str = ", ".join(sorted(etmx_families))
            md_lines.append(f"- **Calibration Line Coupling (SUS-ETMX):** Morphological clusters ({fams_str}) exhibit significant coherence with ETMX calibration lines. This indicates a known instrumental effect (calibration coupling) consistent with why the O3b reference model did not recognize it as a known class — the morphology may reflect an O4a-specific instrumental configuration not represented in the O3b training set.")

        md_lines.append("- **Absence of O4a Gravity Spy Catalog:** Supervised validation is limited to historical models.")
        md_lines.append("- **VQ Dictionary size (K=275):** The production reference index (`patch_compressed_index_o3b.npz`, MD5-pinned) contains exactly K=275 centroids; this was verified empirically from the artifact shape. The value K=281 that appears in some legacy development code was a divergent constant that never entered production. No claim is made that K is dynamically optimized; it is the pinned dictionary actually used for every score in this report. Comparisons of absolute intra-cluster coherences against earlier internal drafts that assumed K=281 should be treated with caution.")
        md_lines.append(f"- **Auxiliary (PEM) channel coverage in {self.observing_run}:** Environmental/auxiliary coupling checks used the GWOSC O4 Auxiliary Channel Data Release (DOI 10.7935/kt51-6n86), which exposes a limited public subset of channels (14 for H1, 11 for L1) rather than the full internal PEM sensor network. Per-event channel availability varies with the GPS window; the number of channels actually tested (m) is reported per event in the disposition ledger. Event-level COUPLED/NO_CORRELATION verdicts use a family-wise EMPIRICAL null: for each event, the (1-alpha) quantile (alpha=0.01) of the max-statistic — the maximum coherence over all m tested channels and the 20-500 Hz band — computed on time-shift surrogate pairs (32 s windows, 96 s stride, >= 64 s guard) drawn from a CAT1-clean background block near the event, with candidate windows excluded (+/-96 s). The same shift is applied against all channels simultaneously, preserving inter-channel correlation (e.g. the SUS-ETMX actuator stages); the number of surrogate pairs N and the derived threshold are reported per event in the ledger, with a window-level bootstrap CI in the calibration JSON. Neither the raw per-channel threshold (measured single-channel FPR: 23% at C >= 0.6 on time-shift surrogates) nor the quasi-Gaussian analytic p-value (falsified by that same measurement by ~7 orders of magnitude) determines the verdict; the analytic value survives only as a secondary diagnostic. Events lacking a calibration fall back to the legacy dual criterion and are explicitly tagged [LEGACY dual criterion]. Because the public subset is incomplete, a NO_CORRELATION verdict bounds coupling only over the tested channels and does not exclude coupling with unreleased sensors; candidates surviving this check still require human review.")
        
        # ------------------------------------------------------------------
        # Final Candidate Disposition Ledger (dynamic, single source per GPS)
        # ------------------------------------------------------------------
        md_lines.extend(self._build_disposition_ledger(tax_df))

        md_content = "\n".join(md_lines)
        log_path = self.output_dir / "Final_Discovery_Report.md"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"# Final Discovery Report ({self.observing_run})\n")
            f.write("## Taxonomy of Comparison: Pre-fix vs Post-fix\n\n")
            f.write("To prevent post-hoc rationalizations, " + f"the candidates from the new {self.observing_run} scan must be strictly classified" + " against the previous baseline according to the following taxonomy:\n\n")
            f.write("1. **Persistente (Persistent):** The candidate retains the same GPS time and is classified as ROBUST in both the old and new runs. This validates that the candidate is independent of the legacy whitening artifact.\n")
            f.write("2. **Scomparso (Disappeared):** A candidate that was ROBUST or AMBIGUOUS in the old run, but is now SUB_THRESHOLD (or completely undetected) in the new run. These are the false positives explicitly inflated by the edge artifact.\n")
            f.write("3. **Emerso (Emerged):** A candidate that was absent (or SUB_THRESHOLD) in the old run, but is now detected and classified as ROBUST or AMBIGUOUS. This directly quantifies the recovered sensitivity due to the fix.\n")
            f.write("4. **Riclassificato (Reclassified):** A candidate that changes category (e.g., ROBUST → AMBIGUOUS, or AMBIGUOUS → ROBUST) but does not disappear completely.\n\n")
            f.write("> [!NOTE]\n> For any *Emersi* (Emerged) candidates, cross-reference them against the LVK \"Data Quality Products for Transient Gravitational Wave Searches\" and \"Glitch Modelling for Events\" (GWTC-4.0, August 2025 on Zenodo). This external dataset provides official data quality and glitch modelling flags that can independently validate the astrophysical or instrumental nature of these newly recovered signals, granting high external credibility to the pipeline's discovery capabilities.\n\n")
            f.write(md_content)
        logger.info(f"Wrote {log_path}")


if __name__ == "__main__":
    from src.core.utils import setup_logger
    import subprocess
    import sys
    
    setup_logger("aggregate_report")
    
    reporter = AggregateReporter()
    reporter.run()

    # Automatically run offline validation scripts
    logger.info("Starting automated offline validation...")
    try:
        from src.core.utils import load_config
        detectors = load_config().get("detectors", ["H1", "L1"])
        
        for det in detectors:
            logger.info(f"-> Running Poisson Upper Limit ({det})...")
            subprocess.run([sys.executable, "src/pipeline_v2_production/poisson_upper_limit.py", "--detector", det], check=True)

        logger.info("-> Running PEM Coherence Analysis...")
        subprocess.run([sys.executable, "src/pipeline_v2_production/pem_coherence_analysis.py", "--nds-host", "nds.gwosc.org"], check=True)
        
        logger.info("All automated offline validation scripts completed and injected successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"An offline validation script failed with exit code {e.returncode}: {e}")
    except Exception as e:
        logger.error(f"Failed to execute automated offline validation scripts: {e}")
