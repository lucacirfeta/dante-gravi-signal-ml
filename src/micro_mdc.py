import logging
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from tqdm import tqdm

from src.injection import SyntheticGlitchGenerator, InjectionEngine, _load_all_references
from src.preprocessor import whiten, bandpass, generate_qtransform
from src.novelty_detector import PatchLevelNoveltyDetector
from src.data_loader import fetch_strain_data
from src.utils import setup_logger, load_config

logger = setup_logger(__name__)

def run_micro_mdc(
    detector: PatchLevelNoveltyDetector,
    session_gps_start: int,
    session_gps_end: int,
    detector_name: str = 'L1',
    glitch_types: list[str] = ['AsymBlip', 'SpiralBurst'],
    amplitudes: np.ndarray = np.logspace(-22, -21, 8),
    n_injections: int = 20,
    k_values: list[int] = [15, 37, 68],
    seed: int = 42
) -> pd.DataFrame:
    """Executes the micro-MDC loop to evaluate the patch-level MIL novelty detector."""
    np.random.seed(seed)
    output_dir = Path("results/micro_mdc")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    spec_dir = output_dir / "temp_spectrograms"
    spec_dir.mkdir(parents=True, exist_ok=True)
    
    glitch_gen = SyntheticGlitchGenerator(sample_rate=4096)
    injector = InjectionEngine(sample_rate=4096)
    
    segment_length = 32
    available_starts = np.arange(session_gps_start, session_gps_end - segment_length, segment_length)
    
    results = []
    
    for k in k_values:
        logger.info(f"=== Starting Micro-MDC for k={k} ===")
        
        # --- Background Baseline Pass ---
        # 1. Estrai 100 segmenti casuali di puro background (senza iniezioni)
        logger.info(f"Extracting 100 NULL segments for baseline (k={k})...")
        null_starts = np.random.choice(available_starts, size=min(100, len(available_starts)), replace=False)
        null_scores = []
        
        for seg_start in tqdm(null_starts, desc=f"Baseline pass k={k}"):
            seg_end = seg_start + segment_length
            try:
                ts_clean = fetch_strain_data(detector_name, seg_start, seg_end, cache_raw=True)
                ts_white = whiten(ts_clean)
                ts_bp = bandpass(ts_white)
                
                temp_path = spec_dir / f"null_{seg_start}.png"
                generate_qtransform(ts_bp, save_path=temp_path)
                
                # 2. Passali in detector.classify()
                # Use a dummy threshold for now since we just need the score
                res = detector.classify(temp_path, k=k, threshold=0.0) 
                null_scores.append(res['novelty_score'])
                
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                logger.warning(f"Failed baseline segment {seg_start}: {e}")
                
        if not null_scores:
            raise RuntimeError("Failed to compute baseline scores!")
            
        # 3. Calcola mean e std
        mu_hybrid = np.mean(null_scores)
        sigma_hybrid = np.std(null_scores)
        
        # 4. dynamic_threshold
        # As determined, anomalous patches have higher (less negative) scores.
        dynamic_threshold = mu_hybrid + (4 * sigma_hybrid)
        logger.info(f"Baseline for k={k}: mu={mu_hybrid:.4f}, sigma={sigma_hybrid:.4f} -> dynamic_threshold={dynamic_threshold:.4f}")
        
        # --- Injection Pass ---
        for gtype in glitch_types:
            for amp in amplitudes:
                logger.info(f"Injecting {gtype} at amp={amp:.2e}")
                inj_starts = np.random.choice(available_starts, size=n_injections, replace=False)
                
                for seg_start in tqdm(inj_starts, desc=f"Injections {gtype} amp={amp:.1e}"):
                    seg_end = seg_start + segment_length
                    t_inject = seg_start + segment_length / 2.0
                    
                    try:
                        # 1. Scarica strain reale
                        ts_clean = fetch_strain_data(detector_name, seg_start, seg_end, cache_raw=True)
                        # 2. Inietta glitch sintetico
                        glitch = glitch_gen.generate(gtype, amp, duration=1.0)
                        ts_injected = injector.inject(ts_clean, glitch, t_inject)
                        snr = injector.compute_snr(ts_clean, glitch)
                        
                        # 3. Applica whitening + bandpass + Q-transform
                        ts_white = whiten(ts_injected)
                        ts_bp = bandpass(ts_white)
                        temp_path = spec_dir / f"inj_{gtype}_{seg_start}.png"
                        # 4. Salva spettrogramma temporaneo
                        generate_qtransform(ts_bp, save_path=temp_path)
                        
                        # 5. detector.classify
                        res = detector.classify(temp_path, k=k, threshold=dynamic_threshold)
                        
                        # 6. Registra i risultati
                        results.append({
                            "k": k,
                            "glitch_type": gtype,
                            "amplitude": amp,
                            "snr": snr,
                            "dynamic_threshold": dynamic_threshold,
                            "novelty_score": res["novelty_score"],
                            "novelty_status": res["novelty_status"]
                        })
                        
                        if temp_path.exists():
                            temp_path.unlink()
                    except Exception as e:
                        logger.warning(f"Failed injection {gtype} at {seg_start}: {e}")

    df = pd.DataFrame(results)
    df.to_csv(output_dir / "micro_mdc_results.csv", index=False)
    
    # Calculate summary statistics to evaluate recall
    summary = df.groupby(["k", "glitch_type", "amplitude"]).apply(
        lambda x: pd.Series({
            "snr_mean": x["snr"].mean(),
            "recall": (x["novelty_status"] == "NOVEL").mean(),
            "n_novel": (x["novelty_status"] == "NOVEL").sum(),
            "n_total": len(x)
        })
    ).reset_index()
    summary.to_csv(output_dir / "micro_mdc_summary.csv", index=False)
    
    logger.info("Micro-MDC completed. Results saved to results/micro_mdc/")
    return df

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run Micro-MDC for Patch-Level Scoring")
    parser.add_argument("--start", type=int, default=1386795008, help="GPS Start Time (Default: 20260524 L1 start)")
    parser.add_argument("--end", type=int, default=1388003328, help="GPS End Time (Default: 20260524 L1 end)")
    args = parser.parse_args()
    
    cfg = load_config()
    mdc_cfg = cfg.get("micro_mdc", {})
    patch_cfg = cfg.get("patch_novelty", {})
    
    # Default parameters based on user instructions if config missing
    glitch_types = mdc_cfg.get("glitch_types", ["AsymBlip", "SpiralBurst"])
    n_injections = mdc_cfg.get("n_injections", 20)
    n_amplitudes = mdc_cfg.get("n_amplitudes", 8)
    amp_min = mdc_cfg.get("amplitude_min", 1e-22)
    amp_max = mdc_cfg.get("amplitude_max", 1e-21)
    amplitudes = np.logspace(np.log10(amp_min), np.log10(amp_max), n_amplitudes)
    detector_name = mdc_cfg.get("detector", "L1")
    seed = mdc_cfg.get("seed", 42)
    
    k_values = patch_cfg.get("k_sweep", [15, 37, 68])
    device = patch_cfg.get("device", "cuda")
    
    # Load reference index 
    ref_emb, ref_labels, _ = _load_all_references()
    logger.info(f"Loaded {len(ref_emb)} reference embeddings to use as patch-level proxies.")
    
    # Initialize the novelty detector
    detector = PatchLevelNoveltyDetector(
        reference_embeddings=ref_emb,
        reference_labels=ref_labels,
        device=device
    )
    
    # Execute the Micro-MDC
    run_micro_mdc(
        detector=detector,
        session_gps_start=args.start,
        session_gps_end=args.end,
        detector_name=detector_name,
        glitch_types=glitch_types,
        amplitudes=amplitudes,
        n_injections=n_injections,
        k_values=k_values,
        seed=seed
    )
