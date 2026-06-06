"""Aggregates results across multiple MDC sessions."""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

def aggregate_session_metrics(base_dir: Path) -> pd.DataFrame:
    """Read all per-session MDC metrics and output a consolidated view.
    
    Args:
        base_dir: Path to `data/mdc_multisession/outputs/per_session/`
        
    Returns:
        pd.DataFrame: Aggregated results.
    """
    rows = []
    
    for session_dir in base_dir.iterdir():
        if not session_dir.is_dir():
            continue
            
        session_id = session_dir.name
        meta_path = session_dir / "session_meta.csv"
        results_path = session_dir / "mdc_results.csv"
        
        if not meta_path.exists() or not results_path.exists():
            logger.warning(f"Missing data for session {session_id}")
            continue
            
        # Read metadata (tau_op, fpr, s_max_mean, s_max_std, etc.)
        meta = pd.read_csv(meta_path).iloc[0].to_dict()
        
        # Read results
        results = pd.read_csv(results_path)
        
        for _, row in results.iterrows():
            combined = {
                "session": session_id,
                "tau_op": meta["tau_op"],
                "s_max_mean": meta["s_max_mean"],
                "s_max_std": meta["s_max_std"],
                "fpr": meta["fpr"],
                "glitch_type": row["glitch_type"],
                "amplitude": row["amplitude"],
                "snr_mean": row["snr_mean"],
                "recall": row["recall"]
            }
            rows.append(combined)
            
    df = pd.DataFrame(rows)
    return df
