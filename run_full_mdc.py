import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from src.injection import run_mdc

if __name__ == "__main__":
    # Parameters for MDC Run
    detector = "L1"
    session_gps_start = 1369598418 + 3600 * 24 * 7
    session_gps_end = session_gps_start + 3600 * 24 * 7 # 1 week duration for plenty of segments
    glitch_types = ["SpiralBurst", "StepLadder", "NoiseBlob", "Butterfly", "ZSweep"]
    amplitude_grid = np.logspace(np.log10(1e-22), np.log10(2e-21), 10)
    n_injections_per_type = 50
    output_dir = Path("results/mdc_full")
    
    print(f"Starting FULL MDC Run:")
    print(f"Detector: {detector}")
    print(f"GPS Start: {session_gps_start}")
    print(f"GPS End: {session_gps_end}")
    print(f"Glitch Types: {glitch_types}")
    print(f"Amplitudes: {len(amplitude_grid)} levels from {amplitude_grid[0]:.1e} to {amplitude_grid[-1]:.1e}")
    print(f"Injections per type/amp: {n_injections_per_type}")
    print(f"Total planned injections: {len(glitch_types) * len(amplitude_grid) * n_injections_per_type} + 1000 NULLs")
    
    df_summary = run_mdc(
        session_gps_start=session_gps_start,
        session_gps_end=session_gps_end,
        detector=detector,
        glitch_types=glitch_types,
        n_injections_per_type=n_injections_per_type,
        amplitude_grid=amplitude_grid,
        output_dir=output_dir,
        seed=42
    )
    
    print("\nResults Summary:")
    print(df_summary)
