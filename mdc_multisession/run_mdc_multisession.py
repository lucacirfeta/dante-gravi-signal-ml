"""CLI entrypoint for the MDC Multi-Session standalone pipeline."""

import argparse
import logging
from pathlib import Path
import json

import numpy as np
import pandas as pd

from src.utils import setup_logger
from mdc_multisession.session_loader import load_session_smax
from mdc_multisession.threshold_calibrator import calibrate_tau_op
from mdc_multisession.mdc_engine import run_mdc_session
from mdc_multisession.results_aggregator import aggregate_session_metrics

logger = setup_logger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(description="Multi-Session MDC Standalone Pipeline")
    parser.add_argument("--detector", type=str, default="L1", help="Detector (H1 or L1)")
    parser.add_argument("--run", type=str, default="O4a", help="Run name (e.g., O4a)")
    parser.add_argument("--sessions", nargs="+", required=True, help="List of session IDs (e.g. 20260520_120000)")
    parser.add_argument("--fpr", type=float, default=0.0001, help="Target False Positive Rate for tau_op (default 0.0001 = 0.01%)")
    parser.add_argument("--glitches", nargs="+", default=["SpiralBurst", "StepLadder"], help="Glitch morphologies to inject")
    parser.add_argument("--amplitudes", nargs="+", type=float, default=[1e-21, 5e-21, 1e-20, 5e-20], help="Strain amplitudes")
    parser.add_argument("--n-inj", type=int, default=20, help="Number of injections per parameter pair")
    parser.add_argument("--mock-strain", action="store_true", help="Use synthetic Gaussian noise instead of GWOSC strain (useful for local laptops)")
    
    return parser.parse_args()

def main():
    args = parse_args()
    
    base_out = Path("data/mdc_multisession/outputs/per_session")
    base_out.mkdir(parents=True, exist_ok=True)
    
    amp_grid = np.array(args.amplitudes)
    
    for session_id in args.sessions:
        logger.info(f"=== Starting processing for {session_id} ===")
        session_out = base_out / session_id
        session_out.mkdir(exist_ok=True)
        
        # 1. Load Embeddings and Compute s_max
        try:
            s_max = load_session_smax(args.run, session_id, args.detector)
        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            continue
            
        s_max_mean = np.mean(s_max)
        s_max_std = np.std(s_max)
        logger.info(f"s_max distribution: mean={s_max_mean:.4f}, std={s_max_std:.4f}")
        
        # 2. Calibrate tau_op
        tau_op = calibrate_tau_op(s_max, fpr=args.fpr)
        
        # Save session metadata
        meta = pd.DataFrame([{
            "session": session_id,
            "s_max_mean": s_max_mean,
            "s_max_std": s_max_std,
            "fpr": args.fpr,
            "tau_op": tau_op
        }])
        meta.to_csv(session_out / "session_meta.csv", index=False)
        
        # 3. Extract GPS bounds dynamically from spectrogram files
        spec_dir = Path(f"data/runs/{args.run.lower()}/{session_id}/spectrograms/{args.detector}")
        if not spec_dir.exists():
            logger.error(f"Spectrogram dir not found: {spec_dir}")
            continue
            
        spec_files = sorted(list(spec_dir.glob("*.png")))
        if not spec_files:
            logger.error(f"No spectrograms found in {spec_dir}")
            continue
            
        first_file = spec_files[0].name
        last_file = spec_files[-1].name
        # format: L1_1382928032_1382928064.png
        try:
            gps_start = int(first_file.split("_")[1])
            gps_end = int(last_file.split("_")[2].split(".")[0])
        except Exception as e:
            logger.error(f"Error parsing GPS from filenames: {e}")
            continue
            
        logger.info(f"Session GPS Bounds: {gps_start} - {gps_end}")
        
        # 4. Run MDC Engine
        run_mdc_session(
            session_gps_start=gps_start,
            session_gps_end=gps_end,
            detector=args.detector,
            glitch_types=args.glitches,
            amplitude_grid=amp_grid,
            tau_op=tau_op,
            n_injections_per_type=args.n_inj,
            output_dir=session_out,
            mock_strain=args.mock_strain
        )
        
    logger.info("=== All sessions completed. Aggregating results... ===")
    agg_df = aggregate_session_metrics(base_out)
    
    agg_dir = Path("data/mdc_multisession/outputs/aggregate")
    agg_dir.mkdir(parents=True, exist_ok=True)
    
    agg_df.to_csv(agg_dir / "multisession_summary.csv", index=False)
    
    # Print a nice summary table
    print("\n" + "="*80)
    print(f"{'MDC MULTI-SESSION RECALL SUMMARY':^80}")
    print("="*80)
    
    # Pivot table for easy reading
    if not agg_df.empty:
        pivot = agg_df.pivot_table(
            index=["glitch_type", "amplitude"], 
            columns="session", 
            values="recall",
            aggfunc="first"
        ).round(2)
        print(pivot)
        
        print("\nSession Thresholds:")
        meta_pivot = agg_df[["session", "s_max_mean", "s_max_std", "tau_op"]].drop_duplicates().set_index("session").round(4)
        print(meta_pivot)
    else:
        print("No data aggregated.")
        
    print("="*80)

if __name__ == "__main__":
    main()
