import logging
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import scipy.stats as stats
from scipy.stats import genextreme
import hashlib
import os
import stat
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
    
    index_path = "data/reference/patch_compressed_index.npz"
    if os.path.exists(index_path):
        with open(index_path, 'rb') as f:
            md5_hash = hashlib.md5(f.read()).hexdigest()
        logger.info(f"Reference Index MD5 Checksum: {md5_hash}")
        # Forza in sola lettura per proteggere il reference index
        os.chmod(index_path, stat.S_IREAD)
        logger.info(f"Locked {index_path} to read-only mode.")
    else:
        logger.warning(f"Reference index {index_path} not found!")

    output_dir = Path("results/micro_mdc")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    spec_dir = output_dir / "temp_spectrograms"
    spec_dir.mkdir(parents=True, exist_ok=True)
    
    glitch_gen = SyntheticGlitchGenerator(sample_rate=4096)
    injector = InjectionEngine(sample_rate=4096)
    
    segment_length = 32
    available_starts = np.arange(session_gps_start, session_gps_end - segment_length, segment_length)
    
    results = []
    
    # 1. Mappa K specifici per classe
    k_map = {
        'AsymBlip': [1, 3, 5, 10],
        'SpiralBurst': [37, 68]
    }
    
    # Raccogli tutti i k univoci per calcolare le baseline una sola volta
    all_ks = set()
    for gtype in glitch_types:
        all_ks.update(k_map.get(gtype, k_values))
        
    baseline_cache = {}
    
    # --- Background Baseline Pass ---
    for k in sorted(list(all_ks)):
        logger.info(f"Extracting 500 NULL segments for baseline GEV fit (k={k})...")
        null_starts = np.random.choice(available_starts, size=min(500, len(available_starts)), replace=False)
        null_scores = []
        
        for seg_start in tqdm(null_starts, desc=f"Baseline pass k={k}"):
            seg_end = seg_start + segment_length
            try:
                ts_clean = fetch_strain_data(detector_name, seg_start, seg_end, cache_raw=True)
                ts_white = whiten(ts_clean)
                ts_bp = bandpass(ts_white)
                
                temp_path = spec_dir / f"null_{seg_start}.png"
                generate_qtransform(ts_bp, save_path=temp_path)
                
                res = detector.classify(temp_path, k=k, threshold=0.0) 
                null_scores.append(res['novelty_score'])
                
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                logger.warning(f"Failed baseline segment {seg_start}: {e}")
                
        if not null_scores:
            raise RuntimeError(f"Failed to compute baseline scores for k={k}!")
            
        c, loc, scale = genextreme.fit(null_scores)
        dynamic_threshold = genextreme.ppf(0.99, c, loc, scale)
        logger.info(f"GEV Fit parameters: c={c:.4f}, loc={loc:.4f}, scale={scale:.4f} -> Threshold (FPR 1%): {dynamic_threshold:.4f}")
        
        baseline_cache[k] = {
            'null_scores': null_scores,
            'dynamic_threshold': dynamic_threshold
        }
        
    # --- Injection Pass ---
    for gtype in glitch_types:
        current_ks = k_map.get(gtype, k_values)
        for idx, amp in enumerate(amplitudes):
            # Ripristinato n=20 fisso per ora per sfruttare la cache locale
            current_n_inj = 20
            logger.info(f"Injecting {gtype} at amp={amp:.2e} (n={current_n_inj})")
            
            inj_starts = np.random.choice(available_starts, size=current_n_inj, replace=False)
            
            for seg_start in tqdm(inj_starts, desc=f"Injections {gtype} amp={amp:.1e}"):
                seg_end = seg_start + segment_length
                t_inject = seg_start + segment_length / 2.0
                
                try:
                    ts_clean = fetch_strain_data(detector_name, seg_start, seg_end, cache_raw=True)
                    glitch = glitch_gen.generate(gtype, amp, duration=1.0)
                    ts_injected = injector.inject(ts_clean, glitch, t_inject)
                    snr = injector.compute_snr(ts_clean, glitch)
                    
                    ts_white = whiten(ts_injected)
                    ts_bp = bandpass(ts_white)
                    temp_path = spec_dir / f"inj_{gtype}_{seg_start}.png"
                    generate_qtransform(ts_bp, save_path=temp_path)
                    
                    # Esegui il calcolo contemporaneamente per tutti i K della classe per abbattere i tempi I/O
                    for k in current_ks:
                        dyn_thresh = baseline_cache[k]['dynamic_threshold']
                        res = detector.classify(temp_path, k=k, threshold=dyn_thresh)
                        
                        results.append({
                            "k": k,
                            "glitch_type": gtype,
                            "amplitude": amp,
                            "snr": snr,
                            "dynamic_threshold": dyn_thresh,
                            "novelty_score": res["novelty_score"],
                            "novelty_status": res["novelty_status"]
                        })
                        
                    if temp_path.exists():
                        temp_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed injection {gtype} at {seg_start}: {e}")

    df = pd.DataFrame(results)
    
    # 3. Integrazione Test KS (Kolmogorov-Smirnov)
    df["ks_statistic"] = np.nan
    df["ks_pvalue"] = np.nan
    
    # Raggruppa i risultati per calcolare il KS test cella per cella
    for (k, gtype, amp), group in df.groupby(["k", "glitch_type", "amplitude"]):
        bg_scores = baseline_cache[k]['null_scores']
        inj_scores = group["novelty_score"].values
        if len(inj_scores) > 0 and len(bg_scores) > 0:
            ks_res = stats.ks_2samp(bg_scores, inj_scores, alternative='greater')
            df.loc[group.index, "ks_statistic"] = ks_res.statistic
            df.loc[group.index, "ks_pvalue"] = ks_res.pvalue
            
    df.to_csv(output_dir / "micro_mdc_results.csv", index=False)
    
    # Calcola il summary esteso con i risultati KS
    summary = df.groupby(["k", "glitch_type", "amplitude"]).apply(
        lambda x: pd.Series({
            "snr_mean": x["snr"].mean(),
            "recall": (x["novelty_status"] == "NOVEL").mean(),
            "n_novel": (x["novelty_status"] == "NOVEL").sum(),
            "n_total": len(x),
            "ks_statistic": x["ks_statistic"].iloc[0] if not x.empty else np.nan,
            "ks_pvalue": x["ks_pvalue"].iloc[0] if not x.empty else np.nan
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
    
    # Temporary overrides for fast SpiralBurst K=68 validation
    glitch_types = ["SpiralBurst"]
    n_injections = 20
    n_amplitudes = mdc_cfg.get("n_amplitudes", 8)
    amp_min = mdc_cfg.get("amplitude_min", 1e-22)
    amp_max = mdc_cfg.get("amplitude_max", 1e-21)
    amplitudes = np.logspace(np.log10(amp_min), np.log10(amp_max), n_amplitudes)
    detector_name = mdc_cfg.get("detector", "L1")
    seed = mdc_cfg.get("seed", 42)
    
    # Mappa K specifica per glitch (override per validazione K=68)
    K_MAP = {
        "SpiralBurst": [68]
    }
    k_values = patch_cfg.get("k_sweep", [15, 37, 68])
    device = patch_cfg.get("device", "cuda")
    
    # Initialize the patch-level novelty detector
    detector = PatchLevelNoveltyDetector(
        index_path="data/reference/patch_compressed_index.npz",
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
