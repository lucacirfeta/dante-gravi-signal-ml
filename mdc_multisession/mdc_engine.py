"""Standalone MDC Engine using pre-calibrated GEV thresholds."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

from src.utils import load_config
from src.preprocessor import whiten, bandpass, generate_qtransform
from src.encoder import DINOv2Encoder
from src.injection import SyntheticGlitchGenerator, InjectionEngine, _load_all_references
from src.similarity_checker import cosine_knn_search

logger = logging.getLogger(__name__)

def run_mdc_session(
    session_gps_start: int,
    session_gps_end: int,
    detector: str,
    glitch_types: list[str],
    amplitude_grid: np.ndarray,
    tau_op: float,
    n_injections_per_type: int = 50,
    output_dir: Path = None,
    seed: int = 42,
    mock_strain: bool = False,
) -> pd.DataFrame:
    """Run the Mock Data Challenge for a specific session using a pre-calibrated tau_op.
    
    Args:
        session_gps_start: Session GPS start time.
        session_gps_end: Session GPS end time.
        detector: Detector (e.g., 'H1' or 'L1').
        glitch_types: List of synthetic glitch morphologies to inject.
        amplitude_grid: Grid of amplitudes for the injections.
        tau_op: The session-local GEV operational threshold.
        n_injections_per_type: Number of injections per (type, amplitude).
        output_dir: Directory to save temporary spectrograms.
        seed: Random seed.
        
    Returns:
        pd.DataFrame: Summary metrics DataFrame.
    """
    np.random.seed(seed)
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        spec_dir = output_dir / "injected_spectrograms"
        spec_dir.mkdir(exist_ok=True)
    else:
        spec_dir = Path("tmp/mdc_multisession")
        spec_dir.mkdir(parents=True, exist_ok=True)
        
    # Initialize components
    glitch_gen = SyntheticGlitchGenerator(sample_rate=4096)
    injector = InjectionEngine(sample_rate=4096)
    encoder = DINOv2Encoder()
    
    # Load references
    ref_emb, ref_labels, _ = _load_all_references()
    
    # Segment selection (32s segments)
    segment_length = 32
    available_starts = np.arange(session_gps_start, session_gps_end - segment_length, segment_length)
    
    # Define execution sequence
    tasks = []
    
    # Add NULL injections for baseline sanity check
    for i in range(20):
        tasks.append(("NULL", 0.0, i))
        
    # Add actual injections
    for gtype in glitch_types:
        for amp in amplitude_grid:
            for i in range(n_injections_per_type):
                tasks.append((gtype, amp, i))
                
    np.random.shuffle(tasks)
    
    from src.data_loader import fetch_strain_data
    
    results = []
    saved_specs = {gt: 0 for gt in glitch_types + ["NULL"]}
    
    pbar = tqdm(tasks, desc=f"MDC Injections ({detector} | tau_op={tau_op:.4f})")
    
    for gtype, amp, idx in pbar:
        seg_start = np.random.choice(available_starts)
        seg_end = seg_start + segment_length
        
        try:
            if mock_strain:
                # Generate synthetic Gaussian noise mimicking white strain
                # 4096 Hz * 32s = 131072 samples
                noise_std = 1e-21  # typical amplitude scale
                ts_clean_data = np.random.normal(0, noise_std, int(4096 * segment_length))
                from gwpy.timeseries import TimeSeries
                ts_clean = TimeSeries(ts_clean_data, t0=seg_start, dt=1.0/4096, name=detector)
            else:
                ts_clean = fetch_strain_data(detector, seg_start, seg_end, cache_raw=True)
                
            t_inject = seg_start + segment_length / 2.0
            
            if gtype == "NULL":
                ts_injected = ts_clean
                snr = 0.0
            else:
                glitch = glitch_gen.generate(gtype, amp, duration=1.0)
                ts_injected = injector.inject(ts_clean, glitch, t_inject)
                snr = injector.compute_snr(ts_clean, glitch)
                
            ts_white = whiten(ts_injected)
            ts_bp = bandpass(ts_white)
            ts_crop = ts_bp.crop(seg_start, seg_end)
            
            save_spec_path = None
            if saved_specs[gtype] < 3:
                save_spec_path = spec_dir / f"{gtype}_amp{amp:.1e}_{idx}.png"
                saved_specs[gtype] += 1
                
            if save_spec_path is None:
                temp_path = spec_dir / "temp.png"
                generate_qtransform(ts_crop, save_path=temp_path)
                target_path = temp_path
            else:
                target_path = save_spec_path
                generate_qtransform(ts_crop, save_path=target_path)
                
            emb = encoder.extract(target_path)
            
            if save_spec_path is None and temp_path.exists():
                temp_path.unlink()
                
            emb_batch = np.array([emb])
            knn_res = cosine_knn_search(emb_batch, ref_emb, ref_labels, k=1)[0]
            
            s_max = knn_res["top_similarity"]
            
            # Strict decision rule using local tau_op
            status = "NOVEL" if s_max < tau_op else "KNOWN"
            
            results.append({
                "glitch_type": gtype,
                "amplitude": amp,
                "snr": snr,
                "novelty_status": status,
                "top_similarity": s_max,
                "gps_time": t_inject
            })
            
            pbar.set_postfix({"gtype": gtype, "snr": f"{snr:.1f}", "status": status, "s_max": f"{s_max:.4f}"})
            
        except Exception as e:
            logger.warning(f"Failed injection {gtype} at {seg_start}: {e}")
            continue
            
    df = pd.DataFrame(results)
    if output_dir:
        df.to_csv(output_dir / "mdc_raw_results.csv", index=False)
        
    summary = []
    
    for gtype in df["glitch_type"].unique():
        if gtype == "NULL":
            subset = df[df["glitch_type"] == "NULL"]
            n_tot = len(subset)
            n_nov = sum(subset["novelty_status"] == "NOVEL")
            recall = n_nov / n_tot if n_tot > 0 else 0
            summary.append({
                "glitch_type": "NULL",
                "amplitude": 0.0,
                "snr_mean": 0.0,
                "snr_std": 0.0,
                "recall": recall,
                "n_novel": n_nov,
                "n_total": n_tot
            })
            continue
            
        for amp in amplitude_grid:
            subset = df[(df["glitch_type"] == gtype) & (np.isclose(df["amplitude"], amp, atol=1e-30, rtol=1e-5))]
            if len(subset) == 0:
                continue
                
            snr_mean = subset["snr"].mean()
            snr_std = subset["snr"].std()
            n_tot = len(subset)
            n_nov = sum(subset["novelty_status"] == "NOVEL")
            recall = n_nov / n_tot if n_tot > 0 else 0
            
            summary.append({
                "glitch_type": gtype,
                "amplitude": amp,
                "snr_mean": snr_mean,
                "snr_std": snr_std,
                "recall": recall,
                "n_novel": n_nov,
                "n_total": n_tot
            })
            
    summary_df = pd.DataFrame(summary)
    if output_dir:
        summary_df.to_csv(output_dir / "mdc_results.csv", index=False)
        
    return summary_df
