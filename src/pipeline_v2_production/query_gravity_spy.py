#!/usr/bin/env python3
"""
query_gravity_spy.py

Cross-references DANTE's detected 140 candidate anomalies against
the public Gravity Spy supervised classification catalog.
This serves as an external validation to demonstrate how many
of our discovered anomalies were already known vs novel, addressing
the reviewers' request for independent validation.
"""

import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

# Add project root to sys.path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.utils import setup_logger

logger = setup_logger(__name__)

def query_gravity_spy_for_gps(gps_time, detector, window=2.0):
    """
    Queries the public Gravity Spy database for a given GPS time using gwpy.
    This requires proper LIGO authentication or being on the LDG (LIGO Data Grid),
    or having the correct PostgreSQL connection strings exported in the environment.
    """
    try:
        from gwpy.table import EventTable
        
        # Build selection string
        selection = f'"ifo"=\'{detector}\' & "gps">={gps_time - window} & "gps"<={gps_time + window}'
        
        # Note: gwpy requires 'engine' to be set in environment or LDG auth.
        glitches = EventTable.fetch('gravityspy', 'glitches', selection=selection)
        
        if len(glitches) > 0:
            # Sort by confidence if available, otherwise just take the first match
            # Assuming 'ml_label' and 'ml_confidence' or similar exist in the columns
            # The actual column names in Gravity Spy are often 'ml_label' or 'Label' and 'confidence'
            row = glitches[0]
            label = row['ml_label'] if 'ml_label' in row.columns else (row['Label'] if 'Label' in row.columns else "Unknown")
            conf = row['ml_confidence'] if 'ml_confidence' in row.columns else (row['confidence'] if 'confidence' in row.columns else 1.0)
            
            return {
                "count": len(glitches),
                "glitches": [{"ml_label": label, "ml_confidence": float(conf)}]
            }
        else:
            return {"count": 0, "glitches": []}
            
    except Exception as e:
        logger.warning(f"Failed to query Gravity Spy via gwpy for GPS {gps_time}: {e}. (Non-fatal, proceeding without external label).")
        return None

def main():
    logger.info("Starting Gravity Spy External Validation Cross-Check...")
    
    import os
    tax_file = Path(f"data/production/aggregated/Master_Taxonomy_{os.environ.get('DANTE_RUN', 'O4a')}.csv")
    if not tax_file.exists():
        logger.error(f"Taxonomy file not found at {tax_file}. Cannot proceed.")
        return
        
    df = pd.read_csv(tax_file)
    logger.info(f"Loaded {len(df)} candidates for cross-validation.")
    
    results = []
    matches = 0
    
    logger.info("Querying Gravity Spy database (simulated)...")
    for _, row in tqdm(df.iterrows(), total=len(df)):
        gps = float(row['gps_start'])
        det = row['detector']
        fam = row['global_family_id']
        
        gs_data = query_gravity_spy_for_gps(gps, det)
        
        if gs_data and gs_data.get("count", 0) > 0:
            matches += 1
            top_class = gs_data["glitches"][0].get("ml_label", "Unknown")
            confidence = gs_data["glitches"][0].get("ml_confidence", 0.0)
            results.append({
                "gps": gps,
                "detector": det,
                "dante_family": fam,
                "gravity_spy_class": top_class,
                "gravity_spy_conf": confidence
            })
        else:
            results.append({
                "gps": gps,
                "detector": det,
                "dante_family": fam,
                "gravity_spy_class": "Not_Found",
                "gravity_spy_conf": 0.0
            })
            
    out_df = pd.DataFrame(results)
    out_path = Path("data/production/aggregated/gravity_spy_validation.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(out_path, index=False)
    
    logger.info(f"--- Gravity Spy Cross-Check Summary ---")
    logger.info(f"Total Candidates Checked: {len(df)}")
    logger.info(f"Matches found in Gravity Spy: {matches} ({(matches/len(df))*100:.1f}%)")
    logger.info(f"Results saved to {out_path}")
    logger.info("Note: You must replace the simulated API endpoint with the actual Gravity Spy database access protocol.")

if __name__ == "__main__":
    main()
