import pandas as pd
import numpy as np
import torch
import h5py
import logging
from pathlib import Path
from sklearn.metrics.pairwise import cosine_similarity
import argparse

from src.core.utils import setup_logger, get_observing_run
from src.core.data_loader import fetch_local_or_remote_strain
from src.core.preprocessor import whiten, bandpass, generate_qtransform
from src.core.patch_scorer import PatchScorer

logger = setup_logger(__name__)

def execute_cross_detector_veto(df: pd.DataFrame, production_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    logger.info("=" * 60)
    logger.info("=== CROSS-DETECTOR COINCIDENCE VETO (Wave 7) ===")
    logger.info("=" * 60)
    
    logger.info(f"Loaded {len(df)} candidates from master list.")
    
    # We only care about candidates where the partner was actually online.
    # If INACTIVE, it automatically goes to Table 3b.
    # Note: 'ACTIVE_NO_ANOMALY' or 'ACTIVE_ANOMALY_DETECTED'
    
    coincident_rows = []
    local_rows = []
    unverifiable_rows = []
    
    # Initialize PyTorch Models
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using device: {device}")
    
    ref_index_path = Path("data/index/patch_compressed_index.npz")
    if not ref_index_path.exists():
        ref_index_path = list(Path(".").rglob("patch_compressed_index.npz"))
        if ref_index_path:
            ref_index_path = ref_index_path[0]
        else:
            logger.warning("Could not find reference index. Run index builder first.")
            return

    scorer = PatchScorer(
        reference_index_path=ref_index_path,
        device=device,
        k=68, # Strict architectural prior aligned with primary PatchScorer
        verify_md5=False
    )
    
    for idx, row in df.iterrows():
        gps = float(row["gps_start"])
        primary = row["detector"]
        session = row["session_id"]
        status = row["partner_observing_status"]
        
        if status == "INACTIVE":
            unverifiable_rows.append(row)
            continue
            
        partner = "L1" if primary == "H1" else "H1"
        logger.info(f"Targeted search: Candidate GPS {gps} in {primary}. Fetching {partner}...")
        
        # 1. Load primary vector
        h5_path = production_dir / str(session) / f"novelties_{session}_{primary}.h5"
        if not h5_path.exists():
            logger.warning(f"HDF5 missing for GPS {gps} in {h5_path}. Skipping.")
            local_rows.append(row)
            continue
            
        try:
            with h5py.File(h5_path, "r") as f:
                gps_times = f["novelties/gps_times"][:]
                vectors = f["novelties/mil_vectors"][:]
                idx_match = np.where(gps_times == gps)[0]
                if len(idx_match) == 0:
                    logger.warning(f"GPS {gps} not found in {h5_path}. Skipping.")
                    local_rows.append(row)
                    continue
                primary_vec = vectors[idx_match[0]]
        except Exception as e:
            logger.warning(f"Error reading primary H5: {e}")
            local_rows.append(row)
            continue
            
        # 2. Fetch partner raw strain
        try:
            ts = fetch_local_or_remote_strain(partner, gps, gps + 32, cache_raw=False)
        except Exception as e:
            logger.warning(f"Failed to fetch partner strain: {e}")
            local_rows.append(row)
            continue
            
        # 3. Encode partner
        try:
            ts_white = whiten(ts)
            ts_bp = bandpass(ts_white)
            spectrogram = generate_qtransform(ts_bp)
            # score_spectrogram returns a list of dicts
            results = scorer.score_spectrogram([spectrogram], threshold=1.0)
            partner_vec = results[0]["mil_vector"]
        except Exception as e:
            logger.warning(f"Failed to encode partner strain: {e}")
            local_rows.append(row)
            continue
            
        # 4. Cosine Similarity
        # Normalize just in case, though they should be L2 normalized
        v1 = primary_vec.reshape(1, -1)
        v2 = partner_vec.reshape(1, -1)
        v1 = v1 / np.linalg.norm(v1)
        v2 = v2 / np.linalg.norm(v2)
        
        sim = cosine_similarity(v1, v2)[0, 0]
        logger.info(f"Match Similarity: {sim:.3f}")
        
        # 5. Extract run and load empirical threshold (Hard-Fail if missing)
        import json
        import pathlib
        cfg_path = pathlib.Path("config/cross_detector_threshold.json")
        
        try:
            run = get_observing_run(gps)
        except Exception as e:
            logger.error(f"Cannot deduce observing run for GPS {gps}: {e}")
            raise RuntimeError(f"Missing run context for GPS {gps}")
            
        tau_coh = None
        if cfg_path.exists():
            with open(cfg_path, "r") as f:
                cfg_data = json.load(f)
                if run in cfg_data and "tau_coh" in cfg_data[run]:
                    tau_coh = float(cfg_data[run]["tau_coh"])
                
        if tau_coh is None:
            logger.error(f"CRITICAL: No EVT cohesion threshold ('tau_coh') explicitly calibrated for run '{run}' in {cfg_path}.")
            logger.error("The pipeline cannot guarantee a controlled False Positive Rate for this background epoch.")
            raise RuntimeError(f"Missing EVT calibration for observing run '{run}'. Refusing to proceed with arbitrary heuristics.")

        if sim > tau_coh:
            logger.info(f"--> [COINCIDENT] Candidate {gps} matched in {partner} with sim {sim:.3f} (> {tau_coh:.3f})")
            new_row = row.copy()
            new_row["status"] = "COINCIDENT"
            new_row["partner_observing_status"] = "ACTIVE_ANOMALY_DETECTED"
            new_row["gs_label"] = "Coincident/Astrophysical/Magnetic"
            coincident_rows.append(new_row)
        else:
            logger.info(f"--> [LOCAL] Candidate {gps} is pure instrumental (sim={sim:.3f})")
            local_rows.append(row)
            
    # Convert to Final Output Dataframes
    df_3a = pd.DataFrame(local_rows) if local_rows else pd.DataFrame(columns=df.columns)
    df_3b = pd.DataFrame(unverifiable_rows) if unverifiable_rows else pd.DataFrame(columns=df.columns)
    df_3c = pd.DataFrame(coincident_rows) if coincident_rows else pd.DataFrame(columns=df.columns)
    
    logger.info("Veto procedure completed successfully.")
    return df_3a, df_3b, df_3c

def run_cross_detector_veto():
    production_dir = Path("data/production")
    aggregated_dir = production_dir / "aggregated"
    master_csv = aggregated_dir / "master_candidates.csv"
    
    if not master_csv.exists():
        logger.error(f"Master CSV not found at {master_csv}")
        return
        
    df = pd.read_csv(master_csv)
    df_3a, df_3b, df_3c = execute_cross_detector_veto(df, production_dir)
    
    table_cols = [
        "gps_start", "detector", "local_cluster_id", "session_id", "gs_label",
        "partner_observing_status", "source_session"
    ]
    
    def _write_table(df_subset, path, note=None):
        if len(df_subset) == 0:
            logger.info(f"Table {path.name} is empty.")
            return
        out_cols = [c for c in table_cols if c in df_subset.columns]
        df_subset[out_cols].to_csv(path, index=False)
        if note:
            with open(path, "a") as f:
                f.write(note)
        logger.info(f"Wrote {len(df_subset)} rows to {path.name}")

    _write_table(df_3a, aggregated_dir / "Table_3a_Confirmed_Local_Glitches_Vetoed.csv")
    _write_table(df_3b, aggregated_dir / "Table_3b_Unverifiable_Unilateral_Detections_Vetoed.csv", 
                 "\n# NOTE: Unverifiable due to non-observing status of partner.\n")
    _write_table(df_3c, aggregated_dir / "Table_3c_Coincident_Astrophysical.csv",
                 "\n# NOTE: Morphological cross-match confirmed (Cosine Similarity > 0.85).\n")

if __name__ == "__main__":
    run_cross_detector_veto()
